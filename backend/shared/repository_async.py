from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, TypeVar

from sqlalchemy import and_, delete, func, insert, or_, select
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from . import models

logger = logging.getLogger("reveal_market.shared.repository_async")

DEFAULT_SCHEMA_VERSION_KEY = "core"

T = TypeVar("T")


def _is_transient_db_error(exc: BaseException) -> bool:
    """Return True for transient DB errors worth retrying."""
    if isinstance(exc, OperationalError):
        return True
    if isinstance(exc, DBAPIError) and getattr(exc, "connection_invalidated", False):
        return True
    return False


db_retry = retry(
    retry=retry_if_exception(_is_transient_db_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.2, max=2),
    reraise=True,
)


@db_retry
async def get_market_by_event_id(session: AsyncSession, event_id: str) -> models.Market | None:
    """Return a market by its unique event identifier."""

    stmt = select(models.Market).where(models.Market.event_id == event_id)
    return (await session.scalars(stmt)).first()


@db_retry
async def get_market_by_onchain_market_id(session: AsyncSession, onchain_market_id: int) -> models.Market | None:
    """Return a market by its onchain numeric identifier."""

    stmt = select(models.Market).where(models.Market.onchain_market_id == onchain_market_id)
    return (await session.scalars(stmt)).first()


@db_retry
async def get_market_by_market_address(session: AsyncSession, market_address: str) -> models.Market | None:
    """Return a market by its onchain address."""

    stmt = select(models.Market).where(models.Market.market_address == market_address)
    return (await session.scalars(stmt)).first()


async def upsert_market(
    session: AsyncSession,
    data: Mapping[str, Any],
    existing: models.Market | None = None,
) -> models.Market:
    """Insert or update a market row based on the provided field mapping."""

    payload = dict(data)
    for legacy in (
        "outcomes",
        "outcome_prices",
        "tags",
        "clob_token_ids",
        "merkle_root",
        "proof_status",
        "proof_request_id",
        "proof_hash",
        "submission_status",
        "settlement_tx_hash",
        "settlement_submitted_at",
        "extra_data",
        "group_item_title",
        "group_item_threshold",
        "best_bid",
        "best_ask",
        "spread",
        "volume",
        "open_interest",
        "grouping_window_key",
        "grouping_resolution_source",
    ):
        payload.pop(legacy, None)
    market = existing or await get_market_by_event_id(session, payload["event_id"])
    if market is None:
        onchain_market_id = payload.get("onchain_market_id")
        if onchain_market_id is not None:
            market = await get_market_by_onchain_market_id(session, int(onchain_market_id))
    if market is None:
        market_address = payload.get("market_address")
        if market_address:
            market = await get_market_by_market_address(session, str(market_address))
    if market is None:
        market = models.Market(**payload)
        session.add(market)
    else:
        # Preserve on-chain identifiers already persisted; upstream payloads must never override these.
        for protected in ("market_address", "onchain_market_id", "factory"):
            existing_value = getattr(market, protected, None)
            if existing_value not in (None, ""):
                payload.pop(protected, None)
        for field, value in payload.items():
            if hasattr(market, field):
                setattr(market, field, value)
    return market


async def get_resolution_by_condition_id(session: AsyncSession, condition_id: str) -> models.Resolution | None:
    """Return a persisted resolution snapshot for the given condition id."""

    stmt = select(models.Resolution).where(models.Resolution.condition_id == condition_id)
    return (await session.scalars(stmt)).first()


async def get_resolution_for_market(session: AsyncSession, market_id: int) -> models.Resolution | None:
    """Return the latest resolution linked to a market via its condition id."""

    stmt = (
        select(models.Resolution)
        .join(models.Market, models.Resolution.condition_id == models.Market.condition_id)
        .where(models.Market.id == market_id)
    )
    return (await session.scalars(stmt)).first()


async def upsert_resolution(session: AsyncSession, data: Mapping[str, Any]) -> models.Resolution:
    """Insert or update a resolution record."""

    payload = dict(data)
    payload.pop("outcomes", None)
    condition_id = payload["condition_id"]
    record = await get_resolution_by_condition_id(session, condition_id)
    if record is None:
        record = models.Resolution(**payload)
        session.add(record)
    else:
        for field, value in payload.items():
            setattr(record, field, value)
    return record


async def get_quote(session: AsyncSession, quote_id: str) -> models.Quote | None:
    """Return a stored pricing quote."""

    return await session.get(models.Quote, quote_id)


async def create_quote(session: AsyncSession, data: Mapping[str, Any]) -> models.Quote:
    """Persist a freshly issued pricing quote."""

    payload = dict(data)
    quote_id = payload["quote_id"]
    existing = await session.get(models.Quote, quote_id)
    if existing is not None:
        raise ValueError(f"quote {quote_id} already exists")
    record = models.Quote(**payload)
    session.add(record)
    return record


async def mark_quote_status(
    session: AsyncSession,
    quote: models.Quote,
    status: models.QuoteStatusEnum,
    consumed_at: datetime | None = None,
) -> models.Quote:
    """Update quote status, capturing consumption time when applicable."""

    quote.status = status.value
    if consumed_at:
        quote.consumed_at = consumed_at
    session.add(quote)
    return quote


async def record_quote_audit(session: AsyncSession, data: Mapping[str, Any]) -> models.QuoteAudit:
    payload = dict(data)
    record = models.QuoteAudit(**payload)
    session.add(record)
    return record


async def expire_stale_quotes(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Mark any expired quotes as stale so cap calculations stay accurate."""

    reference = now or datetime.now(UTC)
    stmt = select(models.Quote).where(
        models.Quote.status == models.QuoteStatusEnum.ISSUED.value,
        models.Quote.expires_at < reference,
    )
    count = 0
    result = await session.scalars(stmt)
    for quote in result:
        quote.status = models.QuoteStatusEnum.EXPIRED.value
        session.add(quote)
        count += 1
    return count


async def sum_quote_stakes(
    session: AsyncSession,
    *,
    market_id: str | None = None,
    wallet_address: str | None = None,
    window_seconds: int | None = None,
    statuses: set[str] | None = None,
) -> Decimal:
    """Return the aggregate stake_zen for quotes matching the filters."""

    active_statuses = statuses or {
        models.QuoteStatusEnum.ISSUED.value,
        models.QuoteStatusEnum.CONSUMED.value,
    }
    stmt = select(func.coalesce(func.sum(models.Quote.stake_zen), 0))
    stmt = stmt.where(models.Quote.status.in_(active_statuses))
    if market_id:
        stmt = stmt.where(models.Quote.market_id == market_id)
    if wallet_address:
        stmt = stmt.where(models.Quote.wallet_address == wallet_address)
    if window_seconds and window_seconds > 0:
        cutoff = datetime.now(UTC) - timedelta(seconds=window_seconds)
        stmt = stmt.where(models.Quote.created_at >= cutoff)
    return Decimal(await session.scalar(stmt) or 0)


async def get_schema_version(
    session: AsyncSession, key: str = DEFAULT_SCHEMA_VERSION_KEY
) -> models.SchemaVersion | None:
    """Fetch the recorded schema version for the provided key."""

    return await session.get(models.SchemaVersion, key)


async def record_schema_version(
    session: AsyncSession, revision: str, key: str = DEFAULT_SCHEMA_VERSION_KEY
) -> str | None:
    """Persist the current schema revision and return the previous value if present."""

    previous_revision: str | None = None
    record = await get_schema_version(session, key)
    now = datetime.now(UTC)
    if record is None:
        record = models.SchemaVersion(key=key, revision=revision, applied_at=now)
        session.add(record)
        return None
    previous_revision = record.revision
    record.revision = revision
    record.applied_at = now
    return previous_revision


async def upsert_settlement_snapshot(
    session: AsyncSession, market_id: int, data: Mapping[str, Any]
) -> models.Settlement:
    """Insert or update a settlement snapshot for a market."""

    settlement = (
        await session.execute(select(models.Settlement).where(models.Settlement.market_id == market_id))
    ).scalar_one_or_none()
    payload = dict(data)
    if settlement is None:
        settlement = models.Settlement(market_id=market_id)
        # SQLite fixtures may not auto-increment BigInteger PKs; align id to market_id for deterministic testing.
        if getattr(settlement, "id", None) is None:
            bind = session.get_bind()
            if hasattr(bind, "dialect"):
                dialect_name = bind.dialect.name
            elif hasattr(bind, "sync_engine"):
                dialect_name = bind.sync_engine.dialect.name
            else:
                dialect_name = ""
            if dialect_name == "sqlite":
                settlement.id = market_id  # type: ignore[assignment]
    for field, value in payload.items():
        if hasattr(settlement, field):
            setattr(settlement, field, value)
    session.add(settlement)
    return settlement


async def record_commitments(
    session: AsyncSession, market_id: int, tickets: Sequence[Mapping[str, Any]], tx_hash: str | None = None
) -> int:
    """Persist commitments (and merkle siblings) for a market, skipping duplicates."""

    bind = session.get_bind()
    if hasattr(bind, "dialect"):
        dialect_name = bind.dialect.name
    elif hasattr(bind, "sync_engine"):
        dialect_name = bind.sync_engine.dialect.name
    else:
        dialect_name = ""
    existing_hashes = {
        row[0]
        for row in (
            await session.execute(select(models.Commitment.ticket_hash).where(models.Commitment.market_id == market_id))
        ).all()
    }
    count = 0
    for ticket in tickets:
        ticket_hash = str(ticket.get("ticketHash") or ticket.get("ticket_hash") or "").lower()
        if not ticket_hash or ticket_hash in existing_hashes:
            continue
        raw_index = ticket.get("merkleIndex")
        if raw_index is None:
            raw_index = ticket.get("leaf_index")
        leaf_index = None
        if raw_index is not None:
            try:
                leaf_index = int(raw_index)
            except (TypeError, ValueError):
                leaf_index = None
        commitment_values = {
            "market_id": market_id,
            "user_address": str(ticket.get("user") or ticket.get("user_address") or "").lower(),
            "outcome_id": int(ticket.get("outcomeId") or ticket.get("outcome_id") or 0),
            "amount_wei": int(ticket.get("amount") or ticket.get("amount_wei") or 0),
            "payout_wei": int(ticket.get("payout") or ticket.get("payout_wei") or 0),
            "salt": str(ticket.get("salt") or "0x0"),
            "ticket_hash": ticket_hash,
            "leaf": str(ticket.get("leaf") or ""),
            "leaf_index": leaf_index,
            "tx_hash": str(ticket.get("txHash") or ticket.get("tx_hash") or tx_hash or "") or None,
        }
        if dialect_name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            stmt = (
                pg_insert(models.Commitment)
                .values(**commitment_values)
                .on_conflict_do_nothing(index_elements=["market_id", "ticket_hash"])
                .returning(models.Commitment.id)
            )
        elif dialect_name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            stmt = (
                sqlite_insert(models.Commitment)
                .values(**commitment_values)
                .prefix_with("OR IGNORE")
                .returning(models.Commitment.id)
            )
        else:
            stmt = insert(models.Commitment).values(**commitment_values).returning(models.Commitment.id)
        result = await session.execute(stmt)
        commitment_id = result.scalar_one_or_none()
        if not commitment_id:
            continue
        existing_hashes.add(ticket_hash)
        siblings = ticket.get("merklePath") or ticket.get("merkle_path") or []
        for level, sibling in enumerate(siblings):
            session.add(
                models.CommitmentMerklePath(
                    commitment_id=commitment_id,
                    level=level,
                    sibling_hash=str(sibling),
                )
            )
        count += 1
    return count


async def replace_merkle_path(session: AsyncSession, commitment_id: int, siblings: list[str]) -> None:
    """Replace merkle path rows for a commitment."""

    await session.execute(
        delete(models.CommitmentMerklePath).where(models.CommitmentMerklePath.commitment_id == commitment_id)
    )
    for level, sibling in enumerate(siblings):
        session.add(models.CommitmentMerklePath(commitment_id=commitment_id, level=level, sibling_hash=str(sibling)))
    await session.flush()


async def count_commitments(session: AsyncSession, market_db_id: int) -> int:
    """Return the number of commitments persisted for a market."""

    result = await session.execute(
        select(func.count()).select_from(models.Commitment).where(models.Commitment.market_id == market_db_id)
    )
    return int(result.scalar_one() or 0)


@db_retry
async def list_commitments_for_wallet(
    session: AsyncSession, wallet_address: str, *, limit: int = 500
) -> list[tuple[models.Commitment, models.Market]]:
    """Return commitments with market metadata for a wallet address."""

    stmt = (
        select(models.Commitment, models.Market)
        .join(models.Market, models.Market.id == models.Commitment.market_id)
        .where(models.Commitment.user_address == wallet_address.lower())
        .order_by(models.Commitment.created_at.desc())
        .limit(limit)
    )
    rows = await session.execute(stmt)
    return [(commitment, market) for commitment, market in rows.all()]


@db_retry
async def list_commitments_with_settlement(
    session: AsyncSession,
    wallet_address: str,
    *,
    market_filter: str | None = None,
    winning_only: bool = False,
    limit: int = 500,
) -> list[tuple[models.Commitment, models.Market, models.Settlement | None]]:
    """Return commitments joined with market + optional settlement.

    When market_filter is provided, it matches either the event_id or market_address.
    Set winning_only=True to only return rows where settlement.winning_outcome_id matches
    the commitment outcome (settlement is required in that case).
    """

    stmt = (
        select(models.Commitment, models.Market, models.Settlement)
        .join(models.Market, models.Market.id == models.Commitment.market_id)
        .options(selectinload(models.Market.outcomes_rel))
    )
    if winning_only:
        stmt = stmt.join(models.Settlement, models.Settlement.market_id == models.Commitment.market_id)
        stmt = stmt.where(
            models.Settlement.winning_outcome_id.is_not(None),
            models.Settlement.winning_outcome_id == models.Commitment.outcome_id,
        )
    else:
        stmt = stmt.join(
            models.Settlement,
            models.Settlement.market_id == models.Commitment.market_id,
            isouter=True,
        )

    stmt = stmt.where(models.Commitment.user_address == wallet_address.lower())
    if market_filter:
        market_filter_lower = market_filter.lower()
        stmt = stmt.where(
            or_(
                models.Market.event_id == market_filter,
                func.lower(models.Market.event_id) == market_filter_lower,
                func.lower(models.Market.market_address) == market_filter_lower,
            )
        )

    stmt = stmt.order_by(models.Commitment.created_at.desc()).limit(limit)
    rows = await session.execute(stmt)
    return [(commitment, market, settlement) for commitment, market, settlement in rows.all()]


@db_retry
async def list_commitments_by_market(
    session: AsyncSession, market_id: int, *, limit: int = 500
) -> list[models.Commitment]:
    """Return all commitments for a market ordered by leaf index then id."""

    stmt = (
        select(models.Commitment)
        .where(models.Commitment.market_id == market_id)
        .order_by(models.Commitment.leaf_index.asc().nulls_last(), models.Commitment.id.asc())
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


async def update_commitment_tx_hash(session: AsyncSession, old_hash: str, new_hash: str) -> int:
    """Replace a stored tx hash/job id with the finalized transaction hash."""

    stmt = select(models.Commitment).where(models.Commitment.tx_hash == old_hash).with_for_update()
    rows = (await session.scalars(stmt)).all()
    updated = 0
    for row in rows:
        row.tx_hash = new_hash
        session.add(row)
        updated += 1
    if updated:
        await session.flush()
    return updated


async def list_markets_missing_address(session: AsyncSession, *, limit: int | None = None) -> list[models.Market]:
    """Return markets that are missing a contract address."""

    stmt = (
        select(models.Market)
        .where(models.Market.market_address.is_(None))
        .where(models.Market.onchain_market_id.is_not(None))
        .where(models.Market.onchain_market_id != 0)
        .order_by(models.Market.id.asc())
    )
    if limit and limit > 0:
        stmt = stmt.limit(limit)
    return list((await session.scalars(stmt)).all())


async def list_markets_for_factory_sync(session: AsyncSession, *, limit: int | None = None) -> list[models.Market]:
    """Return markets that should be mirrored against on-chain factory params."""

    stmt = (
        select(models.Market)
        .where(models.Market.market_address.is_not(None))
        .where(models.Market.market_address != "")
        .where(
            or_(
                models.Market.factory.is_(None),
                models.Market.factory == "",
                models.Market.rake_bps.is_(None),
                models.Market.onchain_market_id.is_(None),
            )
        )
        .order_by(models.Market.id.asc())
    )
    if limit and limit > 0:
        stmt = stmt.limit(limit)
    return list((await session.scalars(stmt)).all())


async def get_settlement_by_market_id(session: AsyncSession, market_id: int) -> models.Settlement | None:
    """Return the settlement snapshot for a market when it exists."""

    stmt = select(models.Settlement).where(models.Settlement.market_id == market_id)
    return (await session.scalars(stmt)).first()


async def get_commitment_with_path_for_wallet(
    session: AsyncSession, market_db_id: int, wallet_address: str, outcome_id: int, ticket_id: int | None = None
) -> tuple[models.Commitment, list[models.CommitmentMerklePath]] | None:
    """Return a commitment and its merkle path for a wallet/outcome (optionally by ticket id)."""

    filters = [
        models.Commitment.market_id == market_db_id,
        models.Commitment.user_address == wallet_address.lower(),
        models.Commitment.outcome_id == outcome_id,
    ]
    if ticket_id is not None:
        filters.append(models.Commitment.leaf_index == ticket_id)
    commitment = (
        await session.execute(select(models.Commitment).where(*filters).order_by(models.Commitment.id.asc()))
    ).scalar_one_or_none()
    if commitment is None:
        return None
    paths = (
        (
            await session.execute(
                select(models.CommitmentMerklePath)
                .where(models.CommitmentMerklePath.commitment_id == commitment.id)
                .order_by(models.CommitmentMerklePath.level.asc())
            )
        )
        .scalars()
        .all()
    )
    return commitment, list(paths)


async def record_factory_event(
    session: AsyncSession,
    *,
    factory_address: str,
    market_address: str | None,
    event: str,
    tx_hash: str | None = None,
    block_number: int | None = None,
    block_timestamp: datetime | None = None,
    payload: Mapping[str, Any] | None = None,
) -> models.FactoryEvent:
    """Persist a factory event for audit/mirroring, deduplicating by tx hash + event."""

    normalized_tx = tx_hash.lower() if isinstance(tx_hash, str) else None
    existing: models.FactoryEvent | None = None
    if normalized_tx:
        existing = (
            await session.execute(
                select(models.FactoryEvent).where(
                    models.FactoryEvent.tx_hash == normalized_tx,
                    models.FactoryEvent.event == event,
                )
            )
        ).scalar_one_or_none()
    if existing:
        return existing
    normalized_market = market_address.lower() if isinstance(market_address, str) else None
    if normalized_market:
        market_exists = (
            await session.execute(
                select(models.Market.market_address).where(models.Market.market_address == normalized_market)
            )
        ).scalar_one_or_none()
        if market_exists is None:
            normalized_market = None
    record = models.FactoryEvent(
        factory_address=factory_address.lower(),
        market_address=normalized_market,
        event=event,
        tx_hash=normalized_tx,
        block_number=block_number,
        block_timestamp=block_timestamp,
        payload=dict(payload or {}),
    )
    session.add(record)
    return record


async def record_settlement_receipt(
    session: AsyncSession,
    *,
    market_id: int,
    market_address: str | None,
    request_id: str,
    proof_hash: str | None,
    proof: str | None,
    batch_index: int | None,
    public_signals: list[str] | None,
    prover_version: str | None,
    circuit_hash: str | None,
    generated_at: datetime | None,
) -> models.SettlementReceipt:
    """Persist a prover receipt for downstream automation/audits."""

    existing = (
        await session.execute(
            select(models.SettlementReceipt).where(
                models.SettlementReceipt.market_id == market_id,
                models.SettlementReceipt.request_id == request_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    normalized_market = None
    if isinstance(market_address, str):
        normalized_market = market_address
        market_exists = (
            await session.execute(
                select(models.Market.market_address).where(models.Market.market_address == normalized_market)
            )
        ).scalar_one_or_none()
        if market_exists is None:
            lower = market_address.lower()
            market_exists = (
                await session.execute(select(models.Market.market_address).where(models.Market.market_address == lower))
            ).scalar_one_or_none()
            normalized_market = lower if market_exists is not None else None
    receipt = models.SettlementReceipt(
        market_id=market_id,
        market_address=normalized_market,
        request_id=request_id,
        proof_hash=proof_hash,
        proof=proof,
        batch_index=batch_index,
        public_signals=public_signals or [],
        prover_version=prover_version,
        circuit_hash=circuit_hash,
        generated_at=generated_at,
    )
    session.add(receipt)
    return receipt


async def get_settlement_receipt_by_request_id(
    session: AsyncSession, request_id: str
) -> models.SettlementReceipt | None:
    """Return a settlement receipt by prover request id."""

    stmt = select(models.SettlementReceipt).where(models.SettlementReceipt.request_id == request_id)
    return (await session.scalars(stmt)).first()


async def list_settlements_pending_tx(
    session: AsyncSession,
    *,
    market_event_id: str | None = None,
    include_failed: bool = True,
    processing_stale_seconds: int = 0,
) -> list[tuple[models.Settlement, models.Market]]:
    """Return settlements with generated proofs that have not been submitted on-chain."""

    statuses = [
        models.SettlementSubmissionStatus.NONE.value,
        models.SettlementSubmissionStatus.QUEUED.value,
    ]
    if include_failed:
        statuses.append(models.SettlementSubmissionStatus.FAILED.value)
    status_filters: list[ColumnElement[bool]] = [models.Settlement.submission_status.in_(statuses)]
    if processing_stale_seconds > 0:
        stale_cutoff = datetime.now(tz=UTC) - timedelta(seconds=int(processing_stale_seconds))
        status_filters.append(
            and_(
                models.Settlement.submission_status == models.SettlementSubmissionStatus.PROCESSING.value,
                models.Settlement.updated_at <= stale_cutoff,
            )
        )
    stmt = (
        select(models.Settlement, models.Market)
        .join(models.Market, models.Market.id == models.Settlement.market_id)
        .where(
            models.Settlement.proof_status == models.SettlementProofStatus.GENERATED.value,
            or_(*status_filters),
            models.Settlement.settlement_tx_hash.is_(None),
        )
    )
    if market_event_id:
        stmt = stmt.where(models.Market.event_id == market_event_id)
    rows = await session.execute(stmt)
    return [(settlement, market) for settlement, market in rows.all()]
