from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from shared import models as shared_models
from shared import repository_async as shared_repository_async
from sqlalchemy.ext.asyncio import AsyncSession


async def record_schema_version(session: AsyncSession, revision: str, *, key: str) -> str | None:
    return await shared_repository_async.record_schema_version(session, revision, key=key)


async def expire_stale_quotes(session: AsyncSession, *, now: datetime | None = None) -> int:
    return await shared_repository_async.expire_stale_quotes(session, now=now)


async def sum_quote_stakes(
    session: AsyncSession,
    *,
    market_id: str | None = None,
    user_id: str | None = None,
    window_seconds: int | None = None,
    statuses: set[str] | None = None,
) -> Decimal:
    return await shared_repository_async.sum_quote_stakes(
        session,
        market_id=market_id,
        user_id=user_id,
        window_seconds=window_seconds,
        statuses=statuses,
    )


async def get_market_by_event_id(session: AsyncSession, event_id: str) -> shared_models.Market | None:
    return await shared_repository_async.get_market_by_event_id(session, event_id)


async def create_quote(session: AsyncSession, data: Mapping[str, Any]) -> shared_models.Quote:
    return await shared_repository_async.create_quote(session, data)


async def get_quote(session: AsyncSession, quote_id: str) -> shared_models.Quote | None:
    return await shared_repository_async.get_quote(session, quote_id)


async def mark_quote_status(
    session: AsyncSession,
    quote: shared_models.Quote,
    status: shared_models.QuoteStatusEnum,
    *,
    consumed_at: datetime | None = None,
) -> shared_models.Quote:
    return await shared_repository_async.mark_quote_status(session, quote, status, consumed_at=consumed_at)


async def upsert_resolution(session: AsyncSession, data: Mapping[str, Any]) -> shared_models.Resolution:
    return await shared_repository_async.upsert_resolution(session, data)


async def record_commitments(session: AsyncSession, market_id: int, tickets: Sequence[Mapping[str, Any]]) -> int:
    return await shared_repository_async.record_commitments(session, market_id, tickets)


async def count_commitments(session: AsyncSession, market_db_id: int) -> int:
    return await shared_repository_async.count_commitments(session, market_db_id)


async def list_commitments_with_settlement(
    session: AsyncSession, wallet_address: str
) -> list[tuple[shared_models.Commitment, shared_models.Market, shared_models.Settlement | None]]:
    return await shared_repository_async.list_commitments_with_settlement(session, wallet_address)


async def get_commitment_with_path_for_wallet(
    session: AsyncSession, market_db_id: int, wallet_address: str, outcome_id: int, ticket_id: int | None = None
) -> tuple[shared_models.Commitment, list[shared_models.CommitmentMerklePath]] | None:
    return await shared_repository_async.get_commitment_with_path_for_wallet(
        session, market_db_id, wallet_address, outcome_id, ticket_id
    )


async def list_commitments_by_market(session: AsyncSession, market_id: int) -> list[shared_models.Commitment]:
    return await shared_repository_async.list_commitments_by_market(session, market_id)


async def replace_merkle_path(session: AsyncSession, commitment_id: int, siblings: list[str]) -> None:
    await shared_repository_async.replace_merkle_path(session, commitment_id, siblings)


async def upsert_settlement_snapshot(
    session: AsyncSession, market_id: int, data: Mapping[str, Any]
) -> shared_models.Settlement:
    return await shared_repository_async.upsert_settlement_snapshot(session, market_id, data)
