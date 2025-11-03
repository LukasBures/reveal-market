from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared import repository as shared_repository

from . import models, schemas


def get_markets(
    session: Session,
    *,
    status: Optional[str] = None,
    category: Optional[str] = None,
    oracle: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[models.Market]:
    stmt = select(models.Market).order_by(models.Market.created_at.desc())
    if status:
        stmt = stmt.where(models.Market.status == status)
    if category:
        stmt = stmt.where(models.Market.category == category)
    if oracle:
        stmt = stmt.where(models.Market.oracle == oracle)
    if search:
        stmt = stmt.where(models.Market.title.ilike(f"%{search}%"))
    stmt = stmt.offset(offset).limit(limit)
    return list(session.scalars(stmt))


def get_market_stats(session: Session) -> List[schemas.MarketStatusBreakdown]:
    stmt = (
        select(models.Market.status, func.count(models.Market.id))
        .group_by(models.Market.status)
        .order_by(models.Market.status.asc())
    )
    rows = session.execute(stmt).all()
    return [schemas.MarketStatusBreakdown(status=row[0], count=row[1]) for row in rows]


def get_market_by_event_id(session: Session, event_id: str) -> Optional[models.Market]:
    return shared_repository.get_market_by_event_id(session, event_id)


def create_or_update_market(session: Session, market_in: schemas.MarketCreate) -> models.Market:
    return shared_repository.upsert_market(session, market_in.model_dump())


def patch_market(session: Session, market: models.Market, update: schemas.MarketUpdate) -> models.Market:
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(market, field, value)
    return market
