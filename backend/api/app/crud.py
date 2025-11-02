from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models, schemas


def get_markets(session: Session, status: Optional[str] = None, limit: int = 100) -> List[models.Market]:
    stmt = select(models.Market).order_by(models.Market.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(models.Market.status == status)
    return list(session.scalars(stmt))


def get_market_by_event_id(session: Session, event_id: str) -> Optional[models.Market]:
    stmt = select(models.Market).where(models.Market.event_id == event_id)
    return session.scalars(stmt).first()


def create_or_update_market(session: Session, market_in: schemas.MarketCreate) -> models.Market:
    market = get_market_by_event_id(session, market_in.event_id)
    if market is None:
        market = models.Market(**market_in.dict())
        session.add(market)
    else:
        for field, value in market_in.dict().items():
            setattr(market, field, value)
    return market


def patch_market(session: Session, market: models.Market, update: schemas.MarketUpdate) -> models.Market:
    for field, value in update.dict(exclude_unset=True).items():
        setattr(market, field, value)
    return market
