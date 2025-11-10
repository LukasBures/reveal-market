from __future__ import annotations

from typing import List, Optional

from shared import repository as shared_repository
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

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
    stmt = select(models.Market)
    if status:
        stmt = stmt.where(models.Market.status == status)
    if category:
        stmt = stmt.where(func.lower(models.Market.category) == category.lower())
    if oracle:
        stmt = stmt.where(models.Market.oracle == oracle)
    stmt = _apply_text_search(session, stmt, search)
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


def get_market_by_condition_id(session: Session, condition_id: str) -> Optional[models.Market]:
    stmt = select(models.Market).where(models.Market.condition_id == condition_id)
    return session.scalars(stmt).first()


def get_resolution_by_condition_id(session: Session, condition_id: str) -> Optional[models.Resolution]:
    stmt = select(models.Resolution).where(models.Resolution.condition_id == condition_id)
    return session.scalars(stmt).first()


def create_or_update_market(session: Session, market_in: schemas.MarketCreate) -> models.Market:
    return shared_repository.upsert_market(session, market_in.model_dump())


def patch_market(session: Session, market: models.Market, update: schemas.MarketUpdate) -> models.Market:
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(market, field, value)
    return market


def search_markets(session: Session, query: str, limit: int) -> List[models.Market]:
    stmt = select(models.Market)
    stmt = _apply_text_search(session, stmt, query or "")
    stmt = stmt.limit(limit)
    return list(session.scalars(stmt))


def get_markets_by_tag(session: Session, tag: str, limit: int) -> List[models.Market]:
    normalized = (tag or "").strip().lower()
    if not normalized:
        return []
    pattern = f'%"{normalized}"%'
    stmt = (
        select(models.Market)
        .where(func.lower(cast(models.Market.tags, String)).like(pattern))
        .order_by(models.Market.created_at.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def _apply_text_search(session: Session, stmt, search: Optional[str]):
    search_value = (search or "").strip()
    if not search_value:
        return stmt.order_by(models.Market.created_at.desc())

    pattern = f"%{search_value}%"
    fallback_clause = or_(
        models.Market.title.ilike(pattern),
        models.Market.slug.ilike(pattern),
        models.Market.category.ilike(pattern),
        models.Market.oracle.ilike(pattern),
    )

    if _supports_full_text(session):
        vector = func.to_tsvector(
            "english",
            func.concat_ws(
                " ",
                func.coalesce(models.Market.title, ""),
                func.coalesce(models.Market.slug, ""),
                func.coalesce(models.Market.category, ""),
                func.coalesce(models.Market.oracle, ""),
            ),
        )
        query = func.websearch_to_tsquery("english", search_value)
        stmt = stmt.where(or_(vector.op("@@")(query), fallback_clause))
        rank = func.ts_rank_cd(vector, query)
        return stmt.order_by(rank.desc(), models.Market.created_at.desc())

    stmt = stmt.where(fallback_clause)
    return stmt.order_by(models.Market.created_at.desc())


def _supports_full_text(session: Session) -> bool:
    bind = session.get_bind()
    if bind is None:
        return False
    return bind.dialect.name == "postgresql"
