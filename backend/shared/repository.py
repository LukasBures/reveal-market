from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models

DEFAULT_SCHEMA_VERSION_KEY = "core"


def get_market_by_event_id(session: Session, event_id: str) -> models.Market | None:
    """Return a market by its unique event identifier."""
    stmt = select(models.Market).where(models.Market.event_id == event_id)
    return session.scalars(stmt).first()


def upsert_market(
    session: Session,
    data: Mapping[str, Any],
    existing: models.Market | None = None,
) -> models.Market:
    """Insert or update a market row based on the provided field mapping."""
    payload = dict(data)
    # Drop legacy/normalized-only fields that are no longer columns on markets
    for legacy in (
        "outcomes",
        "outcome_prices",
        "tags",
        "clob_token_ids",
        "extra_data",
        "group_item_title",
        "group_item_threshold",
        "best_bid",
        "best_ask",
        "spread",
        "volume",
        "open_interest",
    ):
        payload.pop(legacy, None)
    market = existing or get_market_by_event_id(session, payload["event_id"])
    if market is None:
        market = models.Market(**payload)
        session.add(market)
    else:
        for field, value in payload.items():
            if hasattr(market, field):
                setattr(market, field, value)
    return market


def get_resolution_by_condition_id(session: Session, condition_id: str) -> models.Resolution | None:
    """Return a persisted resolution snapshot for the given condition id."""
    stmt = select(models.Resolution).where(models.Resolution.condition_id == condition_id)
    return session.scalars(stmt).first()


def upsert_resolution(session: Session, data: Mapping[str, Any]) -> models.Resolution:
    """Insert or update a resolution record."""
    payload = dict(data)
    payload.pop("outcomes", None)
    condition_id = payload["condition_id"]
    record = get_resolution_by_condition_id(session, condition_id)
    if record is None:
        record = models.Resolution(**payload)
        session.add(record)
    else:
        for field, value in payload.items():
            setattr(record, field, value)
    return record


def get_quote(session: Session, quote_id: str) -> models.Quote | None:
    """Return a stored pricing quote."""

    return session.get(models.Quote, quote_id)


def create_quote(session: Session, data: Mapping[str, Any]) -> models.Quote:
    """Persist a freshly issued pricing quote."""

    payload = dict(data)
    quote_id = payload["quote_id"]
    existing = session.get(models.Quote, quote_id)
    if existing is not None:
        raise ValueError(f"quote {quote_id} already exists")
    record = models.Quote(**payload)
    session.add(record)
    return record


def mark_quote_status(
    session: Session,
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


def expire_stale_quotes(session: Session, *, now: datetime | None = None) -> int:
    """Mark any expired quotes as stale so cap calculations stay accurate."""

    reference = now or datetime.now(UTC)
    stmt = select(models.Quote).where(
        models.Quote.status == models.QuoteStatusEnum.ISSUED.value,
        models.Quote.expires_at < reference,
    )
    count = 0
    for quote in session.scalars(stmt):
        quote.status = models.QuoteStatusEnum.EXPIRED.value
        session.add(quote)
        count += 1
    return count


def sum_quote_stakes(
    session: Session,
    *,
    market_id: str | None = None,
    user_id: str | None = None,
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
    if user_id:
        stmt = stmt.where(models.Quote.user_id == user_id)
    if window_seconds and window_seconds > 0:
        cutoff = datetime.now(UTC) - timedelta(seconds=window_seconds)
        stmt = stmt.where(models.Quote.created_at >= cutoff)
    return Decimal(session.scalar(stmt) or 0)


def get_schema_version(session: Session, key: str = DEFAULT_SCHEMA_VERSION_KEY) -> models.SchemaVersion | None:
    """Fetch the recorded schema version for the provided key."""

    return session.get(models.SchemaVersion, key)


def record_schema_version(session: Session, revision: str, key: str = DEFAULT_SCHEMA_VERSION_KEY) -> str | None:
    """Persist the current schema revision and return the previous value if present."""

    previous_revision: str | None = None
    record = get_schema_version(session, key)
    now = datetime.now(UTC)
    if record is None:
        record = models.SchemaVersion(key=key, revision=revision, applied_at=now)
        session.add(record)
        return None
    previous_revision = record.revision
    record.revision = revision
    record.applied_at = now
    return previous_revision


def apply_market_summary(
    session: Session,
    event_id: str,
    *,
    summary: str,
    source: str,
    model: str,
    metadata: Mapping[str, Any] | None,
    checked_at: datetime,
) -> models.Market:
    """Persist AI-generated summary metadata onto a market row."""

    market = get_market_by_event_id(session, event_id)
    if market is None:
        raise ValueError(f"market {event_id} not found")
    market.summary = summary
    market.summary_source = source
    market.summary_model = model
    market.summary_metadata = dict(metadata or {})
    market.summary_checked_at = checked_at
    market.summary_requested_at = None
    session.add(market)
    return market


def upsert_settlement_snapshot(session: Session, market_id: int, data: Mapping[str, Any]) -> models.Settlement:
    """Insert or update a settlement snapshot for a market."""

    settlement = session.execute(
        select(models.Settlement).where(models.Settlement.market_id == market_id)
    ).scalar_one_or_none()
    payload = dict(data)
    if settlement is None:
        settlement = models.Settlement(market_id=market_id)
    for field, value in payload.items():
        if hasattr(settlement, field):
            setattr(settlement, field, value)
    session.add(settlement)
    return settlement


def record_commitments(session: Session, market_id: int, tickets: list[Mapping[str, Any]]) -> int:
    """Persist commitments (and merkle siblings) for a market, skipping duplicates."""

    count = 0
    existing_hashes = {
        row[0]
        for row in session.execute(
            select(models.Commitment.ticket_hash).where(models.Commitment.market_id == market_id)
        ).all()
    }
    for ticket in tickets:
        ticket_hash = str(ticket.get("ticketHash") or ticket.get("ticket_hash") or "").lower()
        if not ticket_hash or ticket_hash in existing_hashes:
            continue
        commitment = models.Commitment(
            market_id=market_id,
            user_address=str(ticket.get("user") or ticket.get("user_address") or "").lower(),
            outcome_id=int(ticket.get("outcomeId") or ticket.get("outcome_id") or 0),
            amount_wei=int(ticket.get("amount") or ticket.get("amount_wei") or 0),
            salt=str(ticket.get("salt") or "0x0"),
            ticket_hash=ticket_hash,
            leaf=str(ticket.get("leaf") or ""),
            leaf_index=int(ticket.get("merkleIndex") or ticket.get("leaf_index") or 0),
        )
        session.add(commitment)
        session.flush()
        siblings = ticket.get("merklePath") or ticket.get("merkle_path") or []
        for level, sibling in enumerate(siblings):
            session.add(
                models.CommitmentMerklePath(
                    commitment_id=commitment.id,
                    level=level,
                    sibling_hash=str(sibling),
                )
            )
        count += 1
    return count


def record_factory_event(
    session: Session,
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
        existing = session.execute(
            select(models.FactoryEvent).where(
                models.FactoryEvent.tx_hash == normalized_tx,
                models.FactoryEvent.event == event,
            )
        ).scalar_one_or_none()
    if existing:
        return existing
    normalized_market = market_address.lower() if isinstance(market_address, str) else None
    if normalized_market:
        market_exists = session.execute(
            select(models.Market.market_address).where(models.Market.market_address == normalized_market)
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


def record_settlement_receipt(
    session: Session,
    *,
    market_id: int,
    market_address: str | None,
    request_id: str,
    proof_hash: str | None,
    public_signals: list[str] | None,
    prover_version: str | None,
    circuit_hash: str | None,
    generated_at: datetime | None,
) -> models.SettlementReceipt:
    """Persist a prover receipt for downstream automation/audits."""

    existing = session.execute(
        select(models.SettlementReceipt).where(
            models.SettlementReceipt.market_id == market_id,
            models.SettlementReceipt.request_id == request_id,
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    receipt = models.SettlementReceipt(
        market_id=market_id,
        market_address=market_address.lower() if isinstance(market_address, str) else None,
        request_id=request_id,
        proof_hash=proof_hash,
        public_signals=public_signals or [],
        prover_version=prover_version,
        circuit_hash=circuit_hash,
        generated_at=generated_at,
    )
    session.add(receipt)
    return receipt
