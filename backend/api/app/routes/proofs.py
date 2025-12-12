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
        if cache_available and condition_value:
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
