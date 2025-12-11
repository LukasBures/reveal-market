from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from shared import models as shared_models
from shared import repository as shared_repository
from sqlalchemy.ext.asyncio import AsyncSession


async def record_schema_version(session: AsyncSession, revision: str, *, key: str) -> str | None:
    return await session.run_sync(shared_repository.record_schema_version, revision, key=key)


async def expire_stale_quotes(session: AsyncSession, *, now: datetime | None = None) -> int:
    return await session.run_sync(shared_repository.expire_stale_quotes, now=now)


async def sum_quote_stakes(
    session: AsyncSession,
    *,
    market_id: str | None = None,
    user_id: str | None = None,
    window_seconds: int | None = None,
    statuses: set[str] | None = None,
) -> Decimal:
    return await session.run_sync(
        shared_repository.sum_quote_stakes,
        market_id=market_id,
        user_id=user_id,
        window_seconds=window_seconds,
        statuses=statuses,
    )


async def get_market_by_event_id(session: AsyncSession, event_id: str) -> shared_models.Market | None:
    return await session.run_sync(shared_repository.get_market_by_event_id, event_id)


async def create_quote(session: AsyncSession, data: Mapping[str, Any]) -> shared_models.Quote:
    return await session.run_sync(shared_repository.create_quote, data)


async def get_quote(session: AsyncSession, quote_id: str) -> shared_models.Quote | None:
    return await session.run_sync(shared_repository.get_quote, quote_id)


async def mark_quote_status(
    session: AsyncSession,
    quote: shared_models.Quote,
    status: shared_models.QuoteStatusEnum,
    *,
    consumed_at: datetime | None = None,
) -> shared_models.Quote:
    return await session.run_sync(shared_repository.mark_quote_status, quote, status, consumed_at=consumed_at)


async def upsert_resolution(session: AsyncSession, data: Mapping[str, Any]) -> shared_models.Resolution:
    return await session.run_sync(shared_repository.upsert_resolution, data)
