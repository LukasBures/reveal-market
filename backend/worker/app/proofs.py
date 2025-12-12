"""Settlement proof orchestration and persistence helpers."""

from __future__ import annotations

import logging
from typing import Any

from redis.asyncio import Redis
from shared import cache_async as shared_cache
from shared import models as shared_models
from shared.cache_keys import proof_receipt_cache_key
from shared.logging import log_event
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import runtime
from .database import session_scope
from .market_sync import SyncSummary
from .polymarket import MarketPayload
from .proof_builder import SettlementDataMissingError, build_prover_payload
from .prover_client import ProverError

logger = runtime.logger


def _persist_settlement_snapshot(session: Session, market_id: int, snapshot: dict[str, Any]) -> None:
    """Write settlement + commitment data to the ledger tables for durability."""

    def _as_int(value: Any) -> int | None:
        try:
            return int(value)
        except Exception:
            return None

    settlement_fields = {
        "merkle_root": snapshot.get("merkleRoot") or snapshot.get("commitments_root"),
        "commitments_count": _as_int(snapshot.get("commitmentsCount") or snapshot.get("commitments_count")),
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
        from shared import repository as shared_repository

        shared_repository.upsert_settlement_snapshot(session, market_id, settlement_payload)

    tickets = snapshot.get("tickets") or []
    if tickets:
        try:
            from shared import repository as shared_repository

            shared_repository.record_commitments(session, market_id, tickets)
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
    }


async def run_prover_jobs(summary: SyncSummary, redis_client: Redis | None) -> int:
    """Iterate queued proof jobs and return how many proofs were generated."""
    if (
        not runtime.settings.prover_enabled
        or not runtime.settings.auto_settlement_enabled
        or runtime.PROVER_CLIENT is None
    ):
        log_event(
            logger,
            logging.DEBUG,
            event="worker.proof.disabled",
            message="skipping proof generation (disabled or client unavailable)",
            prover_enabled=runtime.settings.prover_enabled,
            auto_settlement_enabled=runtime.settings.auto_settlement_enabled,
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

    if (
        not runtime.settings.prover_enabled
        or not runtime.settings.auto_settlement_enabled
        or runtime.PROVER_CLIENT is None
    ):
        log_event(
            logger,
            logging.DEBUG,
            event="worker.proof.disabled",
            message="settlement proof generation is disabled or client unavailable",
            prover_enabled=runtime.settings.prover_enabled,
            auto_settlement_enabled=runtime.settings.auto_settlement_enabled,
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

    if market_identifier is None:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.proof.no_market_id",
            message="skipping proof generation due to missing market id",
            event_id=market_snapshot.get("event_id"),
        )
        return False
    payload: dict[str, Any] | None = None
    persisted_snapshot = False
    try:
        async with session_scope() as session:
            if numeric_market_id is None:
                raise ValueError("non-numeric market id")
            market_record = await session.get(shared_models.Market, numeric_market_id)
            if market_record:
                market_event_id = market_event_id or getattr(market_record, "event_id", None)
                record_condition = getattr(market_record, "condition_id", None)
                if normalized_condition is None and isinstance(record_condition, str):
                    normalized_condition = record_condition.lower()
                if market_address is None:
                    market_address = getattr(market_record, "market_address", None)
            payload = await session.run_sync(build_prover_payload, numeric_market_id)
            await session.run_sync(_persist_settlement_snapshot, numeric_market_id, payload)
            persisted_snapshot = True
            settlement_row = (
                await session.execute(
                    select(shared_models.Settlement).where(shared_models.Settlement.market_id == numeric_market_id)
                )
            ).scalar_one_or_none()
            if settlement_row:
                settlement_row.proof_status = shared_models.SettlementProofStatus.REQUESTED.value
                session.add(settlement_row)
            await session.flush()
    except (ValueError, SettlementDataMissingError) as exc:
        fallback = _build_snapshot_payload(market_snapshot, market_payload, market_identifier or "")
        if not fallback:
            log_event(
                logger,
                logging.DEBUG,
                event="worker.proof.incomplete",
                message="skipping proof generation due to missing settlement fields",
                error=str(exc),
                event_id=market_snapshot.get("event_id"),
            )
            return False
        payload = fallback
    if payload is not None and numeric_market_id is not None and not persisted_snapshot:
        try:
            async with session_scope() as session:
                await session.run_sync(_persist_settlement_snapshot, numeric_market_id, payload)
                settlement_row = (
                    await session.execute(
                        select(shared_models.Settlement).where(shared_models.Settlement.market_id == numeric_market_id)
                    )
                ).scalar_one_or_none()
                if settlement_row:
                    settlement_row.proof_status = shared_models.SettlementProofStatus.REQUESTED.value
                    session.add(settlement_row)
        except Exception as exc:  # pragma: no cover - defensive snapshot persistence
            log_event(
                logger,
                logging.WARNING,
                event="worker.proof.snapshot.persist_failed",
                message="failed to persist settlement snapshot",
                error=str(exc),
                market_id=numeric_market_id,
            )
    if payload is None:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.proof.incomplete",
            message="skipping proof generation due to missing payload",
            event_id=market_snapshot.get("event_id"),
        )
        return False
    log_event(
        logger,
        logging.DEBUG,
        event="worker.proof.request_ready",
        message="constructed settlement proof request",
        market_id=payload.get("marketId"),
        merkle_root=payload.get("merkleRoot"),
    )
    try:
        response = await runtime.PROVER_CLIENT.generate_settlement_proof(payload)
    except ProverError as exc:
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
        return False

    proof_hash = None
    try:
        from eth_utils import keccak

        proof_hash_source = (response.proof or "") + "".join(response.public_signals or [])
        proof_hash = keccak(proof_hash_source.encode()).hex()
    except Exception:  # pragma: no cover - defensive
        proof_hash = None

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
        "proof_hash": f"0x{proof_hash}" if proof_hash else None,
    }
    cache_key_target = (
        normalized_condition
        or payload.get("conditionId")
        or payload.get("marketId")
        or market_event_id
        or market_identifier
        or ""
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
                settlement.proof_request_id = response.request_id
                settlement.proof_hash = f"0x{proof_hash}" if proof_hash else None
                session.add(settlement)
            if numeric_market_id is not None:
                from shared import repository as shared_repository

                await session.run_sync(
                    shared_repository.record_settlement_receipt,
                    market_id=numeric_market_id,
                    market_address=market_address,
                    request_id=response.request_id,
                    proof_hash=f"0x{proof_hash}" if proof_hash else None,
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

    log_event(
        logger,
        logging.DEBUG,
        event="worker.proof.generated",
        message="cached settlement proof receipt",
        event_id=market_event_id,
        condition_id=normalized_condition or condition_id or market_snapshot.get("condition_id"),
        prover_version=response.prover_version,
        nonce=getattr(response, "request_id", None),
    )
    return True
