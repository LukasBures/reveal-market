from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models

DEFAULT_SCHEMA_VERSION_KEY = "core"


def get_market_by_event_id(session: Session, event_id: str) -> models.Market | None:
    """Return a market by its unique event identifier."""
    stmt = select(models.Market).where(models.Market.event_id == event_id)
    return session.scalars(stmt).first()


def upsert_market(session: Session, data: Mapping[str, Any]) -> models.Market:
    """Insert or update a market row based on the provided field mapping."""
    payload = dict(data)
    market = get_market_by_event_id(session, payload["event_id"])
    if market is None:
        market = models.Market(**payload)
        session.add(market)
    else:
        for field, value in payload.items():
            setattr(market, field, value)
    return market


def get_resolution_by_condition_id(session: Session, condition_id: str) -> models.Resolution | None:
    """Return a persisted resolution snapshot for the given condition id."""
    stmt = select(models.Resolution).where(models.Resolution.condition_id == condition_id)
    return session.scalars(stmt).first()


def upsert_resolution(session: Session, data: Mapping[str, Any]) -> models.Resolution:
    """Insert or update a resolution record."""
    payload = dict(data)
    condition_id = payload["condition_id"]
    record = get_resolution_by_condition_id(session, condition_id)
    if record is None:
        record = models.Resolution(**payload)
        session.add(record)
    else:
        for field, value in payload.items():
            setattr(record, field, value)
    return record


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
