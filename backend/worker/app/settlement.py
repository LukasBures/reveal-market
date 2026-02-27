"""Settlement automation: lock batches, build snapshots, request proofs, and submit on-chain transactions."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

from eth_account import Account
from eth_typing import ChecksumAddress, HexStr
from redis.asyncio import Redis
from shared import models as shared_models
from shared import repository_async as shared_repository
from shared.async_utils import resolve_awaitable as _resolve_awaitable
from shared.logging import log_event
from shared.onchain import get_async_web3, to_checksum
from shared.onchain.abi import REVEAL_MARKET_ABI
from shared.poseidon import BATCH_SIZE
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from web3 import AsyncWeb3
from web3.contract.async_contract import AsyncContract
from web3.types import TxParams, Wei

from . import runtime
from .cache_ops import invalidate_cache_tags
from .database import session_scope
from .merkle import build_merkle_root_and_paths
from .metrics import LOCK_BATCHES_COUNTER, RELAYER_QUEUE_COUNTER
from .retry import clear_failure, failure_key, record_failure, should_attempt

logger = runtime.logger  # type: ignore[has-type]

_SETTLEMENT_LOCK_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


async def _acquire_settlement_submission_lock(
    redis_client: Redis | None,
    market_id: int,
) -> tuple[str | None, str | None]:
    if redis_client is None:
        return None, None
    key_prefix = str(runtime.settings.settlement_submission_lock_key_prefix).strip() or "settlement_submit_lock"
    lock_key = f"{key_prefix}:{market_id}"
    lock_token = secrets.token_hex(16)
    _CLOCK_SKEW_BUFFER = 5
    ttl_seconds = max(int(runtime.settings.settlement_submission_lock_ttl_seconds), 30) + _CLOCK_SKEW_BUFFER
    try:
        acquired = await _resolve_awaitable(redis_client.set(lock_key, lock_token, nx=True, ex=ttl_seconds))
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.DEBUG,
            event="worker.settlement.lock_acquire_failed",
            message="failed to acquire settlement submission lock",
            market_id=market_id,
            lock_key=lock_key,
            error=str(exc),
        )
        return None, None
    if not acquired:
        return None, lock_key
    return lock_token, lock_key


async def _release_settlement_submission_lock(
    redis_client: Redis | None,
    *,
    lock_key: str | None,
    lock_token: str | None,
) -> None:
    if redis_client is None or not lock_key or not lock_token:
        return
    try:
        if hasattr(redis_client, "eval"):
            await _resolve_awaitable(redis_client.eval(_SETTLEMENT_LOCK_RELEASE_LUA, 1, lock_key, lock_token))
            return
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.DEBUG,
            event="worker.settlement.lock_release_eval_failed",
            message="failed to release lock via lua; falling back to get/delete",
            lock_key=lock_key,
            error=str(exc),
        )
    try:
        current = await _resolve_awaitable(redis_client.get(lock_key))
        if current == lock_token:
            await _resolve_awaitable(redis_client.delete(lock_key))
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.DEBUG,
            event="worker.settlement.lock_release_failed",
            message="failed to release settlement submission lock",
            lock_key=lock_key,
            error=str(exc),
        )


def _normalize_bytes32(value: Any) -> str | None:
    """Return a 0x-prefixed hex string for bytes/HexBytes values."""

    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return "0x" + value.hex()
    hex_value = getattr(value, "hex", None)
    if callable(hex_value):
        return str(hex_value())
    return str(value)


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


def _batch_root_for_ticket(settlement: shared_models.Settlement, ticket_id: int) -> str | None:
    batch_roots = _parse_json_list(getattr(settlement, "batch_roots", None))
    if batch_roots:
        batch_index = int(ticket_id) // BATCH_SIZE
        if batch_index < len(batch_roots):
            return str(batch_roots[batch_index])
    if _is_empty_hex(getattr(settlement, "merkle_root", None)):
        return None
    return settlement.merkle_root


def _root_to_signal(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value)
    try:
        if raw.lower().startswith("0x"):
            return str(int(raw, 16))
        return str(int(raw))
    except Exception:
        return None


def _raw_tx_bytes(signed_tx: Any) -> bytes:
    # Prefer snake_case (web3/eth-account v7) with camelCase fallback for older versions.
    raw_tx = getattr(signed_tx, "raw_transaction", None)
    if raw_tx is None:
        raw_tx = getattr(signed_tx, "rawTransaction", None)
    if raw_tx is None:  # pragma: no cover - defensive for web3 variants
        raise ValueError("Signed transaction is missing raw transaction bytes")
    return cast(bytes, raw_tx)


def _build_market_contract(web3: AsyncWeb3, market_address: str) -> AsyncContract:
    """Return a typed contract instance for a market address."""

    checksum_address = cast(ChecksumAddress, to_checksum(market_address))
    return web3.eth.contract(address=checksum_address, abi=REVEAL_MARKET_ABI)


def _hex_to_bytes(value: str | None) -> bytes:
    if not value:
        return b""
    cleaned = value.removeprefix("0x")
    try:
        return bytes.fromhex(cleaned)
    except ValueError:
        return b""


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


class LockBatchDataError(RuntimeError):
    """Raised when commitments are incomplete or malformed for batch locking."""


def _normalize_leaf_hex(value: str | None) -> bytes:
    if not value:
        raise LockBatchDataError("missing_commitment_leaf")
    cleaned = value.removeprefix("0x")
    try:
        raw = bytes.fromhex(cleaned)
    except ValueError as exc:
        raise LockBatchDataError("invalid_commitment_leaf") from exc
    if len(raw) != 32:
        raise LockBatchDataError("invalid_commitment_leaf_length")
    return raw


def _build_batch_roots_from_commitments(
    commitments: list[shared_models.Commitment],
) -> tuple[list[str], list[int], int, str | None]:
    if not commitments:
        raise LockBatchDataError("no_commitments")

    _MAX_LEAF_INDEX = BATCH_SIZE * 1024  # upper bound sanity check

    leaves_by_index: dict[int, bytes] = {}
    max_index = -1
    for commitment in commitments:
        if commitment.leaf_index is None:
            raise LockBatchDataError("missing_leaf_index")
        leaf_index = int(commitment.leaf_index)
        if leaf_index < 0:
            raise LockBatchDataError("invalid_leaf_index")
        if leaf_index > _MAX_LEAF_INDEX:
            raise LockBatchDataError("leaf_index_exceeds_maximum")
        if leaf_index in leaves_by_index:
            raise LockBatchDataError("duplicate_leaf_index")
        leaf_hex = commitment.leaf or commitment.ticket_hash
        leaves_by_index[leaf_index] = _normalize_leaf_hex(leaf_hex)
        if leaf_index > max_index:
            max_index = leaf_index

    total_count = max_index + 1
    if len(leaves_by_index) != total_count:
        raise LockBatchDataError("leaf_index_gap")

    batch_roots: list[str] = []
    batch_counts: list[int] = []
    for batch_index in range((total_count + BATCH_SIZE - 1) // BATCH_SIZE):
        start = batch_index * BATCH_SIZE
        end = min(total_count, start + BATCH_SIZE)
        batch_leaves = [leaves_by_index[i] for i in range(start, end)]
        root, _ = build_merkle_root_and_paths(batch_leaves)
        batch_roots.append("0x" + root.hex())
        batch_counts.append(end - start)

    merkle_root = batch_roots[0] if len(batch_roots) == 1 else None
    return batch_roots, batch_counts, total_count, merkle_root


def settlement_needs_refresh(settlement: shared_models.Settlement | None) -> bool:
    """Return True when a settlement snapshot is missing critical fields."""

    if settlement is None:
        return True
    batch_roots = _parse_json_list(getattr(settlement, "batch_roots", None))
    batch_counts = _parse_json_list(getattr(settlement, "batch_counts", None))
    has_batch_roots = bool(batch_roots)
    has_merkle_root = not _is_empty_hex(getattr(settlement, "merkle_root", None))
    if not has_batch_roots and not has_merkle_root:
        return True
    if _is_empty_hex(settlement.circuit_hash):
        return True
    if batch_roots and (not batch_counts or len(batch_counts) != len(batch_roots)):
        return True
    if settlement.commitments_count is None:
        return True
    if settlement.pool_total_yes is None or settlement.pool_total_no is None:
        return True
    if settlement.total_escrow is None or settlement.total_liability is None:
        return True
    if settlement.rake_bps is None:
        return True
    if settlement.winning_outcome_id is None:
        return True
    return False


async def _fetch_onchain_snapshot(web3: AsyncWeb3, market_address: str) -> dict[str, Any]:
    """Return settlement-related state from the on-chain market contract."""

    contract = _build_market_contract(web3, market_address)
    # Batch the initial RPC calls to reduce sequential round trips
    (
        market_state_result,
        total_escrow,
        total_liability,
        pool_total_yes,
        pool_total_no,
        rake_bps,
        circuit_hash,
    ) = await asyncio.gather(
        contract.functions.marketState().call(),
        contract.functions.totalEscrow().call(),
        contract.functions.totalLiability().call(),
        contract.functions.poolTotalYes().call(),
        contract.functions.poolTotalNo().call(),
        contract.functions.rakeBps().call(),
        contract.functions.circuitHash().call(),
    )
    (
        commitments_root,
        next_ticket_id,
        phase_value,
        commit_deadline,
        winning_outcome_id,
    ) = market_state_result
    try:
        oracle = await contract.functions.oracle().call()
    except Exception:
        oracle = None
    try:
        result_posted = bool(await contract.functions.resultPosted().call())
    except Exception:
        result_posted = winning_outcome_id is not None
    batch_roots: list[str] = []
    batch_counts: list[int] = []
    try:
        if int(next_ticket_id or 0) > 0:
            total_batches = (int(next_ticket_id) + BATCH_SIZE - 1) // BATCH_SIZE

            async def _fetch_batch(idx: int) -> tuple[str, int]:
                root_value = await contract.functions.batchRoots(idx).call()
                count_value = await contract.functions.batchCounts(idx).call()
                return _normalize_bytes32(root_value) or str(root_value), int(count_value)

            tasks = [_fetch_batch(index) for index in range(total_batches)]
            results: list[tuple[str, int] | BaseException] = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    continue
                root_value, count_value = result
                batch_roots.append(root_value)
                batch_counts.append(int(count_value))
    except Exception:
        batch_roots = []
        batch_counts = []
    return {
        "commitments_count": int(next_ticket_id),
        "phase": int(phase_value),
        "winning_outcome_id": int(winning_outcome_id) if winning_outcome_id is not None else None,
        "total_escrow": int(total_escrow),
        "total_liability": int(total_liability),
        "pool_total_yes": int(pool_total_yes),
        "pool_total_no": int(pool_total_no),
        "rake_bps": int(rake_bps),
        "commitments_root": _normalize_bytes32(commitments_root),
        "circuit_hash": _normalize_bytes32(circuit_hash),
        "result_posted": result_posted,
        "batch_roots": batch_roots,
        "batch_counts": batch_counts,
        "commit_deadline": int(commit_deadline) if commit_deadline is not None else None,
        "oracle": str(oracle) if oracle is not None else None,
    }


async def _upsert_settlement_from_chain(
    session: AsyncSession, market: shared_models.Market, *, force: bool = False
) -> shared_models.Settlement | None:
    """Populate the settlement snapshot from on-chain state when available."""

    if not market.market_address or not runtime.settings.rpc_url:
        return None
    existing = await shared_repository.get_settlement_by_market_id(session, market.id)
    if existing is not None and not force and not settlement_needs_refresh(existing):
        return existing
    web3 = get_async_web3(str(runtime.settings.rpc_url))
    try:
        snapshot = await _fetch_onchain_snapshot(web3, market.market_address)
    except Exception as exc:  # pragma: no cover - network/execution errors
        log_event(
            logger,
            logging.WARNING,
            event="worker.settlement.chain_fetch_failed",
            message="failed to load settlement snapshot from chain",
            market_id=getattr(market, "event_id", None),
            error=str(exc),
        )
        return existing

    payload = {
        "merkle_root": snapshot.get("commitments_root"),
        "commitments_count": snapshot.get("commitments_count"),
        "batch_roots": snapshot.get("batch_roots"),
        "batch_counts": snapshot.get("batch_counts"),
        "pool_total_yes": snapshot.get("pool_total_yes"),
        "pool_total_no": snapshot.get("pool_total_no"),
        "total_escrow": snapshot.get("total_escrow"),
        "total_liability": snapshot.get("total_liability"),
        "rake_bps": snapshot.get("rake_bps"),
        "circuit_hash": snapshot.get("circuit_hash"),
    }
    winning_outcome_id = snapshot.get("winning_outcome_id")
    result_posted = bool(snapshot.get("result_posted"))
    phase_value = snapshot.get("phase")
    try:
        phase_value = int(phase_value) if phase_value is not None else None
    except (TypeError, ValueError):
        phase_value = None
    # Accept winning_outcome_id when chain has posted, phase >= 2, or the market is already marked final off-chain.
    # This lets us build a complete settlement snapshot as soon as the off-chain resolution is final, even if
    # the on-chain result flag has not been set yet.
    if winning_outcome_id is None and market.condition_id:
        try:
            resolution = await shared_repository.get_resolution_by_condition_id(session, market.condition_id)
            if resolution and resolution.winning_outcome_id is not None:
                winning_outcome_id = int(resolution.winning_outcome_id)
        except Exception:
            winning_outcome_id = None
    if winning_outcome_id is not None and (
        result_posted
        or (phase_value is not None and phase_value >= 2)
        or getattr(market, "resolution_status", None) == shared_models.ResolutionStatusEnum.FINAL.value
    ):
        payload["winning_outcome_id"] = winning_outcome_id
    return await shared_repository.upsert_settlement_snapshot(session, market.id, payload)


async def _fetch_relayer_address(relayer_base_url: str) -> str | None:
    if runtime.circuit_breaker and await runtime.circuit_breaker.is_open("relayer"):
        return None
    try:
        client = await runtime.get_http_client(runtime.settings.relayer_http_timeout_seconds)
        resp = await client.get(relayer_base_url.rstrip("/") + "/healthz")
        if resp.status_code != 200:
            return None
        payload = resp.json()
        address = payload.get("relayer") or payload.get("address")
        if runtime.circuit_breaker:
            await runtime.circuit_breaker.record_success("relayer")
        return str(address) if address else None
    except Exception:
        if runtime.circuit_breaker:
            await runtime.circuit_breaker.record_failure("relayer")
        return None


async def _poll_relayer_job(
    relayer_base_url: str,
    job_id: str,
    *,
    headers: dict[str, str],
    poll_seconds: float,
    max_attempts: int,
) -> dict[str, Any] | None:
    delay = max(poll_seconds, 0.1)
    for _attempt in range(max_attempts):
        try:
            if runtime.circuit_breaker and await runtime.circuit_breaker.is_open("relayer"):
                return None
            status_url = relayer_base_url.rstrip("/") + "/status"
            client = await runtime.get_http_client(runtime.settings.relayer_http_timeout_seconds)
            resp = await client.post(status_url, json={"jobId": job_id}, headers=headers)
            if resp.status_code == 200:
                payload = resp.json()
                status = str(payload.get("status") or "").lower()
                if status in {"succeeded", "confirmed"}:
                    if runtime.circuit_breaker:
                        await runtime.circuit_breaker.record_success("relayer")
                    return payload
                if status in {"failed", "deadletter"}:
                    if runtime.circuit_breaker:
                        await runtime.circuit_breaker.record_failure("relayer")
                    return payload
        except Exception as exc:
            log_event(
                logger,
                logging.DEBUG,
                event="worker.relayer.status_poll_failed",
                message="failed to poll relayer status",
                job_id=job_id,
                error=str(exc),
            )
            if runtime.circuit_breaker:
                await runtime.circuit_breaker.record_failure("relayer")
        await asyncio.sleep(delay)
        delay = min(delay * 2, max(poll_seconds, 1.0) * 8)
    return None


def _format_tx_hash(tx_hash: Any) -> str:
    if hasattr(tx_hash, "hex"):
        return tx_hash.hex()
    return str(tx_hash)


def _receipt_status(receipt: Any) -> int | None:
    if receipt is None:
        return None
    if isinstance(receipt, dict):
        return receipt.get("status")
    return getattr(receipt, "status", None)


def _ensure_tx_success(receipt: Any, tx_hash: Any, *, action: str) -> None:
    status_value = _receipt_status(receipt)
    if status_value != 1:
        raise RuntimeError(f"{action}_failed status={status_value} tx_hash={_format_tx_hash(tx_hash)}")


async def _submit_lock_batches(
    web3: AsyncWeb3,
    account,
    market_address: str,
    batch_roots: list[str],
    batch_counts: list[int],
) -> tuple[str, int | None]:
    contract = _build_market_contract(web3, market_address)
    base_tx: TxParams = {
        "from": account.address,
        "nonce": await web3.eth.get_transaction_count(account.address),
        "gas": int(runtime.settings.lock_batches_gas_limit),
    }
    if runtime.settings.lock_batches_gas_price_gwei is not None:
        base_tx["gasPrice"] = cast(Wei, int(runtime.settings.lock_batches_gas_price_gwei * 1e9))
    if runtime.settings.lock_batches_max_priority_fee_gwei is not None:
        base_tx["maxPriorityFeePerGas"] = cast(Wei, int(runtime.settings.lock_batches_max_priority_fee_gwei * 1e9))
    tx = await contract.functions.lockBatches(batch_roots, batch_counts, b"").build_transaction(base_tx)
    if "gasPrice" not in tx and "maxFeePerGas" not in tx:
        tx["gasPrice"] = await web3.eth.gas_price
    signed = account.sign_transaction(tx)
    tx_hash = await web3.eth.send_raw_transaction(_raw_tx_bytes(signed))
    receipt = await web3.eth.wait_for_transaction_receipt(tx_hash)
    _ensure_tx_success(receipt, tx_hash, action="lock_batches")
    return tx_hash.hex(), getattr(receipt, "blockNumber", None)


async def _call_relayer_lock_batches(
    *,
    relayer_base_url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    poll_seconds: float,
    max_attempts: int,
) -> dict[str, Any] | None:
    if runtime.circuit_breaker and await runtime.circuit_breaker.is_open("relayer"):
        raise RuntimeError("relayer_circuit_open")
    client = await runtime.get_http_client(runtime.settings.relayer_http_timeout_seconds)
    resp = await client.post(relayer_base_url.rstrip("/") + "/lock-batches", json=payload, headers=headers)
    if resp.status_code in {200, 201}:
        if runtime.circuit_breaker:
            await runtime.circuit_breaker.record_success("relayer")
        return resp.json()
    if resp.status_code == 202:
        body = resp.json()
        job_id = body.get("jobId") or body.get("job_id")
        if not job_id:
            if runtime.circuit_breaker:
                await runtime.circuit_breaker.record_failure("relayer")
            return body
        return await _poll_relayer_job(
            relayer_base_url,
            str(job_id),
            headers=headers,
            poll_seconds=poll_seconds,
            max_attempts=max_attempts,
        )
    if runtime.circuit_breaker:
        await runtime.circuit_breaker.record_failure("relayer")
    raise RuntimeError(f"relayer_lock_batches_failed:{resp.status_code}")


def _hydrate_public_signals(public_signals: Sequence[Any]) -> list[int]:
    signals: list[int] = []
    for value in list(public_signals)[:10]:
        try:
            signals.append(int(value))
        except Exception as exc:
            raise ValueError("publicSignals must be numeric") from exc
    if len(signals) != 10:
        raise ValueError("publicSignals length must be 10")
    return signals


async def _maybe_post_result(web3: AsyncWeb3, account, contract, winning_outcome_id: int) -> None:
    try:
        posted = await contract.functions.resultPosted().call()
        if posted:
            return
    except Exception as exc:
        # Best-effort; proceed to submit if missing
        log_event(
            logger,
            logging.DEBUG,
            event="worker.settlement.result_check_failed",
            message="failed to check resultPosted",
            error=str(exc),
        )
    log_event(
        logger,
        logging.INFO,
        event="worker.settlement.post_result.begin",
        message="posting winning outcome on-chain",
        outcome_id=int(winning_outcome_id),
    )
    tx_params: TxParams = {
        "from": account.address,
        "nonce": await web3.eth.get_transaction_count(account.address),
    }
    tx = await contract.functions.postResult(int(winning_outcome_id)).build_transaction(tx_params)
    if "gasPrice" not in tx and "maxFeePerGas" not in tx:
        tx["gasPrice"] = await web3.eth.gas_price
    signed = account.sign_transaction(tx)
    tx_hash = await web3.eth.send_raw_transaction(_raw_tx_bytes(signed))
    receipt = await web3.eth.wait_for_transaction_receipt(tx_hash)
    _ensure_tx_success(receipt, tx_hash, action="post_result")
    log_event(
        logger,
        logging.INFO,
        event="worker.settlement.post_result",
        message="posted winning outcome on-chain",
        tx_hash=tx_hash.hex(),
        block_number=getattr(receipt, "blockNumber", None),
    )


async def _submit_verify_and_settle(
    web3: AsyncWeb3,
    account,
    market_address: str,
    proof: str,
    public_signals: Sequence[Any],
    *,
    wait_for_receipt: bool = True,
) -> tuple[str, int | None]:
    contract = _build_market_contract(web3, market_address)
    signals = _hydrate_public_signals(public_signals)
    proof_bytes = bytes.fromhex(proof.removeprefix("0x"))
    base_tx: TxParams = {
        "from": account.address,
        "nonce": await web3.eth.get_transaction_count(account.address),
        "gas": 800_000,
    }
    # Apply optional gas overrides
    if runtime.settings.settlement_gas_price_gwei is not None:
        base_tx["gasPrice"] = cast(Wei, int(runtime.settings.settlement_gas_price_gwei * 1e9))
    if runtime.settings.settlement_max_priority_fee_gwei is not None:
        base_tx["maxPriorityFeePerGas"] = cast(Wei, int(runtime.settings.settlement_max_priority_fee_gwei * 1e9))
    tx = await contract.functions.verifyAndSettle(proof_bytes, signals).build_transaction(base_tx)
    if "gasPrice" not in tx and "maxFeePerGas" not in tx:
        tx["gasPrice"] = await web3.eth.gas_price
    signed = account.sign_transaction(tx)
    tx_hash = await web3.eth.send_raw_transaction(_raw_tx_bytes(signed))
    tx_hash_hex = web3.to_hex(tx_hash)
    if not wait_for_receipt:
        return tx_hash_hex, None
    receipt = await web3.eth.wait_for_transaction_receipt(tx_hash)
    _ensure_tx_success(receipt, tx_hash, action="verify_and_settle")
    return tx_hash_hex, getattr(receipt, "blockNumber", None)


async def _submit_verify_and_settle_batched(
    web3: AsyncWeb3,
    account,
    market_address: str,
    proofs: Sequence[str],
    public_signals: Sequence[Sequence[Any]],
    batch_indexes: Sequence[int],
    *,
    wait_for_receipt: bool = True,
) -> tuple[str, int | None]:
    contract = _build_market_contract(web3, market_address)
    hydrated_signals = [_hydrate_public_signals(signals) for signals in public_signals]
    proof_bytes = [bytes.fromhex(proof.removeprefix("0x")) for proof in proofs]
    batch_indexes_int = [int(value) for value in batch_indexes]
    base_tx: TxParams = {
        "from": account.address,
        "nonce": await web3.eth.get_transaction_count(account.address),
        "gas": 1_200_000,
    }
    if runtime.settings.settlement_gas_price_gwei is not None:
        base_tx["gasPrice"] = cast(Wei, int(runtime.settings.settlement_gas_price_gwei * 1e9))
    if runtime.settings.settlement_max_priority_fee_gwei is not None:
        base_tx["maxPriorityFeePerGas"] = cast(Wei, int(runtime.settings.settlement_max_priority_fee_gwei * 1e9))
    tx = await contract.functions.verifyAndSettleBatched(
        proof_bytes, hydrated_signals, batch_indexes_int
    ).build_transaction(base_tx)
    if "gasPrice" not in tx and "maxFeePerGas" not in tx:
        tx["gasPrice"] = await web3.eth.gas_price
    signed = account.sign_transaction(tx)
    tx_hash = await web3.eth.send_raw_transaction(_raw_tx_bytes(signed))
    tx_hash_hex = web3.to_hex(tx_hash)
    if not wait_for_receipt:
        return tx_hash_hex, None
    receipt = await web3.eth.wait_for_transaction_receipt(tx_hash)
    _ensure_tx_success(receipt, tx_hash, action="verify_and_settle_batched")
    return tx_hash_hex, getattr(receipt, "blockNumber", None)


async def _wait_for_submission_receipt(web3: AsyncWeb3, tx_hash: str, *, action: str) -> int | None:
    tx_hash_hex = tx_hash if str(tx_hash).startswith("0x") else f"0x{tx_hash}"
    receipt = await web3.eth.wait_for_transaction_receipt(cast(HexStr, tx_hash_hex))
    _ensure_tx_success(receipt, tx_hash_hex, action=action)
    return getattr(receipt, "blockNumber", None)


async def _resolve_winning_outcome(session: AsyncSession, market: shared_models.Market) -> int | None:
    resolution = None
    if market.condition_id:
        resolution = await shared_repository.get_resolution_by_condition_id(session, market.condition_id)
    if resolution and resolution.winning_outcome_id is not None:
        try:
            return int(resolution.winning_outcome_id)
        except Exception:
            return None
    return None


async def _list_lock_candidates(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int,
    after_closes_at: datetime | None = None,
    after_id: int | None = None,
) -> list[shared_models.Market]:
    commitments = select(shared_models.Commitment.market_id).distinct().subquery()
    stmt = (
        select(shared_models.Market)
        .join(commitments, shared_models.Market.id == commitments.c.market_id)
        .where(shared_models.Market.market_address.isnot(None))
        .where(shared_models.Market.status != shared_models.MarketStatusEnum.CANCELLED.value)
        .where(
            or_(
                shared_models.Market.commits_blocked_at.isnot(None),
                shared_models.Market.closes_at <= now,
                shared_models.Market.resolution_status.isnot(None),
            )
        )
    )
    if after_closes_at is not None:
        if after_id is not None:
            stmt = stmt.where(
                or_(
                    shared_models.Market.closes_at > after_closes_at,
                    and_(
                        shared_models.Market.closes_at == after_closes_at,
                        shared_models.Market.id > after_id,
                    ),
                )
            )
        else:
            stmt = stmt.where(shared_models.Market.closes_at > after_closes_at)
    stmt = stmt.order_by(shared_models.Market.closes_at.asc(), shared_models.Market.id.asc()).limit(limit)
    rows = await session.execute(stmt)
    return list(rows.scalars())


async def run_lock_batches_jobs(summary, redis_client: Redis | None) -> int:
    """Submit lockBatches for markets that have passed their commit deadline."""

    if not runtime.settings.rpc_url:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.lock_batches.disabled",
            message="lock-batches skipped (missing RPC URL)",
        )
        return 0

    now = datetime.now(tz=UTC)
    use_relayer = bool(runtime.settings.lock_batches_use_relayer and runtime.settings.relayer_base_url)
    relayer_address: str | None = None
    if use_relayer:
        relayer_address = await _fetch_relayer_address(str(runtime.settings.relayer_base_url))

    account = None
    signer = runtime.settings.settlement_signer_private_key
    if signer is not None:
        account = Account.from_key(signer.get_secret_value())
    if not use_relayer and account is None:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.lock_batches.disabled",
            message="lock-batches skipped (missing signer)",
        )
        return 0

    web3 = get_async_web3(str(runtime.settings.rpc_url))
    submitted = 0
    max_submissions = runtime.settings.lock_batches_max_per_tick
    page_size = max(max_submissions, 5)
    after_closes_at: datetime | None = None
    after_id: int | None = None
    async with session_scope() as session:
        while submitted < max_submissions:
            candidates = await _list_lock_candidates(
                session,
                now=now,
                limit=page_size,
                after_closes_at=after_closes_at,
                after_id=after_id,
            )
            if not candidates:
                break
            for market in candidates:
                after_closes_at = market.closes_at
                after_id = market.id
                if submitted >= max_submissions:
                    break
                retry_key = failure_key("reveal_market_worker:lock_batches:fail", market.id)
                if not await should_attempt(redis_client, retry_key):
                    continue
                if not market.market_address:
                    continue
                use_relayer_for_market = use_relayer
                try:
                    snapshot = await _fetch_onchain_snapshot(web3, market.market_address)
                except Exception as exc:  # pragma: no cover - network error
                    log_event(
                        logger,
                        logging.WARNING,
                        event="worker.lock_batches.chain_fetch_failed",
                        message="failed to fetch on-chain market state",
                        market_id=getattr(market, "event_id", None),
                        error=str(exc),
                    )
                    LOCK_BATCHES_COUNTER.labels(outcome="chain_fetch_failed").inc()
                    await record_failure(
                        redis_client,
                        retry_key,
                        base_seconds=runtime.settings.lock_batches_failure_base_seconds,
                        max_seconds=runtime.settings.lock_batches_failure_max_seconds,
                        max_attempts=runtime.settings.lock_batches_failure_max_attempts,
                        logger=logger,
                        event="worker.lock_batches.retry_scheduled",
                        message="lock-batches retry scheduled after chain fetch failure",
                        reason="chain_fetch_failed",
                    )
                    continue

                phase_value = snapshot.get("phase")
                if phase_value is None or int(phase_value) != 0:
                    settlement = await shared_repository.get_settlement_by_market_id(session, market.id)
                    if settlement is None or settlement_needs_refresh(settlement):
                        await _upsert_settlement_from_chain(session, market, force=True)
                    continue

                commit_deadline = snapshot.get("commit_deadline")
                if commit_deadline is not None and int(commit_deadline) > int(time.time()):
                    continue

                onchain_commitments = snapshot.get("commitments_count")
                if onchain_commitments is not None and int(onchain_commitments) <= 0:
                    LOCK_BATCHES_COUNTER.labels(outcome="no_commitments").inc()
                    continue

                oracle_address = snapshot.get("oracle")
                if account is not None and oracle_address:
                    if account.address.lower() != str(oracle_address).lower():
                        log_event(
                            logger,
                            logging.WARNING,
                            event="worker.lock_batches.oracle_mismatch",
                            message="settlement signer does not match on-chain oracle",
                            market_id=getattr(market, "event_id", None),
                            oracle=oracle_address,
                            signer=account.address,
                        )
                        LOCK_BATCHES_COUNTER.labels(outcome="oracle_mismatch").inc()
                        await record_failure(
                            redis_client,
                            retry_key,
                            base_seconds=runtime.settings.lock_batches_failure_base_seconds,
                            max_seconds=runtime.settings.lock_batches_failure_max_seconds,
                            max_attempts=runtime.settings.lock_batches_failure_max_attempts,
                            logger=logger,
                            event="worker.lock_batches.retry_scheduled",
                            message="lock-batches retry scheduled after oracle mismatch",
                            reason="oracle_mismatch",
                        )
                        continue

                if use_relayer_for_market and relayer_address and oracle_address:
                    if relayer_address.lower() != str(oracle_address).lower():
                        log_event(
                            logger,
                            logging.WARNING,
                            event="worker.lock_batches.relayer_mismatch",
                            message="relayer address does not match on-chain oracle",
                            market_id=getattr(market, "event_id", None),
                            oracle=oracle_address,
                            relayer=relayer_address,
                        )
                        LOCK_BATCHES_COUNTER.labels(outcome="relayer_mismatch").inc()
                        if account is None:
                            await record_failure(
                                redis_client,
                                retry_key,
                                base_seconds=runtime.settings.lock_batches_failure_base_seconds,
                                max_seconds=runtime.settings.lock_batches_failure_max_seconds,
                                max_attempts=runtime.settings.lock_batches_failure_max_attempts,
                                logger=logger,
                                event="worker.lock_batches.retry_scheduled",
                                message="lock-batches retry scheduled after relayer mismatch",
                                reason="relayer_mismatch",
                            )
                            continue
                        use_relayer_for_market = False

                commitments = await shared_repository.list_commitments_by_market(session, market.id)
                if not commitments:
                    LOCK_BATCHES_COUNTER.labels(outcome="no_commitments").inc()
                    await record_failure(
                        redis_client,
                        retry_key,
                        base_seconds=runtime.settings.lock_batches_failure_base_seconds,
                        max_seconds=runtime.settings.lock_batches_failure_max_seconds,
                        max_attempts=runtime.settings.lock_batches_failure_max_attempts,
                        logger=logger,
                        event="worker.lock_batches.retry_scheduled",
                        message="lock-batches retry scheduled after missing commitments",
                        reason="no_commitments",
                    )
                    continue
                try:
                    batch_roots, batch_counts, total_count, _merkle_root = _build_batch_roots_from_commitments(
                        commitments
                    )
                except LockBatchDataError as exc:
                    log_event(
                        logger,
                        logging.WARNING,
                        event="worker.lock_batches.invalid_commitments",
                        message="commitments incomplete for lock-batches",
                        market_id=getattr(market, "event_id", None),
                        error=str(exc),
                    )
                    LOCK_BATCHES_COUNTER.labels(outcome="invalid_commitments").inc()
                    await record_failure(
                        redis_client,
                        retry_key,
                        base_seconds=runtime.settings.lock_batches_failure_base_seconds,
                        max_seconds=runtime.settings.lock_batches_failure_max_seconds,
                        max_attempts=runtime.settings.lock_batches_failure_max_attempts,
                        logger=logger,
                        event="worker.lock_batches.retry_scheduled",
                        message="lock-batches retry scheduled after invalid commitments",
                        reason=str(exc),
                    )
                    continue

                if onchain_commitments is not None and int(onchain_commitments) != total_count:
                    log_event(
                        logger,
                        logging.WARNING,
                        event="worker.lock_batches.commitment_mismatch",
                        message="commitment count mismatch between DB and chain",
                        market_id=getattr(market, "event_id", None),
                        onchain=int(onchain_commitments),
                        local=total_count,
                    )
                    LOCK_BATCHES_COUNTER.labels(outcome="commitment_mismatch").inc()
                    await record_failure(
                        redis_client,
                        retry_key,
                        base_seconds=runtime.settings.lock_batches_failure_base_seconds,
                        max_seconds=runtime.settings.lock_batches_failure_max_seconds,
                        max_attempts=runtime.settings.lock_batches_failure_max_attempts,
                        logger=logger,
                        event="worker.lock_batches.retry_scheduled",
                        message="lock-batches retry scheduled after commitment mismatch",
                        reason="commitment_mismatch",
                    )
                    continue
                if use_relayer_for_market:
                    missing_meta = [
                        commitment.id
                        for commitment in commitments
                        if not commitment.user_address
                        or not commitment.salt
                        or not commitment.leaf
                        or commitment.leaf_index is None
                        or not getattr(commitment, "payout_wei", 0)
                    ]
                    if missing_meta:
                        log_event(
                            logger,
                            logging.WARNING,
                            event="worker.lock_batches.missing_metadata",
                            message="commitments missing metadata required for relayer lock",
                            market_id=getattr(market, "event_id", None),
                            missing_commitment_ids=missing_meta,
                        )
                        LOCK_BATCHES_COUNTER.labels(outcome="missing_metadata").inc()
                        if account is None:
                            await record_failure(
                                redis_client,
                                retry_key,
                                base_seconds=runtime.settings.lock_batches_failure_base_seconds,
                                max_seconds=runtime.settings.lock_batches_failure_max_seconds,
                                max_attempts=runtime.settings.lock_batches_failure_max_attempts,
                                logger=logger,
                                event="worker.lock_batches.retry_scheduled",
                                message="lock-batches retry scheduled after missing relayer metadata",
                                reason="missing_metadata",
                            )
                            continue
                        use_relayer_for_market = False

                try:
                    tx_hash = None
                    block_number = None
                    if use_relayer_for_market and runtime.settings.relayer_base_url:
                        headers = {}
                        if runtime.settings.relayer_bearer_token:
                            headers["Authorization"] = f"Bearer {runtime.settings.relayer_bearer_token}"
                        if runtime.settings.relayer_internal_secret:
                            headers["X-Internal-Secret"] = runtime.settings.relayer_internal_secret.get_secret_value()
                        ticket_payloads = []
                        for commitment in commitments:
                            if not commitment.user_address or not commitment.salt:
                                raise LockBatchDataError("missing_ticket_metadata")
                            if commitment.leaf_index is None:
                                raise LockBatchDataError("missing_leaf_index")
                            ticket_payloads.append(
                                {
                                    "ticket_id": int(commitment.leaf_index),
                                    "outcome_id": int(commitment.outcome_id),
                                    "amount": int(commitment.amount_wei),
                                    "payout": int(commitment.payout_wei),
                                    "user": commitment.user_address,
                                    "salt": commitment.salt,
                                    "leaf": commitment.leaf,
                                }
                            )
                        payload = {
                            "market": market.market_address,
                            "event_id": market.event_id,
                            "market_id": market.event_id,
                            "tickets": ticket_payloads,
                        }
                        result = await _call_relayer_lock_batches(
                            relayer_base_url=str(runtime.settings.relayer_base_url),
                            payload=payload,
                            headers=headers,
                            poll_seconds=runtime.settings.lock_batches_relayer_poll_seconds,
                            max_attempts=runtime.settings.lock_batches_relayer_max_attempts,
                        )
                        if result is None:
                            raise RuntimeError("relayer_lock_batches_timeout")
                        status_value = str(result.get("status") or "").lower()
                        if status_value in {"failed", "deadletter"}:
                            raise RuntimeError(f"relayer_lock_batches_{status_value}")
                        tx_hash = result.get("txHash") or result.get("tx_hash")
                        if not tx_hash:
                            raise RuntimeError("relayer_lock_batches_missing_tx")
                    else:
                        if account is None:
                            continue
                        tx_hash, block_number = await _submit_lock_batches(
                            web3, account, market.market_address, batch_roots, batch_counts
                        )
                    log_event(
                        logger,
                        logging.INFO,
                        event="worker.lock_batches.submitted",
                        message="submitted lockBatches",
                        market_id=getattr(market, "event_id", None),
                        tx_hash=tx_hash,
                        block_number=block_number,
                        batch_count=len(batch_roots),
                    )
                    settlement = await _upsert_settlement_from_chain(session, market, force=True)
                    if settlement is None:
                        settlement = await shared_repository.upsert_settlement_snapshot(
                            session,
                            market.id,
                            {
                                "batch_roots": batch_roots,
                                "batch_counts": batch_counts,
                                "commitments_count": total_count,
                                "circuit_hash": snapshot.get("circuit_hash"),
                                "merkle_root": batch_roots[0] if len(batch_roots) == 1 else None,
                            },
                        )
                    if market.status == shared_models.MarketStatusEnum.COMMIT.value:
                        market.status = shared_models.MarketStatusEnum.LOCKED.value
                    if market.commits_blocked_at is None:
                        market.commits_blocked_at = now
                    session.add(market)
                    submitted += 1
                    if getattr(market, "event_id", None):
                        summary.changed_events.add(market.event_id)
                    LOCK_BATCHES_COUNTER.labels(outcome="submitted").inc()
                    await clear_failure(redis_client, retry_key)
                except Exception as exc:  # pragma: no cover - defensive
                    log_event(
                        logger,
                        logging.WARNING,
                        event="worker.lock_batches.failed",
                        message="lockBatches submission failed",
                        market_id=getattr(market, "event_id", None),
                        error=str(exc),
                    )
                    LOCK_BATCHES_COUNTER.labels(outcome="failed").inc()
                    await record_failure(
                        redis_client,
                        retry_key,
                        base_seconds=runtime.settings.lock_batches_failure_base_seconds,
                        max_seconds=runtime.settings.lock_batches_failure_max_seconds,
                        max_attempts=runtime.settings.lock_batches_failure_max_attempts,
                        logger=logger,
                        event="worker.lock_batches.retry_scheduled",
                        message="lock-batches retry scheduled after submission failure",
                        reason=str(exc),
                    )
                    continue
                await session.flush()
    summary.lock_batches_submitted += submitted
    return submitted


async def _build_merkle_proof_for_commitment(
    session: AsyncSession,
    market_db_id: int,
    settlement: shared_models.Settlement,
    commitment: shared_models.Commitment,
) -> list[str]:
    """Return stored merkle path or recompute from existing leaves."""

    path_rows = list(
        (
            await session.execute(
                select(shared_models.CommitmentMerklePath)
                .where(shared_models.CommitmentMerklePath.commitment_id == commitment.id)
                .order_by(shared_models.CommitmentMerklePath.level.asc())
            )
        ).scalars()
    )
    siblings = [row.sibling_hash for row in path_rows] if path_rows else []
    if siblings:
        return siblings

    batch_roots = _parse_json_list(getattr(settlement, "batch_roots", None))
    batch_counts = _parse_json_list(getattr(settlement, "batch_counts", None))
    if not batch_roots and settlement.merkle_root and not _is_empty_hex(settlement.merkle_root):
        batch_roots = [settlement.merkle_root]
        batch_counts = [settlement.commitments_count]
    if not batch_roots or not batch_counts or len(batch_roots) != len(batch_counts):
        return []
    if commitment.leaf_index is None:
        return []

    batch_index = int(commitment.leaf_index) // BATCH_SIZE
    if batch_index >= len(batch_roots):
        return []
    count_raw = batch_counts[batch_index] if batch_index < len(batch_counts) else None
    try:
        count = int(count_raw or 0)
    except Exception:
        return []
    if count <= 0:
        return []
    index_in_batch = int(commitment.leaf_index) % BATCH_SIZE
    if index_in_batch >= count:
        return []

    commitments = await shared_repository.list_commitments_by_market(session, market_db_id)
    leaves: list[bytes | None] = [None] * count
    for idx, row in enumerate(commitments):
        leaf_bytes = _hex_to_bytes(row.leaf or row.ticket_hash)
        if not leaf_bytes:
            return []
        leaf_index = row.leaf_index if row.leaf_index is not None else idx
        batch_id = int(leaf_index) // BATCH_SIZE
        if batch_id != batch_index:
            continue
        rel_index = int(leaf_index) % BATCH_SIZE
        if rel_index >= count:
            continue
        leaves[rel_index] = leaf_bytes
    if any(leaf is None for leaf in leaves):
        return []
    batch_leaves = cast(list[bytes], leaves)
    try:
        computed_root, paths = build_merkle_root_and_paths(batch_leaves)
        expected_root = bytes.fromhex(str(batch_roots[batch_index]).removeprefix("0x"))
        if computed_root != expected_root:
            return []
        proof = ["0x" + sibling.hex() for sibling in paths[index_in_batch]]
        await shared_repository.replace_merkle_path(session, commitment.id, proof)
        return proof
    except Exception:
        return []


async def _build_relayer_claim_payloads(
    session: AsyncSession, market: shared_models.Market, settlement: shared_models.Settlement
) -> list[dict[str, Any]]:
    """Construct relayer claim payloads for winning commitments."""

    if not market.market_address or settlement.winning_outcome_id is None:
        return []
    winning_outcome = settlement.winning_outcome_id
    payloads: list[dict[str, Any]] = []
    commitments = await shared_repository.list_commitments_by_market(session, market.id)
    for commitment in commitments:
        if commitment.outcome_id != winning_outcome:
            continue
        if commitment.leaf_index is None:
            log_event(
                logger,
                logging.WARNING,
                event="worker.relayer.skip_missing_leaf_index",
                message="skipping relayer claim; commitment missing leaf index",
                market_id=market.event_id,
                commitment_id=getattr(commitment, "id", None),
            )
            continue
        merkle_proof = await _build_merkle_proof_for_commitment(session, market.id, settlement, commitment)
        if not merkle_proof:
            log_event(
                logger,
                logging.WARNING,
                event="worker.relayer.skip_missing_merkle_proof",
                message="skipping relayer claim; merkle proof unavailable",
                market_id=market.event_id,
                commitment_id=getattr(commitment, "id", None),
            )
            continue
        batch_root = _batch_root_for_ticket(settlement, commitment.leaf_index)
        payloads.append(
            {
                "user": commitment.user_address,
                "market": market.market_address,
                "ticket_id": commitment.leaf_index,
                "outcome_id": winning_outcome,
                "amount": int(commitment.amount_wei),
                "salt": commitment.salt or "0x0",
                "merkle_proof": merkle_proof,
                "merkle_root": batch_root,
                "commitments_count": settlement.commitments_count,
                "batch_roots": getattr(settlement, "batch_roots", None),
                "batch_counts": getattr(settlement, "batch_counts", None),
                "pool_total_yes": settlement.pool_total_yes,
                "pool_total_no": settlement.pool_total_no,
                "total_escrow": settlement.total_escrow,
                "total_liability": settlement.total_liability,
                "rake_bps": settlement.rake_bps,
                "proof_request_id": settlement.proof_request_id,
                "event_id": market.event_id,
            }
        )
    return payloads


async def _enqueue_relayer_claims(
    redis_client: Redis | None, market: shared_models.Market, settlement: shared_models.Settlement
) -> int:
    """Queue relayer claim jobs for the given market using the relayer Redis queue."""

    if redis_client is None or not runtime.settings.relayer_queue_enabled or not runtime.settings.relayer_base_url:
        return 0
    try:
        async with session_scope() as session:
            payloads = await _build_relayer_claim_payloads(session, market, settlement)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="worker.relayer.payload_failed",
            message="failed to build relayer claim payloads",
            error=str(exc),
        )
        RELAYER_QUEUE_COUNTER.labels(outcome="error").inc()
        return 0
    if not payloads:
        return 0
    endpoint = str(runtime.settings.relayer_base_url).rstrip("/") + "/claim"
    enqueued = 0
    now = int(datetime.now(tz=UTC).timestamp())
    for payload in payloads:
        job_id = secrets.token_hex(16)
        body = {
            "job_id": job_id,
            "kind": "claim",
            "endpoint": endpoint,
            "payload": payload,
            "attempts": 0,
            "enqueued_at": now,
        }
        try:
            await cast(Awaitable[Any], redis_client.lpush(runtime.settings.relayer_queue_key, json.dumps(body)))
            enqueued += 1
        except Exception as exc:  # pragma: no cover - redis failures are non-fatal
            log_event(
                logger,
                logging.WARNING,
                event="worker.relayer.enqueue_failed",
                message="failed to enqueue relayer claim job",
                market_id=getattr(market, "event_id", None),
                error=str(exc),
            )
            RELAYER_QUEUE_COUNTER.labels(outcome="error").inc()
            continue
    if enqueued:
        RELAYER_QUEUE_COUNTER.labels(outcome="queued").inc(enqueued)
        log_event(
            logger,
            logging.INFO,
            event="worker.relayer.claims_enqueued",
            message="queued relayer claim jobs",
            count=enqueued,
            market_id=getattr(market, "event_id", None),
        )
    return enqueued


async def run_settlement_jobs(summary, redis_client: Redis | None, market_id: str | None = None) -> int:
    """Submit settlement proofs on-chain for markets with generated proofs and no tx hash."""

    relayer_enabled = bool(runtime.settings.relayer_queue_enabled and runtime.settings.relayer_base_url)
    signer_secret = runtime.settings.settlement_signer_private_key
    rpc_url = str(runtime.settings.settlement_rpc_url or runtime.settings.rpc_url or "")
    if signer_secret is None or not rpc_url:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.settlement.tx.unavailable",
            message="settlement tx unavailable (missing signer or rpc)",
        )
        return 0
    account = None
    web3: AsyncWeb3 | None = None
    try:
        account = Account.from_key(signer_secret.get_secret_value())
        web3 = get_async_web3(rpc_url)
    except Exception as exc:  # pragma: no cover - config error
        log_event(
            logger,
            logging.WARNING,
            event="worker.settlement.tx.signer_error",
            message="failed to load settlement signer",
            error=str(exc),
        )
        return 0

    submitted = 0
    dirty_events: set[str] = set()
    dirty_conditions: set[str] = set()
    retry_prefix = "reveal_market_worker:settlement_submit:fail"
    processing_stale_seconds = max(int(runtime.settings.settlement_submission_processing_stale_seconds), 0)
    async with session_scope() as session:
        pending = await shared_repository.list_settlements_pending_tx(
            session,
            market_event_id=market_id,
            include_failed=True,
            processing_stale_seconds=processing_stale_seconds,
        )
        for settlement, market in pending:
            event_id = getattr(market, "event_id", None)
            condition_value = getattr(market, "condition_id", None)
            retry_key = failure_key(retry_prefix, market.id)
            if not await should_attempt(
                redis_client,
                retry_key,
                max_age_seconds=runtime.settings.settlement_submission_failure_max_age_seconds,
                logger=logger,
                event="worker.settlement.retry_expired",
                message="settlement retry window exceeded; skipping submission",
            ):
                continue

            def _mark_dirty(eid: str | None = event_id, cond_val: str | None = condition_value) -> None:
                if eid:
                    dirty_events.add(eid)
                    summary.changed_events.add(eid)
                if isinstance(cond_val, str) and cond_val:
                    normalized = cond_val.lower()
                    dirty_conditions.add(normalized)
                    summary.changed_conditions.add(normalized)

            async def _mark_failure(
                reason: str,
                settlement_entry: shared_models.Settlement = settlement,
                retry_key_value: str = retry_key,
            ) -> None:
                settlement_entry.submission_status = shared_models.SettlementSubmissionStatus.FAILED.value
                settlement_entry.submission_error = reason
                _mark_dirty()
                session.add(settlement_entry)
                await record_failure(
                    redis_client,
                    retry_key_value,
                    base_seconds=runtime.settings.settlement_submission_failure_base_seconds,
                    max_seconds=runtime.settings.settlement_submission_failure_max_seconds,
                    max_attempts=runtime.settings.settlement_submission_failure_max_attempts,
                    logger=logger,
                    event="worker.settlement.retry_scheduled",
                    message="settlement submission retry scheduled after failure",
                    reason=reason,
                )

            lock_token, lock_key = await _acquire_settlement_submission_lock(redis_client, market.id)
            if redis_client is not None and lock_token is None:
                continue
            try:
                if not market.market_address:
                    continue
                winning_outcome_id = settlement.winning_outcome_id
                if winning_outcome_id is None:
                    winning_outcome_id = await _resolve_winning_outcome(session, market)
                if winning_outcome_id is None:
                    continue
                oracle_addr = None
                if account is not None and web3 is not None:
                    try:
                        oracle_addr = (
                            await _build_market_contract(web3, market.market_address).functions.oracle().call()
                        )
                    except Exception as exc:  # pragma: no cover - defensive
                        log_event(
                            logger,
                            logging.WARNING,
                            event="worker.settlement.oracle_check_failed",
                            message="failed to check oracle address",
                            market_id=getattr(market, "event_id", None),
                            error=str(exc),
                        )
                        oracle_addr = None
                if oracle_addr and account.address.lower() != str(oracle_addr).lower():
                    log_event(
                        logger,
                        logging.WARNING,
                        event="worker.settlement.oracle_mismatch",
                        message="settlement signer does not match oracle",
                        market_id=getattr(market, "event_id", None),
                        oracle=oracle_addr,
                        signer=account.address,
                    )
                    await _mark_failure("oracle_mismatch")
                    continue
                batch_roots = _parse_json_list(getattr(settlement, "batch_roots", None))
                if not batch_roots and _is_empty_hex(settlement.merkle_root):
                    # hydrate from chain if possible
                    settlement = await _upsert_settlement_from_chain(session, market) or settlement
                    batch_roots = _parse_json_list(getattr(settlement, "batch_roots", None))
                if not batch_roots and settlement.merkle_root and not _is_empty_hex(settlement.merkle_root):
                    batch_roots = [settlement.merkle_root]
                if web3 is None or account is None:
                    await _mark_failure("settlement_tx_unavailable")
                    continue
                settlement.submission_status = shared_models.SettlementSubmissionStatus.PROCESSING.value
                settlement.submission_error = None
                _mark_dirty()
                session.add(settlement)
                await session.commit()
                if not batch_roots:
                    log_event(
                        logger,
                        logging.DEBUG,
                        event="worker.settlement.missing_roots",
                        message="skipping settlement submission due to missing batch roots",
                        market_id=getattr(market, "event_id", None),
                    )
                    await _mark_failure("missing_batch_roots")
                    continue

                receipts = list(
                    (
                        await session.execute(
                            select(shared_models.SettlementReceipt).where(
                                shared_models.SettlementReceipt.market_id == settlement.market_id
                            )
                        )
                    ).scalars()
                )
                receipt_by_root: dict[str, shared_models.SettlementReceipt] = {}
                for receipt in receipts:
                    if not receipt.proof or not receipt.public_signals:
                        continue
                    signals = receipt.public_signals
                    if isinstance(signals, (list, tuple)) and signals:
                        root_signal = str(signals[0])
                        receipt_by_root.setdefault(root_signal, receipt)

                proofs: list[str] = []
                public_signals_list: list[Sequence[Any]] = []
                batch_indexes: list[int] = []
                for index, root in enumerate(batch_roots):
                    root_signal = _root_to_signal(root)
                    batch_receipt = receipt_by_root.get(root_signal or "")
                    if batch_receipt is None or not batch_receipt.proof or not batch_receipt.public_signals:
                        continue
                    proofs.append(str(batch_receipt.proof))
                    public_signals_list.append(cast(Sequence[Any], batch_receipt.public_signals))
                    batch_indexes.append(index)

                if len(proofs) != len(batch_roots):
                    log_event(
                        logger,
                        logging.DEBUG,
                        event="worker.settlement.missing_proof",
                        message="skipping settlement submission due to missing batch proofs",
                        market_id=getattr(market, "event_id", None),
                    )
                    await _mark_failure("missing_proof_receipt")
                    continue
                try:
                    await _maybe_post_result(
                        web3,
                        account,
                        _build_market_contract(web3, market.market_address),
                        winning_outcome_id,
                    )
                    tx_hash, _ = await _submit_verify_and_settle_batched(
                        web3,
                        account,
                        market.market_address,
                        proofs,
                        public_signals_list,
                        batch_indexes,
                        wait_for_receipt=False,
                    )
                except Exception as exc:  # pragma: no cover - on-chain errors
                    log_event(
                        logger,
                        logging.WARNING,
                        event="worker.settlement.tx_failed",
                        message="failed to submit settlement tx",
                        market_id=getattr(market, "event_id", None),
                        error=str(exc),
                    )
                    await _mark_failure(str(exc))
                    continue

                settlement.settlement_tx_hash = tx_hash
                settlement.settlement_block_number = None
                settlement.settlement_submitted_at = datetime.now(tz=UTC)
                settlement.submission_status = shared_models.SettlementSubmissionStatus.SUBMITTED.value
                settlement.submission_error = None
                _mark_dirty()
                session.add(settlement)
                # Persist tx hash before waiting on receipt so restarts don't replay PROCESSING rows.
                await session.commit()
                log_event(
                    logger,
                    logging.INFO,
                    event="worker.settlement.tx_checkpointed",
                    message="checkpointed settlement tx before receipt wait",
                    market_id=getattr(market, "event_id", None),
                    tx_hash=tx_hash,
                )
                try:
                    block_number = await _wait_for_submission_receipt(
                        web3,
                        tx_hash,
                        action="verify_and_settle_batched",
                    )
                except Exception as exc:
                    settlement.submission_status = shared_models.SettlementSubmissionStatus.FAILED.value
                    settlement.submission_error = f"receipt_wait_failed:{exc}"
                    _mark_dirty()
                    session.add(settlement)
                    await session.commit()
                    log_event(
                        logger,
                        logging.WARNING,
                        event="worker.settlement.receipt_wait_failed",
                        message="receipt wait failed after settlement broadcast",
                        market_id=getattr(market, "event_id", None),
                        tx_hash=tx_hash,
                        error=str(exc),
                    )
                    continue

                settlement.settlement_block_number = block_number
                settlement.submission_error = None
                _mark_dirty()
                session.add(settlement)
                await session.commit()
                await clear_failure(redis_client, retry_key)
                submitted += 1
                log_event(
                    logger,
                    logging.INFO,
                    event="worker.settlement.tx_submitted",
                    message="submitted verifyAndSettleBatched",
                    market_id=getattr(market, "event_id", None),
                    tx_hash=tx_hash,
                    block_number=block_number,
                )
                if relayer_enabled:
                    enqueued = await _enqueue_relayer_claims(redis_client, market, settlement)
                    submitted += enqueued
            finally:
                await _release_settlement_submission_lock(
                    redis_client,
                    lock_key=lock_key,
                    lock_token=lock_token,
                )
        await session.flush()
    if dirty_events or dirty_conditions:
        await invalidate_cache_tags(redis_client, summary)
    return submitted
