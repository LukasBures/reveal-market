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
