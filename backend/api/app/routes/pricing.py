"""Pricing and signed quote routes."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from secrets import token_hex
from threading import Lock
from typing import TypedDict, Unpack, cast

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct, encode_typed_data
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import SecretStr
from shared import models as shared_models
from shared.logging import get_request_id, log_event
from shared.onchain.client import load_account
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from web3 import Web3

from app import models, repository_async, schemas
from app.database import get_session
from app.metrics_registry import PRICING_COUNTER
from app.pricing import PricingEngine, _coerce_price, build_quote_audit_payload, fetch_fx_quote
from app.runtime import logger, settings
from app.services.cache_client import get_cache_client, get_http_client

router = APIRouter()

_STREAMER_TIMEOUT_SECONDS = 3.0
_PRESET_CFG: dict[str, object] | None = None
_PRESET_CFG_LOCK = asyncio.Lock()
_QUOTE_NONCE_FALLBACK: dict[str, datetime] = {}
_QUOTE_NONCE_FALLBACK_LOCK = asyncio.Lock()

_PREVIEW_RL_LIMIT = 30
_PREVIEW_RL_WINDOW = 60.0
_preview_rl_buckets: dict[str, list[float]] = {}
_preview_rl_lock = Lock()


def _check_preview_rate_limit(request: Request) -> None:
    """Enforce 30 req/min per IP on the preview endpoint."""
    client_host = request.client.host if request.client else "anonymous"
    now = time.time()
    with _preview_rl_lock:
        bucket = _preview_rl_buckets.get(client_host, [])
        bucket = [ts for ts in bucket if now - ts < _PREVIEW_RL_WINDOW]
        if len(bucket) >= _PREVIEW_RL_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="preview_rate_limit_exceeded",
                headers={"Retry-After": "60"},
            )
        bucket.append(now)
        _preview_rl_buckets[client_host] = bucket


class _PricingUnavailableFields(TypedDict, total=False):
    error: str
    fx_received_at: str | None


def _pricing_unavailable(
    reason: str, *, request_id: str | None, **fields: Unpack[_PricingUnavailableFields]
) -> HTTPException:
    log_event(
        logger,
        logging.WARNING,
        event="pricing.unavailable",
        message=reason,
        request_id=request_id,
        **fields,
    )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": "pricing_unavailable", "request_id": request_id},
    )


async def _get_cached_preset() -> dict[str, object]:
    """Load and cache env preset config to avoid repeated lookups per request."""

    from shared.env_presets import get_preset

    global _PRESET_CFG
    async with _PRESET_CFG_LOCK:
        if _PRESET_CFG is None:
            _PRESET_CFG = get_preset()
        return _PRESET_CFG


async def _fetch_streamer_price(stream_market_id: str, outcome_id: int) -> Decimal | None:
    """Fetch the latest streamer price for a market/outcome (display_price preferred)."""

    if not stream_market_id:
        return None
    preset_cfg = await _get_cached_preset()
    stream_base = str(preset_cfg.get("streamer_internal") or preset_cfg.get("streamer_public") or "")
    if not stream_base:
        return None
    base = stream_base.rstrip("/")
    url = f"{base}/data/clob/latest"
    params = {"market_id": stream_market_id, "outcome": str(outcome_id)}
    try:
        client = await get_http_client(_STREAMER_TIMEOUT_SECONDS)
        resp = await client.get(url, params=params)
        if resp.status_code != status.HTTP_200_OK:
            return None
        payload = resp.json() if resp.content else {}
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return None
        if data.get("fx_stale") is True:
            return None
        return _coerce_price(data.get("display_price") or data.get("price"))
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        log_event(
            logger,
            logging.WARNING,
            event="pricing.streamer_fetch_failed",
            message="failed to fetch streamer price",
            market_id=stream_market_id,
            outcome_id=outcome_id,
            error=str(exc),
        )
        return None


async def _fetch_db_price(session: AsyncSession, market_id: str, outcome_id: int) -> Decimal | None:
    market = await repository_async.get_market_by_event_id(session, market_id)
    if not market or not getattr(market, "id", None):
        return None
    stmt = select(shared_models.MarketOutcome.price).where(
        shared_models.MarketOutcome.market_id == market.id,
        shared_models.MarketOutcome.outcome_id == outcome_id,
    )
    price = (await session.execute(stmt)).scalar_one_or_none()
    return _coerce_price(price)


async def _resolve_outcome_price(session: AsyncSession, market_id: str, outcome_id: int) -> Decimal | None:
    market = await repository_async.get_market_by_event_id(session, market_id)
    stream_market_id = None
    if market is not None:
        stream_market_id = getattr(market, "condition_id", None) or None
    if stream_market_id is None:
        stream_market_id = market_id
    price = await _fetch_streamer_price(stream_market_id, outcome_id)
    if price is not None:
        return price
    return await _fetch_db_price(session, market_id, outcome_id)


def _strip_0x(value: str | None) -> str:
    """Remove 0x prefix from hex strings."""

    if not value:
        return ""
    return value[2:] if value.startswith("0x") else value


def _to_wei_amount(stake_zen: float | Decimal) -> int:
    """Scale a ZEN stake to wei with safe rounding."""

    quantized = (Decimal(str(stake_zen)) * Decimal("1e18")).to_integral_value(rounding=ROUND_DOWN)
    return int(quantized)


def _scale_fx_value(zen_usd: float | Decimal) -> int:
    """Scale FX price to 1e8 for the on-chain digest."""

    quantized = (Decimal(str(zen_usd)) * Decimal("1e8")).to_integral_value(rounding=ROUND_DOWN)
    return int(quantized)


def _assert_commits_allowed(
    market: shared_models.Market,
    now: datetime,
    session: AsyncSession | None = None,
) -> None:
    """Raise if the market should not accept new quotes/commits."""

    # Enforce a minimum 5-minute buffer before close; use configured cutoff if larger.
    cutoff_seconds = max(300, getattr(settings, "commit_cutoff_seconds", 0) or 0)
    resolution_status = getattr(market, "resolution_status", shared_models.ResolutionStatusEnum.FINAL.value)
    resolution_reason = getattr(market, "resolution_reason", None)
    blocked_at = getattr(market, "commits_blocked_at", None)

    def _normalize_ts(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)

    if resolution_status in {
        shared_models.ResolutionStatusEnum.PENDING.value,
        shared_models.ResolutionStatusEnum.DISPUTED.value,
    }:
        if blocked_at is None:
            market.commits_blocked_at = now
            blocked_at = market.commits_blocked_at
        blocked_at_ts = _normalize_ts(blocked_at)
        if session is not None:
            session.add(market)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "market_resolution_pending",
                "resolution_status": resolution_status,
                "resolution_reason": resolution_reason,
                "commits_blocked_at": blocked_at_ts.isoformat() if blocked_at_ts else None,
            },
        )
    closes_at = _normalize_ts(getattr(market, "closes_at", None))
    if cutoff_seconds > 0 and closes_at is not None:
        cutoff_time = closes_at - timedelta(seconds=int(cutoff_seconds))
        if now >= cutoff_time:
            block_time = cutoff_time
            blocked_at_ts = _normalize_ts(blocked_at)
            if blocked_at_ts is None or blocked_at_ts > block_time:
                market.commits_blocked_at = block_time
                blocked_at_ts = block_time
            if session is not None:
                session.add(market)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "market_near_resolution",
                    "closes_at": closes_at.isoformat(),
                    "cutoff_seconds": cutoff_seconds,
                    "commits_blocked_at": blocked_at_ts.isoformat() if blocked_at_ts else None,
                },
            )
    if getattr(market, "closed", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Market is closed; new quotes are disabled",
        )


def build_quote_digest(
    chain_id: int,
    market_address: str,
    wallet_address: str,
    outcome_id: int,
    stake_wei: int,
    zen_usd_scaled: int,
    expiry_ts: int,
    quote_id_hex: str,
) -> bytes:
    """Build the QUOTE_V1 digest matching the on-chain verifier."""

    quote_bytes = bytes.fromhex(_strip_0x(quote_id_hex))
    if len(quote_bytes) != 32:
        raise ValueError("quote_id must be 32 bytes hex")
    return Web3.solidity_keccak(
        [
            "string",
            "uint256",
            "address",
            "address",
            "uint256",
            "uint256",
            "uint256",
            "uint256",
            "bytes32",
        ],
        [
            "QUOTE_V1",
            int(chain_id),
            Web3.to_checksum_address(market_address),
            Web3.to_checksum_address(wallet_address),
            int(outcome_id),
            int(stake_wei),
            int(zen_usd_scaled),
            int(expiry_ts),
            quote_bytes,
        ],
    )


_EIP712_QUOTE_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
    "Quote": [
        {"name": "marketAddress", "type": "address"},
        {"name": "walletAddress", "type": "address"},
        {"name": "outcomeId", "type": "uint256"},
        {"name": "stakeWei", "type": "uint256"},
        {"name": "zenUsdScaled", "type": "uint256"},
        {"name": "expiryTs", "type": "uint256"},
        {"name": "quoteId", "type": "bytes32"},
    ],
}


def build_eip712_quote_message(
    chain_id: int,
    verifying_contract: str,
    market_address: str,
    wallet_address: str,
    outcome_id: int,
    stake_wei: int,
    zen_usd_scaled: int,
    expiry_ts: int,
    quote_id_hex: str,
) -> dict:
    """Build the EIP-712 typed data dict for a QUOTE_V1 signature."""

    quote_bytes = bytes.fromhex(_strip_0x(quote_id_hex))
    if len(quote_bytes) != 32:
        raise ValueError("quote_id must be 32 bytes hex")
    return {
        "types": _EIP712_QUOTE_TYPES,
        "primaryType": "Quote",
        "domain": {
            "name": "RevealMarket",
            "version": "1",
            "chainId": int(chain_id),
            "verifyingContract": Web3.to_checksum_address(verifying_contract),
        },
        "message": {
            "marketAddress": Web3.to_checksum_address(market_address),
            "walletAddress": Web3.to_checksum_address(wallet_address),
            "outcomeId": int(outcome_id),
            "stakeWei": int(stake_wei),
            "zenUsdScaled": int(zen_usd_scaled),
            "expiryTs": int(expiry_ts),
            "quoteId": quote_bytes,
        },
    }


def _is_internal_caller(internal_secret: str | None) -> bool:
    if not internal_secret:
        return False
    if not settings.internal_api_secret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="internal_secret_not_configured")
    if not hmac.compare_digest(internal_secret, settings.internal_api_secret.get_secret_value()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_internal_secret")
    return True


def _verify_scoped_signature(wallet: str, challenge: str, signature: str) -> None:
    try:
        recovered = Account.recover_message(encode_defunct(text=challenge), signature=signature)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid_signature:{exc}") from exc
    if recovered.lower() != wallet.lower():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="wallet_signature_mismatch")


async def _consume_quote_nonce(wallet: str, nonce: str, issued_at: int) -> None:
    ttl_seconds = max(int(getattr(settings, "quote_signature_nonce_ttl_seconds", 300)), 30)
    key = f"pricing:quote:nonce:{wallet.lower()}:{nonce}"
    cache_client = await get_cache_client()
    if cache_client is not None:
        try:
            consumed = await cache_client.set(key, str(issued_at), ex=ttl_seconds, nx=True)
        except Exception as exc:  # pragma: no cover - cache fallback
            log_event(
                logger,
                logging.WARNING,
                event="pricing.quote.nonce_cache_failed",
                message="failed to persist quote nonce in redis; using local fallback",
                error=str(exc),
            )
        else:
            if consumed:
                return
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="wallet_signature_replayed")

    now = datetime.now(tz=UTC)
    async with _QUOTE_NONCE_FALLBACK_LOCK:
        expired_keys = [k for k, expires_at in _QUOTE_NONCE_FALLBACK.items() if expires_at <= now]
        for stale_key in expired_keys:
            _QUOTE_NONCE_FALLBACK.pop(stale_key, None)
        if key in _QUOTE_NONCE_FALLBACK:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="wallet_signature_replayed")
        _QUOTE_NONCE_FALLBACK[key] = now + timedelta(seconds=ttl_seconds)


async def _verify_quote_signature(
    wallet: str,
    market_id: str,
    outcome_id: int,
    stake_wei: int,
    signature: str,
    *,
    nonce: str | None,
    issued_at: int | None,
) -> None:
    nonce_value = (nonce or "").strip()
    if not nonce_value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="wallet_signature_nonce_required")
    if len(nonce_value) > 128:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="wallet_signature_nonce_invalid")
    if issued_at is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="wallet_signature_timestamp_required")
    now_ts = int(datetime.now(tz=UTC).timestamp())
    max_age_seconds = max(int(getattr(settings, "quote_signature_max_age_seconds", 300)), 30)
    if abs(now_ts - int(issued_at)) > max_age_seconds:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="wallet_signature_stale")
    challenge = f"quote:{market_id}:{wallet.lower()}:{int(outcome_id)}:{int(stake_wei)}:{nonce_value}:{int(issued_at)}"
    _verify_scoped_signature(wallet, challenge, signature)
    await _consume_quote_nonce(wallet, nonce_value, int(issued_at))


def _verify_submit_signature(wallet: str, quote_id: str, signature: str) -> None:
    challenge = f"quote-submit:{quote_id}:{wallet.lower()}"
    _verify_scoped_signature(wallet, challenge, signature)


def _verify_quote_state_signature(wallet: str, quote_id: str, signature: str) -> None:
    challenge = f"quote-state:{quote_id}:{wallet.lower()}"
    _verify_scoped_signature(wallet, challenge, signature)


async def _enforce_caps(
    session: AsyncSession,
    *,
    stake_zen: Decimal,
    market_id: str | None,
    wallet_address: str | None,
    include_stake: bool = True,
    exclude_quote: models.Quote | None = None,
    statuses: set[str] | None = None,
) -> tuple[float | None, float | None, float | None, float | None]:
    """Validate stake caps and return projected totals and remaining allowances."""

    await repository_async.expire_stale_quotes(session)
    window = settings.bet_cap_ttl_seconds
    status_filter = statuses
    market_total = None
    user_total = None
    if market_id:
        market_existing = float(
            await repository_async.sum_quote_stakes(
                session, market_id=market_id, window_seconds=window, statuses=status_filter
            )
        )
        if exclude_quote and exclude_quote.market_id == market_id:
            market_existing = max(0.0, market_existing - float(exclude_quote.stake_zen))
        projected_market = market_existing + (float(stake_zen) if include_stake else 0.0)
        if projected_market > settings.max_market_stake_zen:
            remaining = max(0.0, settings.max_market_stake_zen - market_existing)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "market_cap_exceeded",
                    "max_market_stake_zen": settings.max_market_stake_zen,
                    "remaining_market_stake_zen": remaining,
                    "stake_zen": float(stake_zen),
                    "market_id": market_id,
                },
            )
        market_total = projected_market

    if market_id and wallet_address:
        user_existing = float(
            await repository_async.sum_quote_stakes(
                session,
                market_id=market_id,
                wallet_address=wallet_address,
                window_seconds=window,
                statuses=status_filter,
            )
        )
        if exclude_quote and exclude_quote.market_id == market_id and exclude_quote.wallet_address == wallet_address:
            user_existing = max(0.0, user_existing - float(exclude_quote.stake_zen))
        projected_user = user_existing + (float(stake_zen) if include_stake else 0.0)
        if projected_user > settings.max_user_stake_per_market_zen:
            remaining_user_cap = max(0.0, settings.max_user_stake_per_market_zen - user_existing)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "user_market_cap_exceeded",
                    "max_user_stake_per_market_zen": settings.max_user_stake_per_market_zen,
                    "remaining_user_stake_zen": remaining_user_cap,
                    "stake_zen": float(stake_zen),
                    "market_id": market_id,
                    "wallet_address": wallet_address,
                },
            )
        user_total = projected_user

    remaining_market = None
    remaining_user = None
    if market_total is not None:
        remaining_market = max(0.0, settings.max_market_stake_zen - market_total)
    if user_total is not None:
        remaining_user = max(0.0, settings.max_user_stake_per_market_zen - user_total)
    return market_total, user_total, remaining_market, remaining_user


@router.post("/pricing/quote", response_model=schemas.PricingQuoteResponse, tags=["pricing"])
async def pricing_quote(
    payload: schemas.PricingQuoteRequest,
    wallet_signature: str | None = Header(default=None, alias="X-Wallet-Signature"),
    wallet_signature_nonce: str | None = Header(default=None, alias="X-Wallet-Signature-Nonce"),
    wallet_signature_timestamp: int | None = Header(default=None, alias="X-Wallet-Signature-Timestamp"),
    internal_secret: str | None = Header(default=None, alias="X-Internal-Secret"),
    session: AsyncSession = Depends(get_session),
) -> schemas.PricingQuoteResponse:
    """Generate a signed quote bound to stake, FX, outcome, and expiry."""

    request_id = get_request_id()
    now = datetime.now(tz=UTC)
    user_id = payload.wallet_address
    quote_id_for_audit: str | None = None
    try:
        if payload.stake_zen > settings.max_stake_zen:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "stake_above_cap",
                    "stake_zen": float(payload.stake_zen),
                    "max_stake_zen": settings.max_stake_zen,
                },
            )
        ticket_size_wei = int(settings.ticket_size_wei)
        stake_wei = _to_wei_amount(payload.stake_zen)
        if stake_wei != ticket_size_wei:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"stake_mismatch_expected_{ticket_size_wei}",
            )
        internal_caller = _is_internal_caller(internal_secret)
        if settings.pricing_quote_signature_required and not internal_caller:
            if not wallet_signature:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="wallet_signature_required")
            await _verify_quote_signature(
                payload.wallet_address,
                payload.market_id,
                int(payload.outcome_id),
                int(stake_wei),
                wallet_signature,
                nonce=wallet_signature_nonce,
                issued_at=wallet_signature_timestamp,
            )
        market_record = await repository_async.get_market_by_event_id(session, payload.market_id)
        if market_record and (
            market_record.status
            in {shared_models.MarketStatusEnum.SETTLED.value, shared_models.MarketStatusEnum.CANCELLED.value}
            or market_record.resolved_at is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Market is settled; new quotes are disabled",
            )
        if market_record:
            _assert_commits_allowed(market_record, now, session)
        # Quotes can be issued before on-chain market deployment.
        # Deployment is handled later during /trade/commit.
        ensured_market_address: str | None = (payload.market_address or "") or None
        if not ensured_market_address and market_record is not None:
            ensured_market_address = getattr(market_record, "market_address", None)
        try:
            fx_quote = await fetch_fx_quote(settings)
            if fx_quote.stale:
                raise _pricing_unavailable(
                    "fx_stale",
                    request_id=request_id,
                    fx_received_at=fx_quote.received_at.isoformat() if fx_quote.received_at else None,
                )
            zen_usd = float(fx_quote.zen_usd) if fx_quote.zen_usd is not None else None
            fx_received_at = fx_quote.received_at
        except HTTPException:
            raise
        except Exception as exc:
            raise _pricing_unavailable("fx_unavailable", request_id=request_id, error=str(exc)) from exc

        market_total = None
        user_total = None
        user_remaining = None
        market_remaining = None
        if payload.market_id:
            market_total, user_total, market_remaining, user_remaining = await _enforce_caps(
                session,
                stake_zen=payload.stake_zen,
                market_id=payload.market_id,
                wallet_address=payload.wallet_address,
                include_stake=True,
            )

        outcome_price = None
        if payload.market_id is not None:
            outcome_price = await _resolve_outcome_price(session, payload.market_id, payload.outcome_id)
        if outcome_price is None or outcome_price <= 0:
            raise _pricing_unavailable("price_unavailable", request_id=request_id)

        if zen_usd is None:
            raise _pricing_unavailable("fx_unavailable", request_id=request_id)
        if settings.pricing_chain_id is None:
            raise _pricing_unavailable("pricing_chain_missing", request_id=request_id)

        zen_usd_scaled = _scale_fx_value(zen_usd)
        engine = PricingEngine(settings)
        try:
            quote = engine.quote(
                Decimal(str(payload.stake_zen)),
                Decimal(str(zen_usd)),
                Decimal(str(outcome_price)),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        payout_zen = quote.payout_zen

        expires_at = datetime.now(tz=UTC) + timedelta(seconds=settings.pricing_quote_ttl_seconds)
        expiry_ts = int(expires_at.timestamp())
        quote_id = token_hex(32)
        quote_id_for_audit = quote_id
        if settings.pricing_signer_private_key is None:
            raise _pricing_unavailable("pricing_signer_unavailable", request_id=request_id)
        raw_signer_key = settings.pricing_signer_private_key
        signer_key: str | None
        if isinstance(raw_signer_key, SecretStr):
            signer_key = raw_signer_key.get_secret_value()
        else:
            signer_key = cast(str | None, raw_signer_key)
        signer_account = await asyncio.to_thread(load_account, signer_key)
        signature: str | None = None
        signer_address: str | None = None
        if ensured_market_address:
            try:
                eip712_msg = build_eip712_quote_message(
                    settings.pricing_chain_id,
                    settings.pricing_verifying_contract,
                    ensured_market_address,
                    payload.wallet_address,
                    int(payload.outcome_id),
                    stake_wei,
                    zen_usd_scaled,
                    expiry_ts,
                    quote_id,
                )
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
            message = encode_typed_data(full_message=eip712_msg)
            signed = Account.sign_message(message, signer_account.key)
            signature = signed.signature.hex()
            signer_address = signer_account.address

        quote = quote.model_copy(
            update={
                "max_stake_zen": settings.max_stake_zen,
                "max_user_stake_per_market_zen": settings.max_user_stake_per_market_zen if payload.market_id else None,
                "max_market_stake_zen": settings.max_market_stake_zen if payload.market_id else None,
                "remaining_user_stake_zen": user_remaining,
                "remaining_market_stake_zen": market_remaining,
                "stake_wei": stake_wei,
                "zen_usd_scaled": zen_usd_scaled,
                "quote_id": quote_id,
                "expires_at": expires_at,
                "expiry_ts": expiry_ts,
                "fx_stale": False,
                "fx_received_at": fx_received_at,
                "signature": signature,
                "signature_version": "eip712_v1" if signature else None,
                "signer": signer_address,
                "market_id": payload.market_id,
                "user_id": user_id,
                "wallet_address": payload.wallet_address,
                "outcome_id": payload.outcome_id,
                "market_address": ensured_market_address,
                "chain_id": settings.pricing_chain_id,
                "payout_zen": payout_zen,
            }
        )
        quote_payload = quote.model_dump(mode="json")
        try:
            await repository_async.create_quote(
                session,
                {
                    "quote_id": quote_id,
                    "status": models.QuoteStatusEnum.ISSUED.value,
                    "payload": quote_payload,
                    "stake_zen": Decimal(str(quote.stake_zen)),
                    "stake_wei": stake_wei,
                    "fx_scaled": zen_usd_scaled,
                    "zen_usd": quote.zen_usd,
                    "market_id": payload.market_id,
                    "market_address": ensured_market_address,
                    "user_id": user_id,
                    "wallet_address": payload.wallet_address,
                    "outcome_id": quote.outcome_id,
                    "chain_id": settings.pricing_chain_id,
                    "expires_at": expires_at,
                },
            )
            await session.flush()
            await repository_async.record_quote_audit(
                session,
                build_quote_audit_payload(
                    quote_id=quote_id,
                    action="issued",
                    payload=quote_payload,
                    status=models.QuoteStatusEnum.ISSUED.value,
                ),
            )
        except ValueError as exc:
            if quote_id_for_audit and quote_payload:
                await repository_async.record_quote_audit(
                    session,
                    build_quote_audit_payload(
                        quote_id=quote_id_for_audit,
                        action="issue_failed",
                        payload=quote_payload,
                        error=str(exc),
                        context={"reason": "duplicate"},
                    ),
                )
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - defensive log
            log_event(
                logger,
                logging.ERROR,
                event="pricing.quote.persist_failed",
                message="failed to persist issued quote",
                quote_id=quote_id,
                error=str(exc),
            )
            raise _pricing_unavailable("quote_persist_failed", request_id=request_id, error=str(exc)) from exc

        log_event(
            logger,
            logging.INFO,
            event="pricing.quote",
            message="pricing quote generated",
            stake_zen=payload.stake_zen,
            zen_usd=zen_usd,
            total_monetisation=str(quote.total_monetization),
            market_total=market_total,
            user_total=user_total,
            quote_id=quote_id,
            market_id=payload.market_id,
            user_id=payload.user_id,
        )
        PRICING_COUNTER.labels(event="issue", result="ok").inc()
        return quote
    except HTTPException as exc:
        if quote_id_for_audit:
            await repository_async.record_quote_audit(
                session,
                build_quote_audit_payload(
                    quote_id=quote_id_for_audit,
                    action="issue_failed",
                    payload={"user_id": user_id, "wallet_address": payload.wallet_address},
                    error=str(exc.detail) if hasattr(exc, "detail") else str(exc),
                ),
            )
        raise
    except Exception as exc:  # pragma: no cover - defensive audit fallback
        if quote_id_for_audit:
            await repository_async.record_quote_audit(
                session,
                build_quote_audit_payload(
                    quote_id=quote_id_for_audit,
                    action="issue_failed",
                    payload={"user_id": user_id, "wallet_address": payload.wallet_address},
                    error=str(exc),
                ),
            )
        raise


@router.post(
    "/pricing/preview",
    response_model=schemas.PricingQuoteResponse,
    tags=["pricing"],
    dependencies=[Depends(_check_preview_rate_limit)],
)
async def pricing_quote_preview(
    payload: schemas.PricingQuoteRequest,
    session: AsyncSession = Depends(get_session),
) -> schemas.PricingQuoteResponse:
    """Return an unsigned, non-persistent preview quote (no market creation, no signature)."""

    # No creation here; best-effort fetch of existing market address.
    request_id = get_request_id()
    now = datetime.now(tz=UTC)
    user_id = payload.user_id or payload.wallet_address
    ticket_size_wei = int(settings.ticket_size_wei)
    stake_wei = _to_wei_amount(payload.stake_zen)
    if stake_wei != ticket_size_wei:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"stake_mismatch_expected_{ticket_size_wei}",
        )
    market_record = None
    if payload.market_id:
        market_record = await repository_async.get_market_by_event_id(session, payload.market_id)
        if market_record:
            _assert_commits_allowed(market_record, now, session)
    market_address: str | None = payload.market_address or None
    if payload.market_id and not market_address and market_record:
        market_address = getattr(market_record, "market_address", None)
    try:
        fx_quote = await fetch_fx_quote(settings)
        if fx_quote.stale:
            raise _pricing_unavailable(
                "fx_stale",
                request_id=request_id,
                fx_received_at=fx_quote.received_at.isoformat() if fx_quote.received_at else None,
            )
        zen_usd = float(fx_quote.zen_usd) if fx_quote.zen_usd is not None else None
        fx_received_at = fx_quote.received_at
    except HTTPException:
        raise
    except Exception as exc:
        raise _pricing_unavailable("fx_unavailable", request_id=request_id, error=str(exc)) from exc

    market_total = None
    user_total = None
    user_remaining = None
    market_remaining = None
    if payload.market_id:
        market_total, user_total, market_remaining, user_remaining = await _enforce_caps(
            session,
            stake_zen=payload.stake_zen,
            market_id=payload.market_id,
            wallet_address=payload.wallet_address,
            include_stake=True,
        )

    outcome_price = None
    if payload.market_id is not None:
        outcome_price = await _resolve_outcome_price(session, payload.market_id, payload.outcome_id)
    if outcome_price is None or outcome_price <= 0:
        raise _pricing_unavailable("price_unavailable", request_id=request_id)

    if zen_usd is None:
        raise _pricing_unavailable("fx_unavailable", request_id=request_id)
    if settings.pricing_chain_id is None:
        raise _pricing_unavailable("pricing_chain_missing", request_id=request_id)

    stake_wei = _to_wei_amount(payload.stake_zen)
    zen_usd_scaled = _scale_fx_value(zen_usd)
    engine = PricingEngine(settings)
    try:
        quote = engine.quote(
            Decimal(str(payload.stake_zen)),
            Decimal(str(zen_usd)),
            Decimal(str(outcome_price)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    payout_zen = quote.payout_zen

    # Preview response mirrors the signed payload but omits signature/persistence/expiry.
    expires_at = datetime.now(tz=UTC) + timedelta(seconds=settings.pricing_quote_ttl_seconds)
    expiry_ts = int(expires_at.timestamp())
    return quote.model_copy(
        update={
            "max_stake_zen": settings.max_stake_zen,
            "max_user_stake_per_market_zen": settings.max_user_stake_per_market_zen if payload.market_id else None,
            "max_market_stake_zen": settings.max_market_stake_zen if payload.market_id else None,
            "remaining_user_stake_zen": user_remaining,
            "remaining_market_stake_zen": market_remaining,
            "stake_wei": stake_wei,
            "zen_usd_scaled": zen_usd_scaled,
            "quote_id": None,
            "expires_at": expires_at,
            "expiry_ts": expiry_ts,
            "fx_stale": False,
            "fx_received_at": fx_received_at,
            "signature": None,
            "signer": None,
            "market_id": payload.market_id,
            "user_id": user_id,
            "wallet_address": payload.wallet_address,
            "outcome_id": payload.outcome_id,
            "market_address": market_address,
            "chain_id": settings.pricing_chain_id,
            "payout_zen": payout_zen,
        }
    )


@router.post("/pricing/submit", response_model=schemas.PricingSubmitResponse, tags=["pricing"])
async def pricing_submit(
    payload: schemas.PricingSubmitRequest,
    wallet_signature: str | None = Header(default=None, alias="X-Wallet-Signature"),
    internal_secret: str | None = Header(default=None, alias="X-Internal-Secret"),
    session: AsyncSession = Depends(get_session),
) -> schemas.PricingSubmitResponse:
    """Validate and mark a quote as consumed, re-checking FX drift if requested."""

    request_id = get_request_id()
    quote = payload.quote
    now = datetime.now(tz=UTC)
    quote_payload_for_audit = quote.model_dump(mode="json")
    try:

        def _as_aware(dt: datetime | None) -> datetime | None:
            if dt is None:
                return None
            if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                return dt.replace(tzinfo=UTC)
            return dt

        internal_caller = _is_internal_caller(internal_secret)
        if not internal_caller and not wallet_signature:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="wallet_signature_required")

        if settings.pricing_chain_id is None:
            raise _pricing_unavailable("pricing_chain_missing", request_id=request_id)
        if quote.wallet_address is None or quote.market_address is None or quote.outcome_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="wallet_address, market_address, and outcome_id are required for signed quotes",
            )

        raw_signer_key = settings.pricing_signer_private_key
        signer_key: str | None
        if isinstance(raw_signer_key, SecretStr):
            signer_key = raw_signer_key.get_secret_value()
        else:
            signer_key = cast(str | None, raw_signer_key)
        signer_account = await asyncio.to_thread(load_account, signer_key) if signer_key else None
        if signer_account is None:
            raise _pricing_unavailable("pricing_signer_unavailable", request_id=request_id)

        if not quote.quote_id:
            PRICING_COUNTER.labels(event="submit", result="missing").inc()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote not found or expired")
        quote_id = quote.quote_id
        stmt = select(models.Quote).where(models.Quote.quote_id == quote_id).with_for_update()
        db_quote = (await session.execute(stmt)).scalar_one_or_none()
        if db_quote is None:
            PRICING_COUNTER.labels(event="submit", result="missing").inc()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote not found or expired")
        wallet_for_auth = (db_quote.wallet_address or quote.wallet_address or "").strip()
        if not internal_caller:
            if not wallet_for_auth:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="quote_wallet_missing")
            _verify_submit_signature(wallet_for_auth, quote_id, cast(str, wallet_signature))
        if db_quote.status == models.QuoteStatusEnum.CONSUMED.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Quote already consumed")
        db_expires_at = _as_aware(cast(datetime | None, getattr(db_quote, "expires_at", None)))
        if db_quote.status == models.QuoteStatusEnum.EXPIRED.value or (db_expires_at and db_expires_at <= now):
            db_quote.status = models.QuoteStatusEnum.EXPIRED.value
            await session.flush()
            PRICING_COUNTER.labels(event="submit", result="expired").inc()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote expired")
        quote_expires_at = _as_aware(quote.expires_at)
        if quote_expires_at and quote_expires_at <= now:
            db_quote.status = models.QuoteStatusEnum.EXPIRED.value
            await session.flush()
            PRICING_COUNTER.labels(event="submit", result="expired").inc()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote expired")
        if db_quote.wallet_address and quote.wallet_address:
            if db_quote.wallet_address.lower() != quote.wallet_address.lower():
                PRICING_COUNTER.labels(event="submit", result="wallet_mismatch").inc()
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote wallet mismatch")
        if db_quote.market_id and quote.market_id and db_quote.market_id != quote.market_id:
            PRICING_COUNTER.labels(event="submit", result="market_id_mismatch").inc()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote market id mismatch")
        if db_quote.market_address and quote.market_address:
            if db_quote.market_address.lower() != quote.market_address.lower():
                PRICING_COUNTER.labels(event="submit", result="market_mismatch").inc()
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote market mismatch")
        if db_quote.outcome_id is not None and quote.outcome_id is not None:
            if db_quote.outcome_id != quote.outcome_id:
                PRICING_COUNTER.labels(event="submit", result="outcome_mismatch").inc()
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote outcome mismatch")

        expiry_reference = quote_expires_at or db_expires_at or now
        expiry_ts = quote.expiry_ts or int(expiry_reference.timestamp())
        quote.expiry_ts = expiry_ts
        stake_wei = quote.stake_wei
        zen_usd_scaled = quote.zen_usd_scaled
        recalculated_stake = _to_wei_amount(quote.stake_zen)
        recalculated_fx = _scale_fx_value(quote.zen_usd)
        if recalculated_stake != stake_wei or recalculated_fx != zen_usd_scaled:
            PRICING_COUNTER.labels(event="submit", result="scaled_mismatch").inc()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Quote fields do not match scaled values"
            )
        if not quote.signature:
            try:
                eip712_msg = build_eip712_quote_message(
                    settings.pricing_chain_id,
                    settings.pricing_verifying_contract,
                    quote.market_address,
                    quote.wallet_address,
                    int(quote.outcome_id),
                    stake_wei,
                    zen_usd_scaled,
                    expiry_ts,
                    quote_id,
                )
                signed = Account.sign_message(encode_typed_data(full_message=eip712_msg), signer_account.key)
                quote.signature = signed.signature.hex()
                quote.signer = signer_account.address
            except Exception as exc:
                PRICING_COUNTER.labels(event="submit", result="bad_signature").inc()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid signature: {exc}"
                ) from exc
        try:
            eip712_msg = build_eip712_quote_message(
                settings.pricing_chain_id,
                settings.pricing_verifying_contract,
                quote.market_address,
                quote.wallet_address,
                int(quote.outcome_id),
                stake_wei,
                zen_usd_scaled,
                expiry_ts,
                quote_id,
            )
            recovered = Account.recover_message(encode_typed_data(full_message=eip712_msg), signature=quote.signature)
        except Exception as exc:
            PRICING_COUNTER.labels(event="submit", result="bad_signature").inc()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid signature: {exc}") from exc
        expected_signer = (quote.signer or "").lower() if quote.signer else None
        if expected_signer:
            signer_mismatch = recovered.lower() != expected_signer
        else:
            # Fallback for legacy payloads that predate signer persistence.
            signer_mismatch = recovered.lower() != signer_account.address.lower()
        if signer_mismatch:
            PRICING_COUNTER.labels(event="submit", result="signer_mismatch").inc()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote signer mismatch")
        if db_quote.stake_wei != stake_wei or db_quote.fx_scaled != zen_usd_scaled:
            PRICING_COUNTER.labels(event="submit", result="payload_mismatch").inc()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote payload mismatch with ledger")

        current_fx: Decimal | None = None
        if payload.max_fx_diff_percent is not None:
            try:
                fx_quote = await fetch_fx_quote(settings)
                if fx_quote.zen_usd is not None:
                    current_fx = fx_quote.zen_usd
                if fx_quote.stale:
                    PRICING_COUNTER.labels(event="submit", result="fx_stale").inc()
                    raise _pricing_unavailable(
                        "fx_stale",
                        request_id=request_id,
                        fx_received_at=fx_quote.received_at.isoformat() if fx_quote.received_at else None,
                    )
                fx_diff_percent = (
                    (abs(current_fx - quote.zen_usd) / quote.zen_usd * Decimal("100"))
                    if current_fx is not None and quote.zen_usd
                    else Decimal("0")
                )
                if current_fx is None:
                    PRICING_COUNTER.labels(event="submit", result="fx_missing").inc()
                    raise _pricing_unavailable("fx_missing", request_id=request_id)
                if fx_diff_percent > payload.max_fx_diff_percent:
                    PRICING_COUNTER.labels(event="submit", result="fx_drift").inc()
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"FX drift {fx_diff_percent:.4f}% exceeds bound {payload.max_fx_diff_percent}%",
                    )
            except HTTPException:
                raise
            except Exception as exc:
                PRICING_COUNTER.labels(event="submit", result="fx_error").inc()
                raise _pricing_unavailable("fx_check_failed", request_id=request_id, error=str(exc)) from exc
        else:
            current_fx = quote.zen_usd
        market_id_for_caps = db_quote.market_id
        if db_quote.market_id is not None:
            quote.market_id = db_quote.market_id

        await _enforce_caps(
            session,
            stake_zen=quote.stake_zen,
            market_id=market_id_for_caps,
            wallet_address=quote.wallet_address,
            exclude_quote=db_quote,
            include_stake=True,
            statuses={
                models.QuoteStatusEnum.ISSUED.value,
                models.QuoteStatusEnum.CONSUMED.value,
            },
        )

        db_quote.payload = quote.model_dump(mode="json")
        await repository_async.mark_quote_status(
            session,
            db_quote,
            models.QuoteStatusEnum.CONSUMED,
            consumed_at=now,
        )
        await session.flush()
        await repository_async.record_quote_audit(
            session,
            build_quote_audit_payload(
                quote_id=quote_id,
                action="consumed",
                payload=db_quote.payload,
                status=models.QuoteStatusEnum.CONSUMED.value,
            ),
        )
        PRICING_COUNTER.labels(event="submit", result="ok").inc()
        log_event(
            logger,
            logging.INFO,
            event="pricing.submit",
            message="pricing quote submitted",
            quote_id=quote.quote_id,
            market_id=quote.market_id,
            user_id=quote.user_id,
            outcome_id=quote.outcome_id,
            stake_zen=float(quote.stake_zen),
            zen_usd=float(quote.zen_usd),
        )

        return schemas.PricingSubmitResponse(
            quote=quote,
            current_fx=current_fx if current_fx is not None else quote.zen_usd,
            valid=True,
        )
    except HTTPException as exc:
        error_text = str(exc.detail) if hasattr(exc, "detail") else str(exc)
        await repository_async.record_quote_audit(
            session,
            build_quote_audit_payload(
                quote_id=quote.quote_id or "unknown",
                action="consume_failed",
                payload=quote_payload_for_audit,
                error=error_text,
            ),
        )
        raise
    except Exception as exc:  # pragma: no cover - defensive audit fallback
        await repository_async.record_quote_audit(
            session,
            build_quote_audit_payload(
                quote_id=quote.quote_id or "unknown",
                action="consume_failed",
                payload=quote_payload_for_audit,
                error=str(exc),
            ),
        )
        raise


@router.get("/pricing/quotes/{quote_id}", response_model=schemas.QuoteRecord, tags=["pricing"])
async def pricing_quote_state(
    quote_id: str,
    wallet: str | None = None,
    wallet_signature: str | None = Header(default=None, alias="X-Wallet-Signature"),
    internal_secret: str | None = Header(default=None, alias="X-Internal-Secret"),
    session: AsyncSession = Depends(get_session),
) -> schemas.QuoteRecord:
    record = await repository_async.get_quote(session, quote_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="quote_not_found")
    internal_caller = _is_internal_caller(internal_secret)
    if not internal_caller:
        wallet_address = (record.wallet_address or "").strip()
        requested_wallet = (wallet or "").strip()
        if not requested_wallet:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="wallet_required")
        if not wallet_signature:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="wallet_signature_required")
        if not wallet_address or wallet_address.lower() != requested_wallet.lower():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="wallet_quote_forbidden")
        _verify_quote_state_signature(requested_wallet, quote_id, wallet_signature)
    return schemas.QuoteRecord.model_validate(record)


@router.get("/pricing/fx", response_model=schemas.FxQuoteResponse, tags=["pricing"])
async def pricing_fx() -> schemas.FxQuoteResponse:
    request_id = get_request_id()
    try:
        fx_quote = await fetch_fx_quote(settings, use_cache_on_error=False)
        if fx_quote.stale:
            log_event(
                logger,
                logging.WARNING,
                event="pricing.fx.stale",
                message="FX feed stale",
                fx_received_at=fx_quote.received_at.isoformat() if fx_quote.received_at else None,
            )
            raise _pricing_unavailable(
                "fx_stale",
                request_id=request_id,
                fx_received_at=fx_quote.received_at.isoformat() if fx_quote.received_at else None,
            )
        return fx_quote
    except httpx.HTTPError as exc:
        log_event(
            logger,
            logging.WARNING,
            event="pricing.fx.error",
            message="failed to fetch FX feed",
            error=str(exc),
        )
        raise _pricing_unavailable("fx_unavailable", request_id=request_id, error=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive catch for malformed payloads
        log_event(
            logger,
            logging.WARNING,
            event="pricing.fx.error",
            message="unexpected FX parsing error",
            error=str(exc),
        )
        raise _pricing_unavailable("fx_unavailable", request_id=request_id, error=str(exc)) from exc
