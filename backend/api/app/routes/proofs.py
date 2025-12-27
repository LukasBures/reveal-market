"""Proof receipt routes for settlement provenance."""

from __future__ import annotations

import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from shared import models as shared_models
from shared.cache_async import get_json
from shared.cache_keys import proof_receipt_cache_key
from shared.logging import log_event
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas
from app.database import get_session
from app.metrics import update_cache_context
from app.runtime import logger, settings
from app.services.cache_client import get_cache_client
from app.services.proofs import build_proof_receipt_model

router = APIRouter()


def _root_cache_key(receipt: shared_models.SettlementReceipt) -> str | None:
    signals = receipt.public_signals
    if isinstance(signals, (list, tuple)) and signals:
        try:
            root_signal = str(signals[0])
        except Exception:
            root_signal = None
        if root_signal:
            return proof_receipt_cache_key(f"root:{root_signal}")
    return None


def _root_signal_from_value(value: object) -> str | None:
    if value is None:
        return None
    try:
        if isinstance(value, (bytes, bytearray)):
            return str(int.from_bytes(value, "big")) if value else None
        if isinstance(value, str):
            cleaned = value.strip().lower()
            if cleaned.startswith("0x"):
                return str(int(cleaned[2:] or "0", 16))
            return str(int(cleaned))
        return str(int(str(value)))
    except (TypeError, ValueError):
        return None


def _root_cache_key_from_batch(
    receipt: shared_models.SettlementReceipt, settlement: shared_models.Settlement | None
) -> str | None:
    if settlement is None:
        return None
    batch_index = getattr(receipt, "batch_index", None)
    if batch_index is None:
        return None
    try:
        index = int(batch_index)
    except (TypeError, ValueError):
        return None
    batch_roots = getattr(settlement, "batch_roots", None)
    if not isinstance(batch_roots, (list, tuple)):
        return None
    if index < 0 or index >= len(batch_roots):
        return None
    root_signal = _root_signal_from_value(batch_roots[index])
    if not root_signal:
        return None
    return proof_receipt_cache_key(f"root:{root_signal}")


@router.get("/proofs", response_model=list[schemas.ProofReceipt], tags=["proofs"], include_in_schema=False)
async def list_proof_receipts(
    request: Request,
    limit: Annotated[
        int, Query(ge=1, le=settings.max_page_size, description="Maximum number of proof receipts to return")
    ] = settings.default_page_size,
    offset: Annotated[int, Query(ge=0, description="Offset into the receipts list")] = 0,
    market_id: Annotated[int | None, Query(ge=1, description="Filter by numeric market id")] = None,
    event_id: Annotated[str | None, Query(description="Filter by market event id")] = None,
    condition_id: Annotated[str | None, Query(description="Filter by condition id (0x…)")] = None,
    request_id: Annotated[str | None, Query(description="Filter by prover request id")] = None,
    session: AsyncSession = Depends(get_session),
) -> list[schemas.ProofReceipt]:
    """List settlement proof receipts, pulling cached payloads when present."""

    start = time.perf_counter()
    cache = await get_cache_client()
    cache_available = cache is not None
    bounded_limit = min(limit, settings.max_page_size)
    bounded_offset = max(0, offset)
    condition_filter = condition_id.strip().lower() if isinstance(condition_id, str) else None
    request_filter = request_id.strip() if isinstance(request_id, str) else None
    event_filter = event_id.strip() if isinstance(event_id, str) else None
    log_event(
        logger,
        logging.DEBUG,
        event="proofs.list.request",
        message="fetching proof receipts",
        limit=bounded_limit,
        offset=bounded_offset,
        market_id=market_id,
        event_id=event_filter,
        condition_id=condition_filter,
        request_id=request_filter,
    )
    stmt = (
        select(
            shared_models.SettlementReceipt,
            shared_models.Settlement,
            shared_models.Market,
        )
        .join(
            shared_models.Settlement,
            shared_models.Settlement.market_id == shared_models.SettlementReceipt.market_id,
            isouter=True,
        )
        .join(
            shared_models.Market,
            shared_models.Market.id == shared_models.SettlementReceipt.market_id,
            isouter=True,
        )
        .order_by(
            shared_models.SettlementReceipt.generated_at.desc(),
            shared_models.SettlementReceipt.created_at.desc(),
        )
        .offset(bounded_offset)
        .limit(bounded_limit)
    )
    filters = []
    if market_id is not None:
        filters.append(shared_models.SettlementReceipt.market_id == market_id)
    if request_filter:
        filters.append(shared_models.SettlementReceipt.request_id == request_filter)
    if event_filter:
        filters.append(shared_models.Market.event_id == event_filter)
    if condition_filter:
        filters.append(func.lower(shared_models.Market.condition_id) == condition_filter)
    if filters:
        stmt = stmt.where(*filters)
    rows = (await session.execute(stmt)).all()
    receipts: list[schemas.ProofReceipt] = []
    cache_hits = 0
    for receipt_row, settlement_row, market_row in rows:
        cached_payload = None
        condition_value = getattr(market_row, "condition_id", None) if market_row is not None else None
        if cache_available:
            key = _root_cache_key(receipt_row)
            if key:
                cached_payload = await get_json(cache, key)
            if cached_payload is None and settlement_row is not None:
                key = _root_cache_key_from_batch(receipt_row, settlement_row)
                if key:
                    cached_payload = await get_json(cache, key)
            if cached_payload is None and condition_value:
                cached_payload = await get_json(cache, proof_receipt_cache_key(str(condition_value)))
            if cached_payload is not None:
                cache_hits += 1
        receipts.append(build_proof_receipt_model(receipt_row, settlement_row, market_row, cached_payload))
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    log_event(
        logger,
        logging.INFO,
        event="proofs.list.response",
        message="served proof receipts",
        limit=bounded_limit,
        offset=bounded_offset,
        result_count=len(receipts),
        cache_hits=cache_hits,
        duration_ms=duration_ms,
    )
    update_cache_context(request, cache_key=None, hit=cache_hits > 0, source="proofs")
    return receipts
