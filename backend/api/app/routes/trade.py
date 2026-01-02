"""Trade orchestration routes tying quotes to relayer commits."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections.abc import Awaitable, Mapping
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from typing import Any, cast

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import APIRouter, Depends, Header, HTTPException, status
from shared import models
from shared.logging import log_event
from shared.merkle import build_merkle_path, build_merkle_root_and_paths
from shared.onchain import OnChainConfigurationError, get_async_web3, load_account, to_checksum
from shared.onchain.abi import ERC20_ABI, MARKET_FACTORY_ABI, PROTOCOL_POOL_ABI, REVEAL_MARKET_ABI
from shared.poseidon import BATCH_SIZE, compute_leaf, int_to_bytes32, int_to_hex32, poseidon_t3
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from web3 import Web3
from web3.exceptions import Web3RPCError

from app import repository_async, schemas
from app.database import get_session
from app.routes import pricing as pricing_routes
from app.runtime import logger
from app.runtime import settings as runtime_settings
from app.services.cache_client import get_cache_client

COMMITTED_EVENT_SIG = Web3.keccak(text="Committed(uint256,bytes32,uint256)").hex()
ESCROW_ABI = [
    {
        "name": "balances",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    }
]
_RESERVE_TICKET_LUA = """
local key = KEYS[1]
local base = tonumber(ARGV[1])
local current = redis.call('GET', key)
if not current then
  current = base
else
  current = tonumber(current)
  if current < base then
    current = base
  end
end
local next_val = current + 1
redis.call('SET', key, next_val)
return next_val
"""
settings: Any = cast(Any, runtime_settings)

router = APIRouter()


def _strip_hex(value: str) -> str:
    return value[2:] if value.startswith("0x") else value


def _ensure_0x(value: str) -> str:
    return value if value.startswith("0x") else f"0x{value}"


def _normalize_bytes32(value: Any) -> str | None:
    """Return a 0x-prefixed hex string for bytes/HexBytes values."""

    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return "0x" + value.hex()
    hex_value = getattr(value, "hex", None)
    if callable(hex_value):
        try:
            result = hex_value()
            return result if isinstance(result, str) else str(result)
        except Exception:
            return None
    return str(value)


def _is_empty_hex(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (bytes, bytearray)):
        return len(value) == 0 or all(b == 0 for b in value)
    if not isinstance(value, str):
        value = str(value)
    cleaned = value.strip().lower()
    if cleaned.startswith("0x"):
        cleaned = cleaned[2:]
    if not cleaned:
        return True
    return all(ch == "0" for ch in cleaned)


def _parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


async def _fetch_claimed_tickets(market_address: str, ticket_ids: list[int]) -> dict[int, bool]:
    if not settings.rpc_url or not ticket_ids:
        return {}
    try:
        web3 = get_async_web3(str(settings.rpc_url))
        contract = web3.eth.contract(address=to_checksum(market_address), abi=REVEAL_MARKET_ABI)
        calls = [contract.functions.claimedTickets(int(ticket_id)).call() for ticket_id in ticket_ids]
        results = await asyncio.gather(*calls, return_exceptions=True)
    except Exception as exc:  # pragma: no cover - best-effort chain checks
        log_event(
            logger,
            logging.DEBUG,
            event="trade.claimed_tickets.fetch_failed",
            message="failed to fetch claimed tickets from chain",
            market_address=market_address,
            error=str(exc),
        )
        return {}
    claimed: dict[int, bool] = {}
    for ticket_id, result in zip(ticket_ids, results, strict=False):
        if isinstance(result, BaseException):
            continue
        claimed[int(ticket_id)] = bool(result)
    return claimed


async def _sync_claimed_commitments(
    session: AsyncSession,
    rows: list[tuple[models.Commitment, models.Market, models.Settlement | None]],
) -> None:
    if not settings.rpc_url:
        return
    markets_to_check: dict[str, list[models.Commitment]] = {}
    for commitment, market, settlement in rows:
        if commitment.claimed_at is not None:
            continue
        if commitment.leaf_index is None or not market.market_address:
            continue
        if settlement is None or settlement.winning_outcome_id is None:
            continue
        if settlement.winning_outcome_id != commitment.outcome_id:
            continue
        if not _has_valid_roots(settlement):
            continue
        markets_to_check.setdefault(market.market_address, []).append(commitment)

    if not markets_to_check:
        return
    now = datetime.now(tz=UTC)
    for market_address, commitments in markets_to_check.items():
        ticket_ids = [int(commitment.leaf_index) for commitment in commitments if commitment.leaf_index is not None]
        claimed_map = await _fetch_claimed_tickets(market_address, ticket_ids)
        if not claimed_map:
            continue
        for commitment in commitments:
            if commitment.leaf_index is None:
                continue
            if claimed_map.get(int(commitment.leaf_index)):
                commitment.claimed_at = now
                session.add(commitment)
    await session.flush()


async def _fetch_claim_deadlines(market_addresses: list[str]) -> dict[str, int]:
    if not settings.rpc_url or not market_addresses:
        return {}
    web3 = get_async_web3(str(settings.rpc_url))
    tasks = []
    addresses: list[str] = []
    for address in market_addresses:
        try:
            contract = web3.eth.contract(address=to_checksum(address), abi=REVEAL_MARKET_ABI)
        except Exception as exc:
            log_event(
                logger,
                logging.DEBUG,
                event="trade.claim_deadline.contract_failed",
                message="failed to init market contract for claim deadline",
                market_address=address,
                error=str(exc),
            )
            continue
        addresses.append(address)
        tasks.append(contract.functions.claimDeadline().call())
    if not tasks:
        return {}
    results = await asyncio.gather(*tasks, return_exceptions=True)
    deadlines: dict[str, int] = {}
    for address, result in zip(addresses, results, strict=False):
        if isinstance(result, BaseException):
            continue
        try:
            deadlines[address] = int(result)
        except (TypeError, ValueError):
            continue
    return deadlines


def _raw_tx_bytes(signed_tx: Any) -> bytes:
    raw_tx = getattr(signed_tx, "raw_transaction", None)
    if raw_tx is None:
        raw_tx = getattr(signed_tx, "rawTransaction", None)
    if raw_tx is None:  # pragma: no cover - defensive for web3 variants
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="signed_tx_missing_raw_transaction")
    return cast(bytes, raw_tx)


def _is_placeholder_private_key(raw_key: str | None) -> bool:
    """Return True when the provided key is effectively zeroed out."""

    if not raw_key:
        return False
    normalized = raw_key.strip().lower()
    if normalized.startswith("0x"):
        normalized = normalized[2:]
    return bool(normalized) and set(normalized) == {"0"}


def _zen_to_wei(value: float | Decimal) -> int:
    """Scale a ZEN-denominated value to wei using safe rounding."""

    quantized = (Decimal(str(value)) * Decimal("1e18")).to_integral_value(rounding=ROUND_DOWN)
    return int(quantized)


def _relayer_url(path: str) -> str:
    """Normalize relayer base URL and join a path without duplicate slashes."""

    if not settings.relayer_base_url:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="relayer_unconfigured")
    base = str(settings.relayer_base_url).rstrip("/")
    suffix = path.lstrip("/")
    return f"{base}/{suffix}"


def _sign_quote_for_commit(quote: schemas.PricingQuotePayload) -> schemas.PricingQuotePayload:
    if settings.pricing_chain_id is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="pricing_chain_missing")
    if not quote.quote_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="quote_missing_id")
    if not quote.market_address or not quote.wallet_address or quote.outcome_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="wallet_address, market_address, and outcome_id are required for signed quotes",
        )
    expiry_ts = quote.expiry_ts
    if not expiry_ts:
        expires_at = quote.expires_at
        if isinstance(expires_at, str):
            try:
                normalized = expires_at.replace("Z", "+00:00")
                expires_at = datetime.fromisoformat(normalized)
            except Exception:
                expires_at = None
        expiry_ts = int(expires_at.timestamp()) if expires_at else 0
    if not expiry_ts:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="quote_expiry_missing")
    raw_signer_key = settings.pricing_signer_private_key
    signer_key = raw_signer_key.get_secret_value() if hasattr(raw_signer_key, "get_secret_value") else raw_signer_key
    if not signer_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="pricing_signer_unavailable")
    signer_account = load_account(str(signer_key))
    digest = pricing_routes.build_quote_digest(
        settings.pricing_chain_id,
        quote.market_address,
        quote.wallet_address,
        int(quote.outcome_id),
        int(quote.stake_wei),
        int(quote.zen_usd_scaled),
        int(expiry_ts),
        quote.quote_id,
    )
    signed = Account.sign_message(encode_defunct(hexstr=digest.hex()), signer_account.key)
    quote.signature = signed.signature.hex()
    quote.signer = signer_account.address
    quote.expiry_ts = int(expiry_ts)
    return quote


async def _fetch_escrow_balance(wallet_address: str) -> int | None:
    """Return escrow balance for a wallet if escrow + RPC are configured."""

    if not settings.relayer_escrow_address or not settings.rpc_url:
        return None
    try:
        web3 = get_async_web3(str(settings.rpc_url))
        escrow = web3.eth.contract(address=to_checksum(settings.relayer_escrow_address), abi=ESCROW_ABI)
        balance = await escrow.functions.balances(Web3.to_checksum_address(wallet_address)).call()
        return int(balance)
    except Exception:
        return None


async def _assert_protocol_pool_headroom(market_onchain_id: int | None, market_address: str, required_wei: int) -> None:
    """Best-effort guard to ensure protocol pool has headroom for the projected top-up."""

    if required_wei <= 0:
        return
    if not settings.rpc_url:
        return
    if market_onchain_id is None or not settings.factory_address:
        return
    try:
        web3 = get_async_web3(str(settings.rpc_url))
        factory = web3.eth.contract(address=to_checksum(settings.factory_address), abi=MARKET_FACTORY_ABI)
        params = await factory.functions.getMarketParams(int(market_onchain_id)).call()
        protocol_pool_address = params[11]
    except Exception as exc:
        log_event(
            logger,
            logging.DEBUG,
            event="protocol_pool.params_fetch_failed",
            message="could not fetch protocol pool params; skipping headroom check",
            error=str(exc),
            market_onchain_id=market_onchain_id,
        )
        return
    if not protocol_pool_address or _strip_hex(protocol_pool_address) == "":
        return
    try:
        pool_address = to_checksum(protocol_pool_address)
        market_checksum = to_checksum(market_address)
        pool = web3.eth.contract(address=pool_address, abi=PROTOCOL_POOL_ABI)
        allowed = await pool.functions.allowedMarket(market_checksum).call()
        capacity_wei = int(await pool.functions.capacity().call())
        liability_cap_wei = int(await pool.functions.liabilityCap(market_checksum).call())
        consumed_wei = int(await pool.functions.consumedLiability(market_checksum).call())
        token_address = await pool.functions.COLLATERAL_TOKEN().call()
        token = web3.eth.contract(address=to_checksum(token_address), abi=ERC20_ABI)
        balance_wei = int(await token.functions.balanceOf(pool_address).call())
    except Exception as exc:
        log_event(
            logger,
            logging.DEBUG,
            event="protocol_pool.headroom_fetch_failed",
            message="could not fetch protocol pool headroom; skipping guard",
            error=str(exc),
            pool_address=protocol_pool_address,
        )
        return

    remaining_cap = None
    if liability_cap_wei > 0:
        remaining_cap = max(0, liability_cap_wei - consumed_wei)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "protocol_pool_unregistered", "message": "Market not registered with protocol pool"},
        )
    if capacity_wei > 0 and required_wei > capacity_wei:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "protocol_pool_capacity", "message": "Protocol pool global capacity exceeded"},
        )
    if remaining_cap is not None and required_wei > remaining_cap:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "protocol_pool_cap", "message": "Protocol pool liability cap exceeded for this market"},
        )
    if required_wei > balance_wei:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "protocol_pool_balance", "message": "Protocol pool lacks collateral for this trade"},
        )


async def _sync_market_factory_params(
    session: AsyncSession,
    *,
    market_record: models.Market | None,
    market_address: str,
    market_onchain_id: int | None,
    auth_signer_key: str,
) -> int | None:
    """Fetch factory params to guard commit configuration and sync rake/factory metadata."""

    if not settings.factory_address or not settings.rpc_url:
        return None

    web3 = get_async_web3(str(settings.rpc_url))
    resolved_market_id = market_onchain_id
    if resolved_market_id is None:
        try:
            contract = web3.eth.contract(address=to_checksum(market_address), abi=REVEAL_MARKET_ABI)
            resolved_market_id = int(await contract.functions.marketId().call())
            if market_record and market_record.onchain_market_id is None:
                market_record.onchain_market_id = resolved_market_id
                session.add(market_record)
                await session.flush()
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                event="trade.market_id_fetch_failed",
                message="failed to resolve market id for factory sync",
                market_address=market_address,
                error=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="market_id_unavailable",
            ) from exc

    if resolved_market_id is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="market_id_unavailable")

    try:
        factory = web3.eth.contract(address=to_checksum(settings.factory_address), abi=MARKET_FACTORY_ABI)
        params = await factory.functions.getMarketParams(int(resolved_market_id)).call()
    except Exception as exc:
        log_event(
            logger,
            logging.WARNING,
            event="trade.market_params_fetch_failed",
            message="failed to fetch market params from factory",
            market_onchain_id=resolved_market_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="market_params_unavailable",
        ) from exc

    onchain_market = params[0]
    ticket_size = int(params[5])
    auth_signer = params[7]
    rake_bps = int(params[9])
    circuit_hash = _normalize_bytes32(params[3]) or str(params[3])
    params_market_id = int(params[12]) if params[12] is not None else resolved_market_id

    if _is_empty_hex(onchain_market):
        onchain_market = None
    if _is_empty_hex(auth_signer):
        auth_signer = None

    if onchain_market is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="market_unregistered")

    if market_address and str(onchain_market).lower() != str(market_address).lower():
        log_event(
            logger,
            logging.WARNING,
            event="trade.market_address_mismatch",
            message="factory market address mismatch",
            market_address=market_address,
            factory_address=onchain_market,
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="market_address_mismatch")

    expected_ticket_size = int(settings.ticket_size_wei)
    if ticket_size != expected_ticket_size:
        log_event(
            logger,
            logging.WARNING,
            event="trade.ticket_size_mismatch",
            message="factory ticket size mismatch",
            expected=expected_ticket_size,
            actual=ticket_size,
            market_id=resolved_market_id,
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ticket_size_mismatch")

    expected_circuit = settings.circuit_hash
    if expected_circuit and circuit_hash.lower() != expected_circuit.lower():
        log_event(
            logger,
            logging.WARNING,
            event="trade.circuit_hash_mismatch",
            message="factory circuit hash mismatch",
            expected=expected_circuit,
            actual=circuit_hash,
            market_id=resolved_market_id,
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="circuit_hash_mismatch")

    expected_signer = settings.authorization_signer or Account.from_key(auth_signer_key).address
    if auth_signer is None or expected_signer.lower() != str(auth_signer).lower():
        log_event(
            logger,
            logging.WARNING,
            event="trade.authorization_signer_mismatch",
            message="factory authorization signer mismatch",
            expected=expected_signer,
            actual=auth_signer,
            market_id=resolved_market_id,
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="authorization_signer_mismatch")

    expected_rake_bps = int(round(float(settings.rake_percent) * 10_000)) if settings.rake_percent is not None else None
    if expected_rake_bps is not None and rake_bps != expected_rake_bps:
        log_event(
            logger,
            logging.WARNING,
            event="trade.rake_bps_mismatch",
            message="factory rake mismatch",
            expected=expected_rake_bps,
            actual=rake_bps,
            market_id=resolved_market_id,
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="rake_bps_mismatch")

    if market_record:
        updated = False
        if market_record.market_address is None:
            market_record.market_address = str(onchain_market)
            updated = True
        if market_record.onchain_market_id is None:
            market_record.onchain_market_id = params_market_id
            updated = True
        if market_record.factory is None or str(market_record.factory).lower() != str(settings.factory_address).lower():
            market_record.factory = str(settings.factory_address)
            updated = True
        if market_record.rake_bps != rake_bps:
            market_record.rake_bps = rake_bps
            updated = True
        if updated:
            session.add(market_record)
            await session.flush()

    return rake_bps


async def _enqueue_relayer_job(kind: str, endpoint: str, payload: dict[str, Any]) -> str:
    """Enqueue a relayer job in Redis when immediate call fails."""

    if not settings.relayer_queue_enabled:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="relayer_unavailable")
    cache = await get_cache_client()
    if cache is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="relayer_queue_unavailable")
    job_id = secrets.token_hex(16)
    body = {
        "job_id": job_id,
        "kind": kind,
        "endpoint": endpoint,
        "payload": payload,
        "attempts": 0,
        "enqueued_at": int(time.time()),
    }
    await cast(Awaitable[Any], cache.lpush(settings.relayer_queue_key, json.dumps(body)))
    return job_id


async def _call_relayer(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST to the relayer with simple retries and friendlier errors."""

    if not settings.relayer_base_url:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="relayer_unconfigured")
    headers = {}
    if settings.relayer_bearer_token:
        headers["Authorization"] = f"Bearer {settings.relayer_bearer_token}"
    attempts = max(1, int(getattr(settings, "relayer_retry_attempts", 0) or 0) + 1)
    backoff = float(getattr(settings, "relayer_retry_backoff_seconds", 0.0) or 0.0)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)
            if resp.status_code in (200, 202):
                return resp.json()
            detail_text = resp.text
            try:
                parsed = resp.json()
                if isinstance(parsed, dict) and parsed.get("detail"):
                    detail_text = str(parsed.get("detail"))
                elif isinstance(parsed, dict) and parsed.get("error"):
                    detail_text = str(parsed.get("error"))
            except Exception as exc:  # pragma: no cover - defensive parse
                log_event(
                    logger,
                    logging.DEBUG,
                    event="relayer.response.parse_error",
                    message="failed to parse relayer response body",
                    error=str(exc),
                    status_code=resp.status_code,
                )
            if resp.status_code in {502, 503, 504} and attempt + 1 < attempts:
                await asyncio.sleep(backoff)
                continue
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"relayer_error:{resp.status_code}:{detail_text}",
            )
        except HTTPException:
            raise
        except Exception as exc:  # pragma: no cover - network errors
            last_error = exc
            if attempt + 1 < attempts:
                await asyncio.sleep(backoff)
                continue
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY, detail=str(last_error) if last_error else "relayer_failed"
    )


async def _get_quote(session: AsyncSession, quote_id: str) -> tuple[Any, schemas.PricingQuotePayload]:
    db_quote = await repository_async.get_quote(session, quote_id)
    if db_quote is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="quote_not_found")
    if db_quote.status != "issued":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="quote_already_consumed")
    payload = db_quote.payload
    try:
        return db_quote, schemas.PricingQuotePayload.model_validate(payload)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"invalid_quote_payload: {exc}") from exc


def _normalize_tx_hash(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.lower().startswith("0x"):
        stripped = stripped.lower()
        return stripped if len(stripped) == 66 else None
    # Allow bare 64-hex strings (some relayer/web3 variants omit 0x).
    if len(stripped) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in stripped):
        return f"0x{stripped.lower()}"
    return None


def _is_hex_tx(value: str | None) -> bool:
    return _normalize_tx_hash(value) is not None


def _extract_tx_hash(data: Mapping[str, Any] | None) -> str | None:
    if not data:
        return None
    for key in ("txHash", "tx_hash", "transactionHash", "transaction_hash"):
        value = data.get(key)
        normalized = _normalize_tx_hash(value)
        if normalized:
            return normalized
    return None


def _extract_job_id(data: Mapping[str, Any] | None) -> str | None:
    if not data:
        return None
    for key in ("jobId", "job_id", "job"):
        value = data.get(key)
        if value:
            return str(value)
    return None


async def _maybe_replace_job_tx_hash(session: AsyncSession, job_id: str, resolved_tx: str) -> None:
    """Replace a stored job id with the finalized tx hash (best-effort)."""

    if not job_id or not resolved_tx or not _is_hex_tx(resolved_tx):
        return
    try:
        await repository_async.update_commitment_tx_hash(session, job_id, resolved_tx)
    except Exception as exc:
        log_event(
            logger,
            logging.DEBUG,
            event="trade.status.tx_hash_update_failed",
            message="failed to replace relayer job id with tx hash",
            job_id=job_id,
            tx_hash=resolved_tx,
            error=str(exc),
        )


async def _resolve_job_tx_hash(session: AsyncSession, job_id: str) -> str | None:
    """Best-effort resolution of a relayer job id to a real tx hash, updating commitments if found."""

    if not job_id:
        return None
    cache = await get_cache_client()
    if cache is not None:
        cached = await cache.get(f"{settings.relayer_queue_key}:result:{job_id}")
        if cached:
            try:
                cached_result = json.loads(cached)
            except Exception:
                cached_result = {}
            resolved = _extract_tx_hash(cached_result)
            if resolved and _is_hex_tx(resolved):
                await _maybe_replace_job_tx_hash(session, job_id, resolved)
                return resolved
    if not settings.relayer_base_url:
        return None
    try:
        status_url = _relayer_url("status")
        result = await _call_relayer(status_url, {"jobId": job_id})
    except Exception:
        return None
    resolved_tx = _extract_tx_hash(result)
    if resolved_tx and _is_hex_tx(resolved_tx):
        await _maybe_replace_job_tx_hash(session, job_id, resolved_tx)
        return resolved_tx
    return None


def _require_auth_signer():
    raw = settings.authorization_signer_private_key
    if raw is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="auth_signer_missing")
    return raw.get_secret_value() if hasattr(raw, "get_secret_value") else str(raw)


async def _next_ticket_id_onchain(market_address: str, market_db_id: int, session: AsyncSession) -> int:
    """Derive next ticket id by reconciling on-chain Committed events with DB state.

    To avoid silent desync, we fail when counts diverge unless the relayer queue is enabled.
    """

    db_count = await repository_async.count_commitments(session, market_db_id)
    rpc_url = settings.rpc_url
    if not rpc_url:
        return db_count
    web3 = get_async_web3(str(rpc_url))
    # Prefer on-chain view when available, but tolerate lag when the relayer queue is enabled.
    try:
        contract = web3.eth.contract(address=to_checksum(market_address), abi=REVEAL_MARKET_ABI)
        onchain_next = int(await contract.functions.nextTicketId().call())
        if onchain_next != db_count and not settings.relayer_queue_enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"ticket_counter_desync:onchain={onchain_next},db={db_count}",
            )
        if onchain_next != db_count and settings.relayer_queue_enabled:
            direction = "onchain_ahead" if onchain_next > db_count else "db_ahead"
            resolved = max(onchain_next, db_count)
            log_event(
                logger,
                logging.WARNING,
                event="ticket_counter.desync_tolerated",
                message="On-chain ticket counter mismatch; continuing because relayer queue is enabled",
                onchain=onchain_next,
                db=db_count,
                direction=direction,
                resolved_next=resolved,
                market_address=market_address,
            )
        return onchain_next if onchain_next == db_count else max(onchain_next, db_count)
    except HTTPException:
        raise
    except Exception as exc:
        if settings.relayer_queue_enabled:
            log_event(
                logger,
                logging.WARNING,
                event="ticket_counter.rpc_failed",
                message="RPC unavailable; using DB ticket count because relayer queue is enabled",
                error=str(exc),
                db=db_count,
                market_address=market_address,
            )
            return db_count
        # Fall back to log scanning.
        try:
            logs = await web3.eth.get_logs(
                {
                    "fromBlock": 0,
                    "toBlock": "latest",
                    "address": Web3.to_checksum_address(market_address),
                    "topics": [COMMITTED_EVENT_SIG],
                }
            )
            onchain_count = len(logs)
        except Exception as log_exc:  # pragma: no cover - defensive network/log fetch
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"log_scan_failed:{log_exc}"
            ) from log_exc
        if onchain_count != db_count and not settings.relayer_queue_enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"ticket_counter_desync:onchain={onchain_count},db={db_count}",
            ) from None
        if onchain_count != db_count and settings.relayer_queue_enabled:
            direction = "onchain_ahead" if onchain_count > db_count else "db_ahead"
            resolved = max(onchain_count, db_count)
            log_event(
                logger,
                logging.WARNING,
                event="ticket_counter.desync_tolerated_logs",
                message="Log scan ticket counter mismatch; continuing because relayer queue is enabled",
                onchain=onchain_count,
                db=db_count,
                direction=direction,
                resolved_next=resolved,
                market_address=market_address,
            )
        return onchain_count if onchain_count == db_count else max(onchain_count, db_count)


async def _reserve_ticket_id(market_address: str, tentative_next: int) -> int:
    """Reserve a ticket id using Redis to avoid duplicate leaf indices under concurrency."""

    cache = await get_cache_client()
    if cache is None:
        return tentative_next
    key = f"ticket_counter:{market_address.lower()}"
    try:
        base = int(tentative_next) - 1
        reserved_raw = await cast(Awaitable[Any], cache.eval(_RESERVE_TICKET_LUA, 1, key, base))  # type: ignore[arg-type]
        reserved = int(reserved_raw)
        if reserved < tentative_next:
            log_event(
                logger,
                logging.WARNING,
                event="ticket_counter.reservation_lower_than_chain",
                message="Redis counter lagged on-chain nextTicketId",
                reserved=reserved,
                tentative=tentative_next,
                market_address=market_address,
            )
            await cache.set(key, str(tentative_next))
            return tentative_next
        return reserved
    except Exception as exc:  # pragma: no cover - best-effort guard
        log_event(
            logger,
            logging.DEBUG,
            event="ticket_counter.reserve_failed",
            message="failed to reserve ticket id; falling back to tentative value",
            market_address=market_address,
            error=str(exc),
        )
        return tentative_next


async def _maybe_create_market_onchain(session: AsyncSession, market_obj) -> tuple[str, int]:
    """Create a market via the factory when no address is stored."""

    if not settings.factory_address:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="factory_missing")
    if not settings.verifier_address:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="verifier_missing")
    if not settings.authorization_signer:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="authorization_signer_missing")
    if not settings.oracle_address:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="oracle_missing")
    raw_key = settings.wallet_private_key
    if raw_key is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="wallet_private_key_missing")
    raw_key_value = raw_key.get_secret_value() if hasattr(raw_key, "get_secret_value") else str(raw_key)
    if _is_placeholder_private_key(raw_key_value):
        log_event(
            logger,
            logging.WARNING,
            event="trade.market_create.placeholder_key",
            message="wallet private key is placeholder; skipping auto-create",
            market_id=getattr(market_obj, "event_id", None),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "wallet_private_key_invalid", "message": "RM_WALLET_PRIVATE_KEY is placeholder/zero"},
        )
    rpc_url = settings.rpc_url
    if not rpc_url:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="rpc_url_missing")
    # Ensure the circuit hash is a full 32-byte hex string so contract calls do not explode.
    circuit_hash = settings.circuit_hash
    if not isinstance(circuit_hash, str) or len(circuit_hash) != 66 or not circuit_hash.startswith("0x"):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="circuit_hash_invalid")
    try:
        account = load_account(raw_key_value)
        web3 = get_async_web3(str(rpc_url))
        factory = web3.eth.contract(address=to_checksum(settings.factory_address), abi=MARKET_FACTORY_ABI)
        commit_deadline = int(time.time()) + int(settings.market_commit_lead_seconds)
        params = (
            to_checksum(settings.oracle_address),
            to_checksum(settings.verifier_address),
            settings.circuit_hash,
            commit_deadline,
            int(settings.ticket_size_wei),
            int(settings.market_max_commitments),
            to_checksum(settings.authorization_signer),
            int(settings.market_protocol_liability_cap_wei),
        )
        try:
            nonce = await web3.eth.get_transaction_count(account.address, block_identifier="pending")
            chain_id = await web3.eth.chain_id
            tx = await factory.functions.createMarket(params).build_transaction(
                {"from": account.address, "nonce": nonce, "chainId": chain_id, "gas": 1_200_000}
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"market_create_failed:{exc}",
            ) from exc
    except HTTPException:
        raise
    except OnChainConfigurationError as exc:
        log_event(
            logger,
            logging.ERROR,
            event="trade.market_create.config_error",
            message="auto-create failed (config)",
            market_id=getattr(market_obj, "event_id", None),
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "market_create_config_error", "message": str(exc)},
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        log_event(
            logger,
            logging.ERROR,
            event="trade.market_create.init_failed",
            message="auto-create failed during setup",
            market_id=getattr(market_obj, "event_id", None),
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "market_create_failed", "message": str(exc)},
        ) from exc
    # Fill gas price if not set
    if "gasPrice" not in tx and "maxFeePerGas" not in tx:
        gas_price = await web3.eth.gas_price
        tx["gasPrice"] = gas_price
    signed = account.sign_transaction(tx)
    raw_tx = _raw_tx_bytes(signed)
    tx_hash = Web3.keccak(raw_tx)
    try:
        tx_hash = await web3.eth.send_raw_transaction(raw_tx)
        receipt = await web3.eth.wait_for_transaction_receipt(tx_hash)
    except Web3RPCError as exc:
        message = str(exc)
        lowered = message.lower()
        if "already known" in lowered:
            log_event(
                logger,
                logging.WARNING,
                event="trade.market_create.already_known",
                message="createMarket tx already in mempool; waiting for receipt",
                market_id=getattr(market_obj, "event_id", None),
                tx_hash=tx_hash.hex(),
            )
            try:
                receipt = await web3.eth.wait_for_transaction_receipt(tx_hash)
            except Exception as wait_exc:  # pragma: no cover - defensive fallback
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"error": "market_create_pending", "message": str(wait_exc)},
                ) from wait_exc
        elif "nonce too low" in lowered:
            try:
                fresh_nonce = await web3.eth.get_transaction_count(account.address, block_identifier="pending")
                tx["nonce"] = fresh_nonce
                signed_retry = account.sign_transaction(tx)
                raw_retry = _raw_tx_bytes(signed_retry)
                tx_hash = await web3.eth.send_raw_transaction(raw_retry)
                receipt = await web3.eth.wait_for_transaction_receipt(tx_hash)
            except Exception as retry_exc:  # pragma: no cover - defensive fallback
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"error": "market_create_failed", "message": str(retry_exc)},
                ) from retry_exc
        else:
            log_event(
                logger,
                logging.ERROR,
                event="trade.market_create.rpc_error",
                message="auto-create failed via RPC",
                market_id=getattr(market_obj, "event_id", None),
                error=message,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "market_create_failed", "message": message},
            ) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        log_event(
            logger,
            logging.ERROR,
            event="trade.market_create.failed",
            message="auto-create failed",
            market_id=getattr(market_obj, "event_id", None),
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "market_create_failed", "message": str(exc)},
        ) from exc
    logs = factory.events.MarketCreated().process_receipt(receipt)
    if not logs:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="market_create_failed")
    market_address = logs[0]["args"]["market"]
    market_id = logs[0]["args"]["marketId"]
    # Persist address + onchain id.
    market_obj.market_address = market_address
    market_obj.onchain_market_id = int(market_id)
    market_obj.factory = settings.factory_address
    session.add(market_obj)
    await session.flush()
    log_event(
        logger,
        logging.INFO,
        event="trade.market_created",
        message="Auto-created market on first trade",
        tx_hash=tx_hash.hex(),
        market_address=market_address,
        market_id=int(market_id),
    )
    return market_address, int(market_id)


def _compute_merkle_path(leaves: list[bytes], target_index: int) -> list[str]:
    """Compute a fixed-depth Poseidon Merkle path for a given index."""

    if target_index < 0 or target_index >= len(leaves):
        raise ValueError("invalid target index")
    siblings = build_merkle_path(leaves, target_index)
    return ["0x" + sibling.hex() for sibling in siblings]


def _batch_root_for_ticket(settlement: models.Settlement, ticket_id: int) -> str | None:
    batch_roots = _parse_json_list(getattr(settlement, "batch_roots", None))
    if batch_roots:
        batch_index = int(ticket_id) // BATCH_SIZE
        if batch_index < len(batch_roots):
            return str(batch_roots[batch_index])
    if _is_empty_hex(getattr(settlement, "merkle_root", None)):
        return None
    return settlement.merkle_root


def _has_valid_roots(settlement: models.Settlement | None) -> bool:
    if settlement is None:
        return False
    batch_roots = _parse_json_list(getattr(settlement, "batch_roots", None))
    if batch_roots:
        return True
    return not _is_empty_hex(getattr(settlement, "merkle_root", None))


async def _build_merkle_proof_for_commitment(
    session: AsyncSession, market: models.Market, settlement: models.Settlement, commitment: models.Commitment
) -> list[str]:
    """Return or compute the Merkle proof for a commitment, persisting it if missing."""

    batch_roots = _parse_json_list(getattr(settlement, "batch_roots", None))
    batch_counts = _parse_json_list(getattr(settlement, "batch_counts", None))

    if not batch_roots and settlement.merkle_root and not _is_empty_hex(settlement.merkle_root):
        batch_roots = [settlement.merkle_root]
        batch_counts = [settlement.commitments_count]
    if not batch_roots:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="merkle_root_missing")
    if commitment.leaf_index is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ticket_index_missing")
    if len(batch_counts) != len(batch_roots):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="batch_count_mismatch")

    batch_index = int(commitment.leaf_index) // BATCH_SIZE
    if batch_index >= len(batch_roots):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="batch_index_out_of_range")
    expected_root = str(batch_roots[batch_index])
    if not expected_root:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="batch_root_missing")
    batch_count_raw = batch_counts[batch_index] if batch_counts else settlement.commitments_count
    try:
        batch_count = int(batch_count_raw or 0)
    except Exception:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="batch_count_invalid") from None
    if batch_count <= 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="batch_count_invalid")
    index_in_batch = int(commitment.leaf_index) % BATCH_SIZE
    if index_in_batch >= batch_count:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="batch_index_invalid")

    path_rows = (
        await session.execute(
            select(models.CommitmentMerklePath)
            .where(models.CommitmentMerklePath.commitment_id == commitment.id)
            .order_by(models.CommitmentMerklePath.level.asc())
        )
    ).scalars()
    merkle_proof = [row.sibling_hash for row in path_rows]

    if not merkle_proof:
        commitments = await repository_async.list_commitments_by_market(session, market.id)
        if not commitments:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no_commitments_recorded")
        leaves: list[bytes | None] = [None] * batch_count
        for idx, c in enumerate(commitments):
            leaf_hex = c.leaf or c.ticket_hash
            try:
                leaf_index = c.leaf_index if c.leaf_index is not None else idx
                batch_id = int(leaf_index) // BATCH_SIZE
                if batch_id != batch_index:
                    continue
                rel_index = int(leaf_index) % BATCH_SIZE
                if rel_index >= batch_count:
                    continue
                leaves[rel_index] = bytes.fromhex(_strip_hex(leaf_hex))
            except Exception as exc:  # pragma: no cover - data integrity guard
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"invalid_leaf:{exc}"
                ) from exc
        if any(leaf is None for leaf in leaves):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="batch_leaf_missing")
        batch_leaves = cast(list[bytes], leaves)
        try:
            computed_root, paths = build_merkle_root_and_paths(batch_leaves)
            expected_root_bytes = bytes.fromhex(_strip_hex(expected_root))
            if computed_root != expected_root_bytes:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="merkle_root_mismatch")
            merkle_proof = ["0x" + sibling.hex() for sibling in paths[index_in_batch]]
        except HTTPException:
            raise
        except Exception as exc:  # pragma: no cover - integrity guard
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"merkle_compute_failed:{exc}"
            ) from exc
        await repository_async.replace_merkle_path(session, commitment.id, merkle_proof)
        await session.flush()

    if not merkle_proof:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="merkle_path_missing")

    try:
        leaf_hex = commitment.leaf or commitment.ticket_hash
        if not leaf_hex:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="leaf_missing")
        computed = bytes.fromhex(_strip_hex(leaf_hex))
        idx = index_in_batch
        for sibling_hex in merkle_proof:
            sibling_bytes = bytes.fromhex(_strip_hex(sibling_hex))
            if idx & 1:
                computed = int_to_bytes32(
                    poseidon_t3(int.from_bytes(sibling_bytes, "big"), int.from_bytes(computed, "big"))
                )
            else:
                computed = int_to_bytes32(
                    poseidon_t3(int.from_bytes(computed, "big"), int.from_bytes(sibling_bytes, "big"))
                )
            idx //= 2
        if computed.hex().lower() != _strip_hex(expected_root).lower():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="merkle_root_mismatch")
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"merkle_verify_failed:{exc}"
        ) from exc

    return merkle_proof


async def _ensure_market(
    session: AsyncSession, market_id: str, expected_address: str | None
) -> tuple[int, str, int | None]:
    market = await repository_async.get_market_by_event_id(session, market_id)
    if market is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "market_address_missing", "message": "Market address unavailable"},
        )
    if market.market_address and expected_address and market.market_address.lower() != expected_address.lower():
        log_event(
            logger,
            logging.WARNING,
            event="trade.market_address_mismatch",
            message="Market address mismatch between quote and DB",
            market_id=market_id,
            quote_address=expected_address,
            db_address=market.market_address,
        )
    resolved_address = market.market_address or expected_address
    if not resolved_address:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "market_address_missing", "message": "Market address unavailable"},
        )
    resolved_onchain_id = market.onchain_market_id
    if resolved_onchain_id is None and settings.rpc_url:
        try:
            web3 = get_async_web3(str(settings.rpc_url))
            contract = web3.eth.contract(address=to_checksum(resolved_address), abi=REVEAL_MARKET_ABI)
            resolved_onchain_id = int(await contract.functions.marketId().call())
            market.onchain_market_id = resolved_onchain_id
            session.add(market)
            await session.flush()
        except Exception:
            resolved_onchain_id = market.onchain_market_id
    return market.id, resolved_address, resolved_onchain_id


async def _ensure_market_or_create(
    session: AsyncSession, market_id: str, expected_address: str | None
) -> tuple[int, str, int | None]:
    market = await repository_async.get_market_by_event_id(session, market_id)
    if market is None:
        if not settings.oracle_address:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="oracle_missing")
        market = models.Market(
            event_id=market_id,
            title=f"Market {market_id}",
            oracle=settings.oracle_address,
            status=models.MarketStatusEnum.COMMIT.value,
        )
        session.add(market)
        await session.flush()

    if expected_address:
        if market.market_address and market.market_address.lower() != expected_address.lower():
            log_event(
                logger,
                logging.WARNING,
                event="trade.market_address_mismatch",
                message="Market address mismatch between quote and DB",
                market_id=market_id,
                quote_address=expected_address,
                db_address=market.market_address,
            )
        resolved_address = expected_address
    elif market.market_address:
        resolved_address = market.market_address
    else:
        now = datetime.now(tz=UTC)
        deploy_ttl_seconds = 180
        cache = await get_cache_client()
        lock_key = f"market_deploy:{market_id}"
        if cache is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "market_deploy_lock_unavailable", "message": "Deploy lock unavailable"},
            )
        lock_acquired = False
        try:
            lock_acquired = bool(await cache.set(lock_key, now.isoformat(), ex=deploy_ttl_seconds, nx=True))
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                event="trade.market_create.lock_error",
                message="failed to acquire market deployment lock",
                market_id=market_id,
                error=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "market_deploy_lock_unavailable", "message": "Deploy lock unavailable"},
            ) from exc
        # If another deploy is in-flight, wait for it to finish instead of erroring immediately.
        deadline = time.monotonic() + deploy_ttl_seconds
        while not lock_acquired:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"error": "market_deploying", "message": "Market deployment in progress"},
                )
            await asyncio.sleep(min(1.0, remaining))
            try:
                await session.refresh(market)
            except Exception:
                log_event(
                    logger,
                    logging.DEBUG,
                    event="trade.market_create.lock_refresh_failed",
                    message="failed to refresh market while waiting for deploy",
                    market_id=market_id,
                )
            if market.market_address:
                resolved_address = market.market_address
                return market.id, resolved_address, market.onchain_market_id
            try:
                lock_acquired = bool(
                    await cache.set(lock_key, datetime.now(tz=UTC).isoformat(), ex=deploy_ttl_seconds, nx=True)
                )
            except Exception as exc:
                log_event(
                    logger,
                    logging.ERROR,
                    event="trade.market_create.lock_error",
                    message="failed to acquire market deployment lock",
                    market_id=market_id,
                    error=str(exc),
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"error": "market_deploy_lock_unavailable", "message": "Deploy lock unavailable"},
                ) from exc
        try:
            try:
                await session.refresh(market)
            except Exception:
                log_event(
                    logger,
                    logging.DEBUG,
                    event="trade.market_create.lock_refresh_failed",
                    message="failed to refresh market after acquiring lock",
                    market_id=market_id,
                )
            if market.market_address:
                resolved_address = market.market_address
                return market.id, resolved_address, market.onchain_market_id
            resolved_address, onchain_id = await _maybe_create_market_onchain(session, market)
            return market.id, resolved_address, onchain_id
        finally:
            if cache is not None and lock_acquired:
                try:
                    await cache.delete(lock_key)
                except Exception:
                    log_event(
                        logger,
                        logging.DEBUG,
                        event="trade.market_create.lock_cleanup_failed",
                        message="failed to clear market deployment lock",
                        market_id=market_id,
                    )

    resolved_onchain_id = market.onchain_market_id
    if resolved_onchain_id is None and settings.rpc_url:
        try:
            web3 = get_async_web3(str(settings.rpc_url))
            contract = web3.eth.contract(address=to_checksum(resolved_address), abi=REVEAL_MARKET_ABI)
            resolved_onchain_id = int(await contract.functions.marketId().call())
            market.onchain_market_id = resolved_onchain_id
            session.add(market)
            await session.flush()
        except Exception:
            resolved_onchain_id = market.onchain_market_id
    return market.id, resolved_address, resolved_onchain_id


async def _maybe_backfill_settlement(session: AsyncSession, market: models.Market) -> models.Settlement | None:
    """Populate settlement snapshot from on-chain state when DB rows are missing or incomplete."""

    if not settings.rpc_url or not market.market_address:
        return None
    try:
        web3 = get_async_web3(str(settings.rpc_url))
        contract = web3.eth.contract(address=to_checksum(market.market_address), abi=REVEAL_MARKET_ABI)
        (
            commitments_root,
            next_ticket_id,
            phase_value,
            _deadline,
            winning_outcome_id,
        ) = await contract.functions.marketState().call()  # type: ignore[assignment]
        settled = int(phase_value) == 2  # Phase.Settled
        total_escrow = await contract.functions.totalEscrow().call()
        total_liability = await contract.functions.totalLiability().call()
        pool_total_yes = await contract.functions.poolTotalYes().call()
        pool_total_no = await contract.functions.poolTotalNo().call()
        rake_bps = await contract.functions.rakeBps().call()
        circuit_hash = await contract.functions.circuitHash().call()
        winning_value = int(winning_outcome_id) if settled else None
        commitments_root_hex = _normalize_bytes32(commitments_root)
        circuit_hash_hex = _normalize_bytes32(circuit_hash)
        batch_roots: list[str] = []
        batch_counts: list[int] = []
        try:
            if int(next_ticket_id or 0) > 0:
                total_batches = (int(next_ticket_id) + BATCH_SIZE - 1) // BATCH_SIZE
                for index in range(total_batches):
                    root_value = await contract.functions.batchRoots(index).call()
                    count_value = await contract.functions.batchCounts(index).call()
                    batch_roots.append(_normalize_bytes32(root_value) or str(root_value))
                    batch_counts.append(int(count_value))
        except Exception:
            batch_roots = []
            batch_counts = []
        settlement_data = {
            "merkle_root": commitments_root_hex or commitments_root,
            "commitments_count": int(next_ticket_id),
            "pool_total_yes": int(pool_total_yes),
            "pool_total_no": int(pool_total_no),
            "total_escrow": int(total_escrow),
            "total_liability": int(total_liability),
            "rake_bps": int(rake_bps),
            "winning_outcome_id": winning_value,
            "circuit_hash": circuit_hash_hex or circuit_hash,
        }
        if batch_roots:
            settlement_data["batch_roots"] = batch_roots
            settlement_data["batch_counts"] = batch_counts
        await repository_async.upsert_settlement_snapshot(session, market.id, settlement_data)
        if settled and settlement_data["winning_outcome_id"] is not None and not market.resolved_at:
            market.resolved_at = datetime.now(tz=UTC)
            session.add(market)
        await session.flush()
    except Exception as exc:  # pragma: no cover - best-effort backfill
        log_event(
            logger,
            logging.DEBUG,
            event="settlement.backfill_failed",
            message="failed to backfill settlement from chain",
            market_id=getattr(market, "event_id", None),
            error=str(exc),
        )
        return None

    result = (
        await session.execute(select(models.Settlement).where(models.Settlement.market_id == market.id))
    ).scalar_one_or_none()
    return result


def _verify_wallet_signature(wallet: str, signature: str) -> None:
    """Verify that the signature was produced by the wallet for the claim-bundles scope."""

    try:
        recovered = Account.recover_message(
            encode_defunct(text=f"claim-bundles:{wallet.lower()}"),
            signature=signature,
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid_signature:{exc}") from exc
    if recovered.lower() != wallet.lower():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="wallet_signature_mismatch")


@router.post("/trade/commit", response_model=schemas.TradeCommitResponse, tags=["trade"])
async def trade_commit(
    payload: schemas.TradeCommitRequest,
    session: AsyncSession = Depends(get_session),
) -> schemas.TradeCommitResponse:
    """Consume a pricing quote, build CommitAuth, and forward to the relayer."""

    db_quote, quote = await _get_quote(session, payload.quote_id)
    # Fail fast on config/quote errors before touching on-chain state.
    now = datetime.now(tz=UTC)
    auth_signer_key = _require_auth_signer()
    if not settings.relayer_base_url:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="relayer_unconfigured")
    if quote.expires_at and quote.expires_at <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="quote_expired")
    if quote.outcome_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="outcome_required")
    chain_id = settings.pricing_chain_id
    if chain_id is None or quote.chain_id != chain_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="quote_chain_mismatch")
    ticket_size_wei = int(settings.ticket_size_wei)
    if int(quote.stake_wei) != ticket_size_wei:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"stake_mismatch_expected_{ticket_size_wei}",
        )
    # Check relayer escrow balance if available.
    escrow_balance = await _fetch_escrow_balance(quote.wallet_address or "")
    market_db_id, market_address, market_onchain_id = await _ensure_market_or_create(
        session, quote.market_id or "", quote.market_address
    )
    if not market_address:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "market_address_missing", "message": "Market address unavailable"},
        )
    if not quote.market_address or quote.market_address.lower() != market_address.lower() or not quote.signature:
        quote.market_address = market_address
        db_quote.market_address = market_address
        quote = _sign_quote_for_commit(quote)
        db_quote.payload = quote.model_dump(mode="json")
        await session.flush()
    outcome_id = int(cast(int, quote.outcome_id))
    if settings.relayer_escrow_address and escrow_balance is not None and int(escrow_balance) < int(quote.stake_wei):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="insufficient_escrow_balance")
    market_record = await repository_async.get_market_by_event_id(session, quote.market_id or "")
    if market_record and (
        market_record.status in {models.MarketStatusEnum.SETTLED.value, models.MarketStatusEnum.CANCELLED.value}
        or market_record.resolved_at is not None
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="market_settled")
    if market_record:
        pricing_routes._assert_commits_allowed(market_record, now, session)

    onchain_rake_bps = await _sync_market_factory_params(
        session,
        market_record=market_record,
        market_address=market_address,
        market_onchain_id=market_onchain_id,
        auth_signer_key=auth_signer_key,
    )

    # Validate and consume the quote using the existing submit logic (signature + drift checks).
    await pricing_routes.pricing_submit(
        schemas.PricingSubmitRequest(quote=quote, max_fx_diff_percent=payload.max_fx_diff_percent),
        session=session,
    )
    stake_zen = float(quote.stake_zen)
    entry_fx = float(quote.zen_usd)
    payout_zen = None
    try:
        payout_zen = float(quote.payout_zen)
    except Exception:
        payout_zen = None
    potential = payout_zen if payout_zen is not None else None
    rake_zen_value = None
    protocol_topup = None
    try:
        rake_zen_value = float(quote.rake_zen)
    except Exception:
        rake_zen_value = None
    if payout_zen is not None and rake_zen_value is not None:
        net_zen = max(0.0, stake_zen - rake_zen_value)
        protocol_topup = max(0.0, payout_zen - net_zen)

    # Derive next ticket id by counting on-chain Committed events (fallback to DB count).
    ticket_id = await _next_ticket_id_onchain(market_address, market_db_id, session)
    reserved_ticket_id = await _reserve_ticket_id(market_address, ticket_id)
    if reserved_ticket_id != ticket_id:
        log_event(
            logger,
            logging.DEBUG,
            event="ticket_counter.reserved_adjusted",
            message="ticket id adjusted via redis reservation",
            market_address=market_address,
            tentative=ticket_id,
            reserved=reserved_ticket_id,
        )
    ticket_id = reserved_ticket_id
    salt_bytes = secrets.token_bytes(32)
    salt_hex = "0x" + salt_bytes.hex()
    if not quote.wallet_address:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="wallet_required")
    user_address = Web3.to_checksum_address(str(quote.wallet_address))
    rake_bps = onchain_rake_bps
    if rake_bps is None and market_record and market_record.rake_bps is not None:
        rake_bps = int(market_record.rake_bps)
    if rake_bps is None and settings.rake_percent is not None:
        rake_bps = int(round(float(settings.rake_percent) * 10_000))
    rake_bps = rake_bps or 0
    rake_wei = (ticket_size_wei * rake_bps) // 10_000
    net_amount_wei = ticket_size_wei - rake_wei
    payout_wei = _zen_to_wei(payout_zen) if payout_zen is not None else net_amount_wei
    protocol_topup_wei = max(0, payout_wei - net_amount_wei)
    await _assert_protocol_pool_headroom(market_onchain_id, market_address, protocol_topup_wei)

    leaf_value = compute_leaf(ticket_id, outcome_id, net_amount_wei, payout_wei, user_address, salt_hex)
    commitment = int_to_hex32(leaf_value)

    nonce = secrets.randbelow(2**256 - 1)
    expiry = int(time.time()) + int(settings.commit_nonce_ttl_seconds)
    auth_digest = Web3.solidity_keccak(
        ["address", "uint256", "bytes32", "address", "uint256", "uint256", "uint256", "uint256"],
        [
            Web3.to_checksum_address(market_address),
            int(market_onchain_id or 0),
            bytes.fromhex(_strip_hex(commitment)),
            user_address,
            nonce,
            expiry,
            ticket_size_wei,
            int(chain_id),
        ],
    )
    signed = Account.sign_message(encode_defunct(hexstr=auth_digest.hex()), auth_signer_key)

    relayer_payload = {
        "user": user_address,
        "market": market_address,
        "commitment": commitment,
        "nonce": nonce,
        "expiry": expiry,
        "signature": _ensure_0x(signed.signature.hex()),
        "ticket_value_wei": ticket_size_wei,
        "amount_wei": net_amount_wei,
        "payout_wei": payout_wei,
        "chain_id": chain_id,
        "event_id": quote.market_id or market_onchain_id,
        "market_id": quote.market_id,
        "outcome_id": outcome_id,
        "salt": salt_hex,
        "ticket_id": ticket_id,
        "merkle_path": [],
    }
    relayer_status = None
    relayer_job = None
    commit_url = _relayer_url("commit")
    try:
        relayer_result = await _call_relayer(commit_url, relayer_payload)
    except HTTPException as exc:
        if settings.relayer_queue_enabled:
            relayer_job = await _enqueue_relayer_job("commit", commit_url, relayer_payload)
            relayer_status = "queued"
            relayer_result = {}
        else:
            raise exc

    tx_hash = _extract_tx_hash(relayer_result)
    relayer_status = relayer_status or relayer_result.get("status") or relayer_result.get("state")
    if relayer_status is not None:
        relayer_status = str(relayer_status)
    relayer_job = relayer_job or _extract_job_id(relayer_result)
    if relayer_job is not None:
        relayer_job = str(relayer_job)
    # When the relayer only returns a job id, stash it so /trade/status can later swap in the real tx hash.
    if tx_hash is None and relayer_job is not None:
        tx_hash = relayer_job
    tx_hash = _normalize_tx_hash(tx_hash) or tx_hash

    # Persist commitment snapshot.
    await repository_async.record_commitments(
        session,
        market_db_id,
        [
            {
                "ticketHash": commitment,
                "leaf": commitment,
                "user": quote.wallet_address,
                "outcomeId": quote.outcome_id,
                "amount": net_amount_wei,
                "payout": payout_wei,
                "salt": salt_hex,
                "merkleIndex": ticket_id,
                "merklePath": [],
                "txHash": tx_hash,
            }
        ],
        tx_hash=str(tx_hash) if tx_hash else None,
    )
    await session.flush()

    return schemas.TradeCommitResponse(
        tx_hash=str(tx_hash) if tx_hash else "",
        quote_id=payload.quote_id,
        market_id=quote.market_id or "",
        outcome_id=outcome_id,
        stake_zen=stake_zen,
        entry_fx=entry_fx,
        potential_payout_zen=potential,
        protocol_topup_zen=protocol_topup,
        rake_zen=rake_zen_value,
        status="committed",
        ticket_id=ticket_id,
        salt=salt_hex,
        escrow_balance_wei=int(escrow_balance) if escrow_balance is not None else None,
        relayer_status=relayer_status,
        relayer_job_id=relayer_job,
    )


@router.get("/positions", response_model=schemas.PositionsResponse, tags=["trade"])
async def list_positions(wallet: str, session: AsyncSession = Depends(get_session)) -> schemas.PositionsResponse:
    """Return committed positions for a wallet along with escrow balance."""

    if not wallet:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="wallet_required")
    rows = await repository_async.list_commitments_with_settlement(session, wallet)
    await _sync_claimed_commitments(session, rows)
    claim_deadline_candidates: set[str] = set()
    for commitment, market, settlement in rows:
        if commitment.claimed_at is not None:
            continue
        if not market.market_address or commitment.leaf_index is None:
            continue
        if settlement is None or settlement.winning_outcome_id is None:
            continue
        if settlement.winning_outcome_id != commitment.outcome_id:
            continue
        if not _has_valid_roots(settlement):
            continue
        claim_deadline_candidates.add(market.market_address)
    claim_deadlines = await _fetch_claim_deadlines(list(claim_deadline_candidates))
    now_ts = int(time.time())
    positions: list[schemas.PositionRecord] = []
    for commitment, market, settlement in rows:
        tx_hash_value = getattr(commitment, "tx_hash", None)
        if tx_hash_value and not _is_hex_tx(tx_hash_value):
            resolved_tx = await _resolve_job_tx_hash(session, str(tx_hash_value))
            if resolved_tx:
                tx_hash_value = resolved_tx
        if tx_hash_value and not _is_hex_tx(tx_hash_value):
            tx_hash_value = None
        stake_wei = int(commitment.amount_wei)
        stake_zen = stake_wei / 1e18
        claimed = commitment.claimed_at is not None
        claimable = False
        status = "committed"
        # Surface market status transitions for UI (committed/locked/settled/cancelled/pending).
        if getattr(market, "status", None) == models.MarketStatusEnum.LOCKED.value:
            status = "locked"
        if getattr(market, "status", None) == models.MarketStatusEnum.CANCELLED.value:
            status = "cancelled"
        if settlement and settlement.winning_outcome_id is not None:
            status = "settled"
            if settlement.winning_outcome_id == commitment.outcome_id:
                claimable = True
        if claimable and market.market_address:
            claim_deadline = claim_deadlines.get(market.market_address)
            if claim_deadline and now_ts > int(claim_deadline):
                claimable = False
        if market.resolved_at:
            status = "settled"
        if (
            getattr(market, "resolution_status", None)
            and market.resolution_status != models.ResolutionStatusEnum.FINAL.value
        ):
            status = "pending_resolution"
        if claimed:
            status = "claimed"
            claimable = False
        positions.append(
            schemas.PositionRecord(
                market_id=market.event_id,
                market_title=market.title,
                outcome_id=commitment.outcome_id,
                stake_wei=stake_wei,
                stake_zen=stake_zen,
                tx_hash=tx_hash_value,
                quote_id=None,
                status=status,
                ticket_id=commitment.leaf_index,
                created_at=getattr(commitment, "created_at", None),
                claimed_at=getattr(commitment, "claimed_at", None),
                claimable=claimable,
                closes_at=getattr(market, "closes_at", None),
                resolved_at=getattr(market, "resolved_at", None),
                proof_request_id=settlement.proof_request_id if settlement else None,
                merkle_root=_batch_root_for_ticket(settlement, commitment.leaf_index)
                if settlement and commitment.leaf_index is not None
                else None,
                winning_outcome_id=settlement.winning_outcome_id if settlement else None,
                market_address=market.market_address,
                resolution_status=getattr(market, "resolution_status", None),
                resolution_reason=getattr(market, "resolution_reason", None),
                commits_blocked_at=getattr(market, "commits_blocked_at", None),
            )
        )
    escrow_balance = await _fetch_escrow_balance(wallet)
    return schemas.PositionsResponse(positions=positions, escrow_balance_wei=escrow_balance)


@router.get("/claim/bundles", response_model=schemas.ClaimBundlesResponse, tags=["trade"])
async def list_claim_bundles(
    wallet: str,
    wallet_signature: str | None = Header(default=None, alias="X-Wallet-Signature"),
    session: AsyncSession = Depends(get_session),
) -> schemas.ClaimBundlesResponse:
    """Return claim bundles for settled winning tickets belonging to a wallet."""

    if not wallet:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="wallet_required")
    if not wallet_signature:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="wallet_signature_required")
    _verify_wallet_signature(wallet, wallet_signature)
    rows = await repository_async.list_commitments_with_settlement(session, wallet)
    needs_refresh = False
    for _commitment, market, settlement in rows:
        if (
            getattr(market, "resolution_status", None) is not None
            and market.resolution_status != models.ResolutionStatusEnum.FINAL.value
        ):
            continue
        has_roots = _has_valid_roots(settlement)
        if settlement is None or not has_roots or settlement.winning_outcome_id is None:
            refreshed = await _maybe_backfill_settlement(session, market)
            if refreshed is not None:
                needs_refresh = True
    if needs_refresh:
        rows = await repository_async.list_commitments_with_settlement(session, wallet)
    await _sync_claimed_commitments(session, rows)
    claim_deadline_candidates: set[str] = set()
    for commitment, market, settlement in rows:
        if commitment.claimed_at is not None:
            continue
        if not market.market_address or commitment.leaf_index is None:
            continue
        if settlement is None or settlement.winning_outcome_id is None:
            continue
        if settlement.winning_outcome_id != commitment.outcome_id:
            continue
        if not _has_valid_roots(settlement):
            continue
        claim_deadline_candidates.add(market.market_address)
    claim_deadlines = await _fetch_claim_deadlines(list(claim_deadline_candidates))
    now_ts = int(time.time())
    bundles: list[schemas.ClaimBundle] = []
    for commitment, market, settlement in rows:
        if commitment.claimed_at is not None:
            continue
        if market.market_address:
            claim_deadline = claim_deadlines.get(market.market_address)
            if claim_deadline and now_ts > int(claim_deadline):
                continue
        if (
            settlement is None
            or settlement.winning_outcome_id is None
            or settlement.winning_outcome_id != commitment.outcome_id
        ):
            continue
        if commitment.leaf_index is None or not market.market_address:
            continue
        batch_root = _batch_root_for_ticket(settlement, commitment.leaf_index)
        if not batch_root:
            continue
        merkle_proof = await _build_merkle_proof_for_commitment(session, market, settlement, commitment)
        bundles.append(
            schemas.ClaimBundle(
                marketId=market.event_id,
                marketAddress=market.market_address,
                commitmentsRoot=batch_root,
                ticketId=commitment.leaf_index,
                outcomeId=commitment.outcome_id,
                amountWei=int(commitment.amount_wei),
                payoutWei=int(commitment.payout_wei),
                salt=commitment.salt,
                merkleProof=merkle_proof,
                leaf=commitment.leaf,
                user=commitment.user_address,
            )
        )
    return schemas.ClaimBundlesResponse(bundles=bundles)


@router.post("/trade/claim", response_model=schemas.TradeClaimResponse, tags=["trade"])
async def trade_claim(payload: schemas.TradeClaimRequest, session: AsyncSession = Depends(get_session)):
    """Initiate a claim via the relayer for a settled winning ticket."""

    market_identifier = payload.event_id or payload.market_id
    if not market_identifier:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="market_id_required")
    market = await repository_async.get_market_by_event_id(session, market_identifier)
    if market is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="market_not_found")
    if market.resolution_status and market.resolution_status != models.ResolutionStatusEnum.FINAL.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="market_not_final")
    if not market.market_address:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="market_address_missing")
    settlement = (
        await session.execute(select(models.Settlement).where(models.Settlement.market_id == market.id))
    ).scalar_one_or_none()
    has_roots = _has_valid_roots(settlement)
    if settlement is None or settlement.winning_outcome_id is None or not has_roots:
        settlement = await _maybe_backfill_settlement(session, market) or settlement
    if settlement is None or settlement.winning_outcome_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="market_not_settled")
    if market.resolution_status and market.resolution_status != models.ResolutionStatusEnum.FINAL.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="market_not_final")
    winning_outcome = settlement.winning_outcome_id
    has_roots = _has_valid_roots(settlement)
    if not has_roots:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="merkle_root_missing")
    commitment_with_path = await repository_async.get_commitment_with_path_for_wallet(
        session, market.id, payload.wallet_address, winning_outcome, payload.ticket_id
    )
    if commitment_with_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="commitment_not_found")
    commitment, path_rows = commitment_with_path
    if commitment.leaf_index is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ticket_index_missing")
    ticket_id = commitment.leaf_index
    merkle_proof = [row.sibling_hash for row in path_rows] if path_rows else []
    if not merkle_proof:
        merkle_proof = await _build_merkle_proof_for_commitment(session, market, settlement, commitment)
    batch_roots = _parse_json_list(getattr(settlement, "batch_roots", None))
    batch_counts = _parse_json_list(getattr(settlement, "batch_counts", None))
    if not batch_roots and settlement.merkle_root and not _is_empty_hex(settlement.merkle_root):
        batch_roots = [settlement.merkle_root]
        batch_counts = [settlement.commitments_count]
    if not settings.relayer_base_url:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="relayer_unconfigured")
    relayer_payload = {
        "user": payload.wallet_address,
        "market": market.market_address,
        "ticket_id": ticket_id,
        "outcome_id": winning_outcome,
        "amount": int(commitment.amount_wei),
        "payout": int(commitment.payout_wei),
        "salt": commitment.salt,
        "merkle_proof": merkle_proof,
        "merkle_root": settlement.merkle_root,
        "batch_roots": batch_roots,
        "batch_counts": batch_counts,
        "commitments_count": settlement.commitments_count,
        "pool_total_yes": settlement.pool_total_yes,
        "pool_total_no": settlement.pool_total_no,
        "total_escrow": settlement.total_escrow,
        "total_liability": settlement.total_liability,
        "rake_bps": settlement.rake_bps,
        "proof_request_id": settlement.proof_request_id,
    }
    headers = {}
    if settings.relayer_bearer_token:
        headers["Authorization"] = f"Bearer {settings.relayer_bearer_token}"
    relayer_job = None
    try:
        claim_url = _relayer_url("claim")
        result = await _call_relayer(claim_url, relayer_payload)
    except HTTPException as exc:
        if settings.relayer_queue_enabled:
            relayer_job = await _enqueue_relayer_job("claim", claim_url, relayer_payload)
            result = {}
        else:
            raise exc
    except Exception as exc:  # pragma: no cover - network errors
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    tx_hash = _extract_tx_hash(result) or _extract_job_id(result) or relayer_job or ""
    return schemas.TradeClaimResponse(
        tx_hash=str(tx_hash),
        market_id=market.event_id,
        ticket_id=ticket_id,
        outcome_id=winning_outcome,
        amount_wei=int(commitment.amount_wei),
        payout_wei=int(commitment.payout_wei),
        status="claimed",
    )


@router.post("/commitments/sync", response_model=schemas.CommitmentsSyncResponse, tags=["trade"])
async def sync_commitments(payload: schemas.CommitmentsSyncRequest, session: AsyncSession = Depends(get_session)):
    """Ingest commitments pushed by the relayer (for commits that bypassed the API)."""

    market_identifier = payload.event_id or payload.market_id
    if not market_identifier:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="market_id_required")
    market = await repository_async.get_market_by_event_id(session, market_identifier)
    if market is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="market_not_found")
    tickets = []
    for ticket in payload.tickets:
        tx_hash = getattr(ticket, "tx_hash", None)
        tickets.append(
            {
                "ticketHash": ticket.ticket_hash or ticket.leaf,
                "leaf": ticket.leaf or ticket.ticket_hash,
                "user": ticket.user,
                "outcomeId": ticket.outcome_id,
                "amount": ticket.amount_wei,
                "payout": ticket.payout_wei,
                "salt": ticket.salt,
                "merkleIndex": ticket.leaf_index,
                "merklePath": ticket.merkle_path or [],
                "txHash": tx_hash,
            }
        )
    recorded = await repository_async.record_commitments(session, market.id, tickets)
    return schemas.CommitmentsSyncResponse(recorded=recorded)


@router.post("/settlements/ingest", response_model=schemas.SettlementIngestResponse, tags=["trade"])
async def ingest_settlement(payload: schemas.SettlementIngestRequest, session: AsyncSession = Depends(get_session)):
    """Persist settlement snapshot from relayer/prover so claims can proceed."""

    market_identifier = payload.event_id or payload.market_id
    if not market_identifier:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="market_id_required")
    market = await repository_async.get_market_by_event_id(session, market_identifier)
    if market is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="market_not_found")
    settlement_data = {
        "merkle_root": payload.merkle_root,
        "commitments_count": payload.commitments_count,
        "batch_roots": payload.batch_roots,
        "batch_counts": payload.batch_counts,
        "pool_total_yes": payload.pool_total_yes,
        "pool_total_no": payload.pool_total_no,
        "total_escrow": payload.total_escrow,
        "total_liability": payload.total_liability,
        "rake_bps": payload.rake_bps,
        "winning_outcome_id": payload.winning_outcome_id,
        "proof_status": payload.proof_status or models.SettlementProofStatus.NONE.value,
        "proof_request_id": payload.proof_request_id,
        "proof_hash": payload.proof_hash,
        "circuit_hash": payload.circuit_hash,
    }
    await repository_async.upsert_settlement_snapshot(session, market.id, settlement_data)
    if payload.winning_outcome_id is not None and not market.resolved_at:
        market.resolved_at = datetime.now(tz=UTC)
        session.add(market)
    await session.flush()
    return schemas.SettlementIngestResponse(market_id=market.event_id, updated=True)


def _verify_relayer_secret(secret_header: str | None) -> None:
    if settings.relayer_webhook_secret:
        if secret_header != settings.relayer_webhook_secret:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_relayer_secret")


@router.post("/relayer/commitments", response_model=schemas.CommitmentsSyncResponse, tags=["trade"])
async def relayer_commitments(
    payload: schemas.CommitmentsSyncRequest,
    relayer_secret: str | None = Header(default=None, alias="X-Relayer-Secret"),
    session: AsyncSession = Depends(get_session),
):
    """Relayer-protected hook to push commitments."""

    _verify_relayer_secret(relayer_secret)
    return await sync_commitments(payload, session=session)


@router.post("/relayer/settlements", response_model=schemas.SettlementIngestResponse, tags=["trade"])
async def relayer_settlements(
    payload: schemas.SettlementIngestRequest,
    relayer_secret: str | None = Header(default=None, alias="X-Relayer-Secret"),
    session: AsyncSession = Depends(get_session),
):
    """Relayer/prover-protected hook to push settlement snapshots."""

    _verify_relayer_secret(relayer_secret)
    return await ingest_settlement(payload, session=session)


@router.get("/trade/status", response_model=schemas.TradeStatusResponse, tags=["trade"])
async def trade_status(
    tx_hash: str | None = None,
    job_id: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Return transaction status by hash or relayer job id (best-effort)."""

    if not tx_hash and not job_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tx_hash_or_job_id_required")
    resolved_tx = tx_hash
    job_id_value = job_id
    if resolved_tx and not _is_hex_tx(resolved_tx):
        # Treat non-hex payloads as relayer job ids.
        if not job_id_value:
            job_id_value = resolved_tx
        resolved_tx = None
    if resolved_tx:
        resolved_tx = _normalize_tx_hash(resolved_tx) or resolved_tx
    if resolved_tx and job_id_value:
        await _maybe_replace_job_tx_hash(session, job_id_value, resolved_tx)
    if not resolved_tx and job_id_value:
        cache = await get_cache_client()
        if cache is not None:
            cached = await cache.get(f"{settings.relayer_queue_key}:result:{job_id_value}")
            if cached:
                try:
                    cached_result = json.loads(cached)
                except Exception:
                    cached_result = {}
                cached_tx = _extract_tx_hash(cached_result)
                if cached_tx and _is_hex_tx(cached_tx):
                    resolved_tx = cached_tx
                    await _maybe_replace_job_tx_hash(session, job_id_value, resolved_tx)
                else:
                    status_str = cached_result.get("status") or "pending"
                    return schemas.TradeStatusResponse(tx_hash="", status=status_str)
        if not settings.relayer_base_url:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="relayer_unconfigured")
        status_url = _relayer_url("status")
        try:
            result = await _call_relayer(status_url, {"jobId": job_id_value})
        except HTTPException as exc:
            log_event(
                logger,
                logging.DEBUG,
                event="trade.status.relayer_error",
                message="relayer status lookup failed",
                job_id=job_id_value,
                error=str(exc.detail) if hasattr(exc, "detail") else str(exc),
            )
            return schemas.TradeStatusResponse(tx_hash="", status="unknown")
        resolved_tx = _extract_tx_hash(result)
        if not resolved_tx or not _is_hex_tx(resolved_tx):
            status_str = result.get("status") or result.get("state") or "unknown"
            return schemas.TradeStatusResponse(tx_hash="", status=status_str)
        # If the job id was stored on commitments, replace it with the resolved tx hash.
        await _maybe_replace_job_tx_hash(session, job_id_value, resolved_tx)
    if not resolved_tx:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tx_hash_not_found")
    if not _is_hex_tx(resolved_tx):
        return schemas.TradeStatusResponse(tx_hash="", status="unknown")
    if not settings.rpc_url:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="rpc_url_missing")
    try:
        web3 = get_async_web3(str(settings.rpc_url))
        receipt = await web3.eth.get_transaction_receipt(resolved_tx)
        status_flag = receipt.get("status", 0)
        status_str = "confirmed" if status_flag == 1 else "failed"
        return schemas.TradeStatusResponse(
            tx_hash=resolved_tx,
            status=status_str,
            block_number=receipt.get("blockNumber"),
            gas_used=receipt.get("gasUsed"),
            effective_gas_price=receipt.get("effectiveGasPrice"),
        )
    except Exception as exc:
        # Pending or not found
        detail = str(exc)
        if "not found" in detail.lower():
            return schemas.TradeStatusResponse(tx_hash=resolved_tx, status="pending")
        return schemas.TradeStatusResponse(tx_hash=resolved_tx, status="unknown")
