"""Settlement proof orchestration and persistence helpers."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from collections.abc import Awaitable
from typing import Any, TypeVar, cast

from redis.asyncio import Redis
from shared import cache_async as shared_cache
from shared import models as shared_models
from shared import repository_async as shared_repository
from shared.cache_keys import proof_receipt_cache_key
from shared.logging import log_event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import runtime
from .cache_ops import invalidate_cache_tags
from .database import session_scope
from .market_sync import SyncSummary
from .metrics import (
    PROOF_QUEUE_AGE_GAUGE,
    PROOF_QUEUE_DEPTH_GAUGE,
    PROOF_QUEUE_DLQ_COUNTER,
    PROOF_QUEUE_OVERFLOW_COUNTER,
    SETTLEMENT_QUEUE_DEPTH_GAUGE,
    SETTLEMENT_QUEUE_DLQ_COUNTER,
)
from .polymarket import MarketPayload
from .proof_builder import SettlementDataMissingError, build_prover_payload_async
from .prover_client import ProverError
from .retry import clear_failure, failure_key, record_failure, should_attempt
from .settlement import _upsert_settlement_from_chain, run_settlement_jobs

logger = runtime.logger  # type: ignore[has-type]
T = TypeVar("T")
_PROVER_HEALTH_CACHE_SECONDS = 60.0
_PROVER_CIRCUIT_CACHE: dict[str, Any] = {"value": None, "expires_at": 0.0}


async def _resolve_awaitable[T](value: Awaitable[T] | T) -> T:
    """Handle Redis' async-or-pipeline return types safely for mypy."""

    if inspect.isawaitable(value):
        return cast(T, await value)
    return cast(T, value)


def _normalize_hex(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        cleaned = value.hex()
    else:
        cleaned = str(value).strip().lower()
        if cleaned.startswith("0x"):
            cleaned = cleaned[2:]
    if not cleaned:
        return None
    return cleaned


async def _get_prover_circuit_hash() -> str | None:
    client = runtime.PROVER_CLIENT
    if client is None:
        return None
    fetch_health = getattr(client, "fetch_health", None)
    if fetch_health is None:
        return None
    now = time.monotonic()
    cached = _PROVER_CIRCUIT_CACHE.get("value")
    if cached and now < float(_PROVER_CIRCUIT_CACHE.get("expires_at", 0.0) or 0.0):
        return str(cached)
    try:
        payload = await fetch_health()
    except Exception as exc:  # pragma: no cover - best-effort guard
        log_event(
            logger,
            logging.DEBUG,
            event="worker.proof.health_failed",
            message="failed to fetch prover health payload",
            error=str(exc),
        )
        return None
    circuit_hash = payload.get("circuit_hash") or payload.get("circuitHash") or payload.get("circuit")
    if circuit_hash:
        _PROVER_CIRCUIT_CACHE["value"] = str(circuit_hash)
        _PROVER_CIRCUIT_CACHE["expires_at"] = now + _PROVER_HEALTH_CACHE_SECONDS
        return str(circuit_hash)
    return None


async def validate_prover_circuit_hash() -> None:
    """Validate prover circuit hash matches configured chain hash (if present)."""

    expected = runtime.settings.circuit_hash
    if not expected or runtime.PROVER_CLIENT is None:
        return
    actual = await _get_prover_circuit_hash()
    if not actual:
        raise RuntimeError("prover_circuit_hash_missing")
    expected_norm = _normalize_hex(expected)
    actual_norm = _normalize_hex(actual)
    if expected_norm != actual_norm:
        raise RuntimeError("prover_circuit_hash_mismatch")


def _queue_keys() -> tuple[str, str]:
    return (
        runtime.settings.proof_queue_key,
        runtime.settings.proof_queue_dedupe_key,
    )


def _settlement_queue_keys() -> tuple[str, str]:
    return (
        runtime.settings.settlement_queue_key,
        runtime.settings.settlement_queue_dead_letter_key,
    )


async def _invalidate_market_cache(redis_client: Redis | None, event_id: str | None, condition_id: str | None) -> None:
    if redis_client is None:
        return
    summary = SyncSummary()
    if event_id:
        summary.changed_events.add(str(event_id))
    if condition_id:
        summary.changed_conditions.add(str(condition_id).lower())
    await invalidate_cache_tags(redis_client, summary)


async def _update_queue_depth(redis_client: Redis | None) -> None:
    if redis_client is None:
        return
    queue_key, _ = _queue_keys()
    try:
        depth = await _resolve_awaitable(redis_client.llen(queue_key))
        depth_value = int(depth or 0)
        PROOF_QUEUE_DEPTH_GAUGE.labels(queue=queue_key).set(float(depth_value))
        if depth_value == 0:
            PROOF_QUEUE_AGE_GAUGE.labels(queue=queue_key).set(0.0)
            return
        head = await _resolve_awaitable(redis_client.lindex(queue_key, 0))
        if not head:
            return
        payload = json.loads(head)
        if not isinstance(payload, dict):
            return
        enqueued_at = payload.get("enqueued_at")
        if not enqueued_at:
            return
        age_seconds = max(0.0, time.time() - float(enqueued_at))
        PROOF_QUEUE_AGE_GAUGE.labels(queue=queue_key).set(age_seconds)
    except Exception:  # pragma: no cover - metrics best-effort
        return


async def _dead_letter(redis_client: Redis, job: dict[str, Any], reason: str) -> None:
    """Push a failed job to dead letter list for inspection."""

    try:
        key = runtime.settings.proof_queue_dead_letter_key
        payload = json.dumps(job, default=str)
        await _resolve_awaitable(redis_client.rpush(key, payload))
        max_items = runtime.settings.proof_queue_dead_letter_max_items
        if max_items > 0:
            await _resolve_awaitable(redis_client.ltrim(key, max(-max_items, -1), -1))
        ttl_seconds = runtime.settings.proof_queue_dead_letter_ttl_seconds
        if ttl_seconds > 0:
            await _resolve_awaitable(redis_client.expire(key, ttl_seconds))
        PROOF_QUEUE_DLQ_COUNTER.labels(reason=reason).inc()
    except Exception:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.DEBUG,
            event="worker.proof.queue_dlq_failed",
            message="failed to dead-letter proof job",
            reason=reason,
        )


async def _settlement_dead_letter(redis_client: Redis, job: dict[str, Any], reason: str) -> None:
    try:
        key = runtime.settings.settlement_queue_dead_letter_key
        payload = json.dumps(job, default=str)
        await _resolve_awaitable(redis_client.rpush(key, payload))
        max_items = runtime.settings.settlement_queue_dead_letter_max_items
        if max_items > 0:
            await _resolve_awaitable(redis_client.ltrim(key, max(-max_items, -1), -1))
        ttl_seconds = runtime.settings.settlement_queue_dead_letter_ttl_seconds
        if ttl_seconds > 0:
            await _resolve_awaitable(redis_client.expire(key, ttl_seconds))
        SETTLEMENT_QUEUE_DLQ_COUNTER.labels(reason=reason).inc()
    except Exception:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.DEBUG,
            event="worker.settlement.queue_dlq_failed",
            message="failed to dead-letter settlement job",
            reason=reason,
        )


async def enqueue_proof_jobs(redis_client: Redis | None, summary: SyncSummary) -> int:
    """Store proof jobs in Redis so background workers can process them without blocking ingestion."""

    if redis_client is None:
        return 0
    queue_key, dedupe_key = _queue_keys()
    enqueued = 0
    lua = (
        "local depth = redis.call('LLEN', KEYS[1]); "
        "if depth >= tonumber(ARGV[1]) then return 0 end; "
        "local added = redis.call('SADD', KEYS[2], ARGV[2]); "
        "if added == 0 then return -1 end; "
        "redis.call('RPUSH', KEYS[1], ARGV[3]); return 1;"
    )
    if not hasattr(redis_client, "eval"):
        log_event(
            logger,
            logging.WARNING,
            event="worker.proof.queue_eval_missing",
            message="redis client does not support eval; skipping proof enqueue to avoid race",
        )
        return 0
    for snapshot, payload, condition in summary.proof_jobs:
        job_id = str(
            snapshot.get("market_address")
            or snapshot.get("id")
            or snapshot.get("market_id")
            or snapshot.get("event_id")
            or condition
            or "",
        )
        if not job_id:
            continue
        job = {
            "job_id": job_id,
            "market_snapshot": snapshot,
            "market_payload": payload.model_dump(),
            "condition_id": condition,
            "enqueued_at": time.time(),
        }
        try:
            result = await _resolve_awaitable(
                redis_client.eval(
                    lua,
                    2,
                    queue_key,
                    dedupe_key,
                    str(runtime.settings.proof_queue_max_depth),
                    job_id,
                    json.dumps(job, default=str),
                )
            )
            if int(result or 0) == 1:
                enqueued += 1
                try:
                    await _resolve_awaitable(
                        redis_client.expire(dedupe_key, int(runtime.settings.proof_queue_dedupe_ttl_seconds))
                    )
                except Exception as exc:
                    log_event(
                        logger,
                        logging.DEBUG,
                        event="worker.proof.queue_dedupe_ttl_failed",
                        message="failed to set proof queue dedupe TTL",
                        dedupe_key=dedupe_key,
                        error=str(exc),
                    )
            elif int(result or 0) == 0:
                PROOF_QUEUE_OVERFLOW_COUNTER.labels(outcome="skipped").inc()
            else:
                continue
        except Exception as exc:  # pragma: no cover - enqueue best-effort
            log_event(
                logger,
                logging.WARNING,
                event="worker.proof.queue_enqueue_failed",
                message="failed to enqueue proof job",
                job_id=job_id,
                error=str(exc),
            )
    await _update_queue_depth(redis_client)
    return enqueued


async def _persist_settlement_snapshot(session: AsyncSession, market_id: int, snapshot: dict[str, Any]) -> None:
    """Write settlement + commitment data to the ledger tables for durability."""

    def _as_int(value: Any) -> int | None:
        try:
            return int(value)
        except Exception:
            return None

    settlement_fields = {
        "merkle_root": snapshot.get("merkleRoot") or snapshot.get("commitments_root"),
        "commitments_count": _as_int(snapshot.get("commitmentsCount") or snapshot.get("commitments_count")),
        "batch_roots": snapshot.get("batchRoots") or snapshot.get("batch_roots"),
        "batch_counts": snapshot.get("batchCounts") or snapshot.get("batch_counts"),
        "pool_total_yes": _as_int(snapshot.get("poolTotalYes") or (snapshot.get("poolTotals") or [None, None])[0]),
        "pool_total_no": _as_int(snapshot.get("poolTotalNo") or (snapshot.get("poolTotals") or [None, None])[-1]),
        "total_escrow": _as_int(snapshot.get("totalEscrow") or snapshot.get("total_escrow")),
        "total_liability": _as_int(snapshot.get("totalLiability") or snapshot.get("total_liability")),
        "rake_bps": _as_int(snapshot.get("rakeBps") or snapshot.get("rake_bps")),
        "winning_outcome_id": _as_int(snapshot.get("winningOutcomeId") or snapshot.get("winning_outcome_id")),
        "circuit_hash": snapshot.get("circuitHash") or snapshot.get("circuit_hash"),
    }
    settlement_payload = {k: v for k, v in settlement_fields.items() if v not in (None, "")}
    if settlement_payload:
        await shared_repository.upsert_settlement_snapshot(session, market_id, settlement_payload)

    tickets = snapshot.get("tickets") or []
    if tickets:
        try:
            await shared_repository.record_commitments(session, market_id, tickets)
        except Exception as exc:  # pragma: no cover - durability best-effort
            log_event(
                logger,
                logging.WARNING,
                event="worker.commitment.persist_failed",
                message="failed to persist commitments snapshot",
                market_id=market_id,
                error=str(exc),
            )


def _build_snapshot_payload(
    market_snapshot: dict[str, Any], market_payload: MarketPayload, market_id: str | int
) -> dict[str, Any] | None:
    """Build a prover payload directly from an in-memory market snapshot when DB state is incomplete."""

    required_fields = [
        "commitments_root",
        "pool_totals",
        "total_escrow",
        "total_liability",
        "rake_bps",
        "winning_outcome_id",
        "circuit_hash",
    ]
    for key in required_fields:
        if key not in market_snapshot or market_snapshot[key] in (None, ""):
            return None

    return {
        "marketId": str(market_id),
        "merkleRoot": market_snapshot["commitments_root"],
        "winningOutcomeId": market_snapshot["winning_outcome_id"],
        "poolTotals": [str(x) for x in market_snapshot.get("pool_totals", [])],
        "totalEscrow": str(market_snapshot["total_escrow"]),
        "totalLiability": str(market_snapshot["total_liability"]),
        "rakeBps": str(market_snapshot.get("rake_bps", 0)),
        "circuitHash": market_snapshot["circuit_hash"],
        "batchRoots": market_snapshot.get("batch_roots") or market_snapshot.get("batchRoots"),
        "batchCounts": market_snapshot.get("batch_counts") or market_snapshot.get("batchCounts"),
    }


async def run_prover_jobs(summary: SyncSummary, redis_client: Redis | None) -> int:
    """Iterate queued proof jobs and return how many proofs were generated."""
    if runtime.PROVER_CLIENT is None:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.proof.disabled",
            message="skipping proof generation (prover client unavailable)",
        )
        return 0
    proofs_generated = 0
    for snapshot, payload, condition in summary.proof_jobs:
        if await maybe_generate_settlement_proof(
            redis_client,
            market_snapshot=snapshot,
            market_payload=payload,
            condition_id=condition,
        ):
            proofs_generated += 1
    return proofs_generated


async def maybe_generate_settlement_proof(
    redis_client: Redis | None,
    *,
    market_snapshot: dict[str, Any],
    market_payload: MarketPayload,
    condition_id: str | None,
) -> bool:
    """Call the prover service when settlements change so downstream services can audit proofs."""

    if runtime.PROVER_CLIENT is None:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.proof.disabled",
            message="settlement proof generation skipped (prover client unavailable)",
        )
        return False
    if runtime.circuit_breaker and await runtime.circuit_breaker.is_open("prover"):
        log_event(
            logger,
            logging.WARNING,
            event="worker.prover.circuit_open",
            message="prover circuit open; skipping proof generation",
        )
        return False

    def _as_int(value: Any) -> int | None:
        try:
            return int(value)
        except Exception:
            return None

    market_identifier = (
        market_snapshot.get("id")
        or market_snapshot.get("market_id")
        or market_snapshot.get("event_id")
        or market_snapshot.get("condition_id")
        or condition_id
    )
    normalized_condition = (condition_id or market_snapshot.get("condition_id") or None) or None
    if isinstance(normalized_condition, str):
        normalized_condition = normalized_condition.lower()
    market_event_id = market_snapshot.get("event_id")
    market_address = market_snapshot.get("market_address")
    numeric_market_id = _as_int(market_identifier)
    retry_key = failure_key("reveal_market_worker:proof:fail", str(market_identifier))

    if not await should_attempt(
        redis_client,
        retry_key,
        max_age_seconds=runtime.settings.proof_failure_max_age_seconds,
        logger=logger,
        event="worker.proof.retry_expired",
        message="proof retry window exceeded; skipping",
    ):
        return False

    async def _notify_status_change() -> None:
        await _invalidate_market_cache(
            redis_client,
            market_event_id or market_snapshot.get("event_id") or market_payload.event_id,
            normalized_condition or market_snapshot.get("condition_id") or condition_id,
        )

    if market_identifier is None:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.proof.no_market_id",
            message="skipping proof generation due to missing market id",
            event_id=market_snapshot.get("event_id"),
        )
        return False
    payloads: list[dict[str, Any]] | None = None
    try:
        async with session_scope() as session:
            if numeric_market_id is None:
                raise ValueError("non-numeric market id")
            market_record = await session.get(shared_models.Market, numeric_market_id)
            if market_record is None:
                log_event(
                    logger,
                    logging.INFO,
                    event="worker.proof.no_market_record",
                    message="skipping proof because market record missing",
                    market_id=market_identifier,
                )
                return False
            commitments_count = await shared_repository.count_commitments(session, numeric_market_id)
            if commitments_count <= 0:
                return False
            if market_record:
                market_event_id = market_event_id or getattr(market_record, "event_id", None)
                record_condition = getattr(market_record, "condition_id", None)
                if normalized_condition is None and isinstance(record_condition, str):
                    normalized_condition = record_condition.lower()
                if market_address is None:
                    market_address = getattr(market_record, "market_address", None)
            payloads = await build_prover_payload_async(session, numeric_market_id)
            settlement_row = (
                await session.execute(
                    select(shared_models.Settlement).where(shared_models.Settlement.market_id == numeric_market_id)
                )
            ).scalar_one_or_none()
            if settlement_row:
                if settlement_row.proof_status == shared_models.SettlementProofStatus.GENERATED.value:
                    return False
                settlement_row.proof_status = shared_models.SettlementProofStatus.GENERATING.value
                session.add(settlement_row)
            await session.flush()
            await _notify_status_change()
    except (ValueError, SettlementDataMissingError) as exc:
        fallback = _build_snapshot_payload(market_snapshot, market_payload, market_identifier or "")
        if fallback and numeric_market_id is not None:
            try:
                async with session_scope() as session:
                    await _persist_settlement_snapshot(session, numeric_market_id, fallback)
            except Exception as persist_exc:
                log_event(
                    logger,
                    logging.INFO,
                    event="worker.proof.snapshot_persist_failed",
                    message="failed to persist settlement snapshot",
                    error=str(persist_exc),
                    market_id=market_identifier,
                )
        # If a chain snapshot is available, try to hydrate settlement data before giving up.
        if payloads is None and numeric_market_id is not None and runtime.settings.rpc_url:
            try:
                async with session_scope() as session:
                    market_record = await session.get(shared_models.Market, numeric_market_id)
                    if market_record and getattr(market_record, "market_address", None):
                        refreshed = await asyncio.wait_for(
                            _upsert_settlement_from_chain(session, market_record),
                            timeout=max(runtime.settings.chain_refresh_timeout_seconds, 5),
                        )
                        if refreshed is not None:
                            payloads = await build_prover_payload_async(session, numeric_market_id)
                            settlement_row = (
                                await session.execute(
                                    select(shared_models.Settlement).where(
                                        shared_models.Settlement.market_id == numeric_market_id
                                    )
                                )
                            ).scalar_one_or_none()
                            if settlement_row:
                                if settlement_row.proof_status == shared_models.SettlementProofStatus.GENERATED.value:
                                    return False
                                settlement_row.proof_status = shared_models.SettlementProofStatus.GENERATING.value
                                session.add(settlement_row)
                            await session.flush()
                            await _notify_status_change()
            except Exception as refresh_exc:  # pragma: no cover - best-effort hydrate
                log_event(
                    logger,
                    logging.INFO,
                    event="worker.proof.chain_hydrate_failed",
                    message="failed to backfill settlement from chain for proof payload",
                    market_id=market_identifier,
                    error=str(refresh_exc),
                )
        if not payloads:
            log_event(
                logger,
                logging.INFO,
                event="worker.proof.incomplete",
                message="skipping proof generation due to missing settlement fields",
                error=str(exc),
                event_id=market_snapshot.get("event_id"),
                market_id=market_identifier,
                condition_id=normalized_condition,
                missing_fields="winner/roots/totals/circuit_hash",
            )
            await record_failure(
                redis_client,
                retry_key,
                base_seconds=runtime.settings.proof_failure_base_seconds,
                max_seconds=runtime.settings.proof_failure_max_seconds,
                max_attempts=runtime.settings.proof_failure_max_attempts,
                logger=logger,
                event="worker.proof.retry_scheduled",
                message="proof generation retry scheduled after incomplete settlement data",
                reason="missing_settlement_fields",
            )
            if numeric_market_id is not None and runtime.settings.rpc_url:
                try:
                    async with session_scope() as session:
                        market_record = await session.get(shared_models.Market, numeric_market_id)
                        if market_record and getattr(market_record, "market_address", None):
                            await asyncio.wait_for(
                                _upsert_settlement_from_chain(session, market_record, force=True),
                                timeout=max(runtime.settings.chain_refresh_timeout_seconds, 5),
                            )
                            await session.flush()
                except Exception as exc:
                    log_event(
                        logger,
                        logging.DEBUG,
                        event="worker.proof.chain_refresh_failed",
                        message="failed to refresh settlement snapshot during proof retry",
                        market_id=numeric_market_id,
                        error=str(exc),
                    )
            return False
    if not payloads:
        log_event(
            logger,
            logging.INFO,
            event="worker.proof.incomplete",
            message="skipping proof generation due to missing payload",
            event_id=market_snapshot.get("event_id"),
            market_id=market_identifier,
            condition_id=normalized_condition,
            missing_fields="payload",
        )
        await record_failure(
            redis_client,
            retry_key,
            base_seconds=runtime.settings.proof_failure_base_seconds,
            max_seconds=runtime.settings.proof_failure_max_seconds,
            max_attempts=runtime.settings.proof_failure_max_attempts,
            logger=logger,
            event="worker.proof.retry_scheduled",
            message="proof generation retry scheduled after missing payload",
            reason="missing_payload",
        )
        if numeric_market_id is not None and runtime.settings.rpc_url:
            try:
                async with session_scope() as session:
                    market_record = await session.get(shared_models.Market, numeric_market_id)
                    if market_record and getattr(market_record, "market_address", None):
                        await _upsert_settlement_from_chain(session, market_record, force=True)
                        await session.flush()
            except Exception as exc:
                log_event(
                    logger,
                    logging.DEBUG,
                    event="worker.proof.chain_refresh_failed",
                    message="failed to refresh settlement snapshot during proof retry",
                    market_id=numeric_market_id,
                    error=str(exc),
                )
        return False
    first_payload = payloads[0]
    expected_circuit = await _get_prover_circuit_hash()
    if expected_circuit:
        expected_norm = _normalize_hex(expected_circuit)
        payload_norm = _normalize_hex(first_payload.get("circuitHash"))
        if not payload_norm or (expected_norm and payload_norm != expected_norm):
            if numeric_market_id is not None:
                try:
                    async with session_scope() as session:
                        settlement_row = (
                            await session.execute(
                                select(shared_models.Settlement).where(
                                    shared_models.Settlement.market_id == numeric_market_id
                                )
                            )
                        ).scalar_one_or_none()
                        if settlement_row:
                            settlement_row.proof_status = shared_models.SettlementProofStatus.FAILED.value
                            session.add(settlement_row)
                            await session.flush()
                except Exception as status_exc:  # pragma: no cover - defensive status update
                    log_event(
                        logger,
                        logging.WARNING,
                        event="worker.proof.status_update_failed",
                        message="failed to mark settlement proof as failed",
                        error=str(status_exc),
                        market_id=numeric_market_id,
                    )
            log_event(
                logger,
                logging.WARNING,
                event="worker.proof.circuit_hash_mismatch",
                message="prover circuit hash does not match settlement payload",
                expected=expected_circuit,
                actual=first_payload.get("circuitHash"),
                market_id=market_identifier,
            )
            await _notify_status_change()
            await record_failure(
                redis_client,
                retry_key,
                base_seconds=runtime.settings.proof_failure_base_seconds,
                max_seconds=runtime.settings.proof_failure_max_seconds,
                max_attempts=runtime.settings.proof_failure_max_attempts,
                logger=logger,
                event="worker.proof.retry_scheduled",
                message="proof generation retry scheduled after circuit hash mismatch",
                reason="circuit_hash_mismatch",
            )
            return False
    log_event(
        logger,
        logging.DEBUG,
        event="worker.proof.request_ready",
        message="constructed settlement proof request",
        market_id=first_payload.get("marketId"),
        merkle_root=first_payload.get("merkleRoot"),
    )

    results: list[tuple[dict[str, Any], Any, str | None]] = []
    for payload in payloads:
        try:
            response = await runtime.PROVER_CLIENT.generate_settlement_proof(payload)
        except ProverError as exc:
            if runtime.circuit_breaker:
                await runtime.circuit_breaker.record_failure("prover")
            if numeric_market_id is not None:
                try:
                    async with session_scope() as session:
                        settlement_row = (
                            await session.execute(
                                select(shared_models.Settlement).where(
                                    shared_models.Settlement.market_id == numeric_market_id
                                )
                            )
                        ).scalar_one_or_none()
                        if settlement_row:
                            settlement_row.proof_status = shared_models.SettlementProofStatus.FAILED.value
                            session.add(settlement_row)
                except Exception as status_exc:  # pragma: no cover - defensive status update
                    log_event(
                        logger,
                        logging.WARNING,
                        event="worker.proof.status_update_failed",
                        message="failed to mark settlement proof as failed",
                        error=str(status_exc),
                        market_id=numeric_market_id,
                    )
            log_event(
                logger,
                logging.WARNING,
                event="worker.proof.failed",
                message="prover rejected settlement request",
                error=str(exc),
                event_id=market_snapshot.get("event_id"),
            )
            await _notify_status_change()
            await record_failure(
                redis_client,
                retry_key,
                base_seconds=runtime.settings.proof_failure_base_seconds,
                max_seconds=runtime.settings.proof_failure_max_seconds,
                max_attempts=runtime.settings.proof_failure_max_attempts,
                logger=logger,
                event="worker.proof.retry_scheduled",
                message="proof generation retry scheduled after prover error",
                reason=str(exc),
            )
            return False
        else:
            if runtime.circuit_breaker:
                await runtime.circuit_breaker.record_success("prover")

        proof_hash = None
        try:
            from eth_utils import keccak

            proof_hash_source = (response.proof or "") + "".join(response.public_signals or [])
            proof_hash = keccak(proof_hash_source.encode()).hex()
        except Exception:  # pragma: no cover - defensive
            proof_hash = None

        results.append((payload, response, proof_hash))

        cache_payload = {
            **response.to_json(),
            "marketId": payload.get("marketId"),
            "eventId": market_event_id or market_payload.event_id,
            "conditionId": normalized_condition or payload.get("conditionId"),
            "marketAddress": market_address or market_snapshot.get("market_address"),
            "merkleRoot": payload.get("merkleRoot"),
            "poolTotals": payload.get("poolTotals"),
            "totalEscrow": payload.get("totalEscrow"),
            "totalLiability": payload.get("totalLiability"),
            "rakeBps": payload.get("rakeBps"),
            "winningOutcomeId": payload.get("winningOutcomeId"),
            "batchIndex": payload.get("batchIndex"),
            "commitmentsCount": payload.get("commitmentsCount"),
            "proof_hash": f"0x{proof_hash}" if proof_hash else None,
        }
        root_signal = None
        if response.public_signals:
            try:
                root_signal = str(response.public_signals[0])
            except Exception:
                root_signal = None
        cache_key_target = (
            f"root:{root_signal}"
            if root_signal
            else (
                normalized_condition
                or payload.get("conditionId")
                or payload.get("marketId")
                or market_event_id
                or market_identifier
                or ""
            )
        )
        cache_key = proof_receipt_cache_key(str(cache_key_target))
        if redis_client is not None:
            await shared_cache.set_json(
                redis_client,
                cache_key,
                cache_payload,
                runtime.settings.proof_cache_ttl_seconds,
            )

    try:
        async with session_scope() as session:
            market_record = (
                await session.get(shared_models.Market, numeric_market_id) if numeric_market_id is not None else None
            )
            if market_record:
                if market_event_id is None:
                    market_event_id = getattr(market_record, "event_id", None)
                condition_value = getattr(market_record, "condition_id", None)
                if normalized_condition is None and isinstance(condition_value, str):
                    normalized_condition = condition_value.lower()
                if market_address is None:
                    market_address = getattr(market_record, "market_address", None)
            settlement = (
                (
                    await session.execute(
                        select(shared_models.Settlement).where(shared_models.Settlement.market_id == numeric_market_id)
                    )
                ).scalar_one_or_none()
                if numeric_market_id is not None
                else None
            )
            if settlement:
                settlement.proof_status = shared_models.SettlementProofStatus.GENERATED.value
                if len(results) == 1:
                    settlement.proof_request_id = results[0][1].request_id
                    settlement.proof_hash = f"0x{results[0][2]}" if results[0][2] else None
                else:
                    settlement.proof_request_id = None
                    settlement.proof_hash = None
                session.add(settlement)
            if numeric_market_id is not None:
                for _payload, response, proof_hash in results:
                    batch_index = None
                    try:
                        batch_index_raw = _payload.get("batchIndex")
                        if batch_index_raw is not None:
                            batch_index = int(str(batch_index_raw))
                    except (TypeError, ValueError):
                        batch_index = None
                    await shared_repository.record_settlement_receipt(
                        session,
                        market_id=numeric_market_id,
                        market_address=market_address,
                        request_id=response.request_id,
                        proof_hash=f"0x{proof_hash}" if proof_hash else None,
                        proof=response.proof,
                        batch_index=batch_index,
                        public_signals=response.public_signals,
                        prover_version=response.prover_version,
                        circuit_hash=response.circuit_hash,
                        generated_at=response.generated_at,
                    )
    except Exception as exc:  # pragma: no cover - best effort
        log_event(
            logger,
            logging.WARNING,
            event="worker.proof.persist_failed",
            message="failed to persist proof metadata",
            error=str(exc),
            market_id=market_identifier,
        )

    await _notify_status_change()
    await clear_failure(redis_client, retry_key)
    for payload, response, _proof_hash in results:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.proof.generated",
            message="cached settlement proof receipt",
            event_id=market_event_id,
            condition_id=normalized_condition or condition_id or market_snapshot.get("condition_id"),
            prover_version=response.prover_version,
            nonce=getattr(response, "request_id", None),
            batch_index=payload.get("batchIndex"),
        )
    return True


async def _process_proof_job(redis_client: Redis, job: dict[str, Any]) -> None:
    job_id = job.get("job_id")
    _, dedupe_key = _queue_keys()
    try:
        payload_dict = job.get("market_payload") or {}
        try:
            market_payload = MarketPayload.model_validate(payload_dict)
        except Exception as exc:
            snapshot = job.get("market_snapshot") or {}
            event_id = snapshot.get("event_id") or ""
            if not event_id:
                log_event(
                    logger,
                    logging.WARNING,
                    event="worker.proof.queue_job_invalid",
                    message="dropping invalid proof job payload",
                    job_id=job_id,
                    error=str(exc),
                )
                await _dead_letter(redis_client, job, "invalid_payload")
                return
            market_payload = MarketPayload(
                event_id=event_id,
                title=snapshot.get("title") or "Claim proof job",
                condition_id=snapshot.get("condition_id") or job.get("condition_id"),
                market_address=snapshot.get("market_address"),
            )
        snapshot = job.get("market_snapshot") or {}
        condition = job.get("condition_id")
        await maybe_generate_settlement_proof(
            redis_client,
            market_snapshot=snapshot,
            market_payload=market_payload,
            condition_id=condition,
        )
        # Enqueue settlement job to run separately with its own DLQ/backoff.
        await enqueue_settlement_job(redis_client)
    except Exception as exc:  # pragma: no cover - defensive processing
        log_event(
            logger,
            logging.WARNING,
            event="worker.proof.queue_job_failed",
            message="failed to process proof queue job",
            job_id=job_id,
            error=str(exc),
        )
        await _dead_letter(redis_client, job, "processing_error")
    finally:
        try:
            if job_id:
                await _resolve_awaitable(redis_client.srem(dedupe_key, job_id))
        except Exception:
            log_event(
                logger,
                logging.DEBUG,
                event="worker.proof.queue_cleanup_failed",
                message="failed to clean up proof queue dedupe entry",
                job_id=job_id,
            )
        await _update_queue_depth(redis_client)


async def run_proof_queue_worker(redis_client: Redis | None) -> None:
    """Continuously drain the proof queue without blocking the main Gamma loop."""

    if redis_client is None:
        return
    queue_key, _ = _queue_keys()
    poll = max(runtime.settings.proof_queue_poll_seconds, 0.1)
    semaphore = asyncio.Semaphore(max(1, runtime.settings.proof_queue_max_concurrency))
    await _update_queue_depth(redis_client)
    try:
        while True:
            raw_job = None
            try:
                raw_job = await _resolve_awaitable(redis_client.lpop(queue_key))
            except Exception as exc:  # pragma: no cover - redis transient errors
                log_event(
                    logger,
                    logging.WARNING,
                    event="worker.proof.queue_read_failed",
                    message="failed to read proof queue",
                    error=str(exc),
                )
            if raw_job is None:
                await asyncio.sleep(poll)
                continue
            if isinstance(raw_job, (bytes, bytearray)):
                raw_payload = raw_job.decode()
            elif isinstance(raw_job, str):
                raw_payload = raw_job
            else:
                await _update_queue_depth(redis_client)
                continue
            try:
                job: dict[str, Any] = json.loads(raw_payload)
            except Exception:
                await _update_queue_depth(redis_client)
                continue
            async with semaphore:
                await _process_proof_job(redis_client, job)
    except asyncio.CancelledError:  # pragma: no cover - shutdown path
        return


async def enqueue_settlement_job(redis_client: Redis | None) -> int:
    """Enqueue a settlement job if Redis is available."""

    if redis_client is None:
        return 0
    queue_key, _ = _settlement_queue_keys()
    try:
        await _resolve_awaitable(redis_client.rpush(queue_key, json.dumps({"job": "settle"})))
        await _update_settlement_depth(redis_client)
        return 1
    except Exception as exc:  # pragma: no cover - enqueue best-effort
        log_event(
            logger,
            logging.WARNING,
            event="worker.settlement.queue_enqueue_failed",
            message="failed to enqueue settlement job",
            error=str(exc),
        )
        return 0


async def _update_settlement_depth(redis_client: Redis | None) -> None:
    if redis_client is None:
        return
    queue_key, _ = _settlement_queue_keys()
    try:
        depth = await _resolve_awaitable(redis_client.llen(queue_key))
        SETTLEMENT_QUEUE_DEPTH_GAUGE.labels(queue=queue_key).set(float(depth))
    except Exception:  # pragma: no cover - metrics best-effort
        return


async def _process_settlement_job(redis_client: Redis, job: dict[str, Any]) -> None:
    try:
        temp_summary = SyncSummary()
        await run_settlement_jobs(temp_summary, redis_client)
    except Exception as exc:  # pragma: no cover - defensive
        await _settlement_dead_letter(redis_client, job, "processing_error")
        log_event(
            logger,
            logging.WARNING,
            event="worker.settlement.queue_job_failed",
            message="failed to process settlement queue job",
            error=str(exc),
        )
    finally:
        await _update_settlement_depth(redis_client)


async def run_settlement_queue_worker(redis_client: Redis | None) -> None:
    """Continuously drain the settlement queue."""

    if redis_client is None:
        return
    queue_key, _ = _settlement_queue_keys()
    poll = max(runtime.settings.settlement_queue_poll_seconds, 0.1)
    semaphore = asyncio.Semaphore(max(1, runtime.settings.settlement_queue_max_concurrency))
    await _update_settlement_depth(redis_client)
    try:
        while True:
            raw_job = None
            try:
                raw_job = await _resolve_awaitable(redis_client.lpop(queue_key))
            except Exception as exc:  # pragma: no cover
                log_event(
                    logger,
                    logging.WARNING,
                    event="worker.settlement.queue_read_failed",
                    message="failed to read settlement queue",
                    error=str(exc),
                )
            if raw_job is None:
                await asyncio.sleep(poll)
                continue
            if isinstance(raw_job, (bytes, bytearray)):
                raw_payload = raw_job.decode()
            elif isinstance(raw_job, str):
                raw_payload = raw_job
            else:
                await _update_settlement_depth(redis_client)
                continue
            try:
                job: dict[str, Any] = json.loads(raw_payload)
            except Exception:
                await _update_settlement_depth(redis_client)
                continue
            async with semaphore:
                await _process_settlement_job(redis_client, job)
    except asyncio.CancelledError:  # pragma: no cover
        return
