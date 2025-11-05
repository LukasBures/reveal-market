from __future__ import annotations

from typing import Any, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models


def get_market_by_event_id(session: Session, event_id: str) -> Optional[models.Market]:
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


def get_resolution_by_condition_id(session: Session, condition_id: str) -> Optional[models.Resolution]:
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
