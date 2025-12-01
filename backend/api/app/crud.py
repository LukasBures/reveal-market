from __future__ import annotations

from shared import repository as shared_repository
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from . import models, schemas


def get_markets(
    session: Session,
    *,
    status: str | None = None,
    category: str | None = None,
    oracle: str | None = None,
    search: str | None = None,
    featured: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[models.Market]:
    stmt = select(models.Market).options(
        selectinload(models.Market.outcomes_rel),
        selectinload(models.Market.tags_rel),
        selectinload(models.Market.clob_tokens_rel),
        selectinload(models.Market.gamma_metadata_rel),
    )
    if status == "active":
        stmt = stmt.where(models.Market.closed.is_(False))
    elif status:
        stmt = stmt.where(models.Market.status == status)
    if category:
        stmt = stmt.where(func.lower(models.Market.category) == category.lower())
    if oracle:
        stmt = stmt.where(models.Market.oracle == oracle)
    if featured is True:
        stmt = stmt.where(models.Market.featured.is_(True))
    stmt = _apply_text_search(session, stmt, search)
    stmt = stmt.order_by(models.Market.created_at.desc())
    stmt = stmt.offset(offset).limit(limit)
    rows = session.execute(stmt).unique().scalars().all()
    return rows


def get_market_stats(session: Session) -> list[schemas.MarketStatusBreakdown]:
    stmt = select(models.Market.closed, func.count(models.Market.id)).group_by(models.Market.closed)
    rows = session.execute(stmt).all()
    live = 0
    finalized = 0
    for closed_flag, count in rows:
        if closed_flag:
            finalized += count
        else:
            live += count
    total = live + finalized
    return [
        schemas.MarketStatusBreakdown(status="live", count=live),
        schemas.MarketStatusBreakdown(status="finalized", count=finalized),
        schemas.MarketStatusBreakdown(status="total", count=total),
    ]


def get_market_by_event_id(session: Session, event_id: str) -> models.Market | None:
    return shared_repository.get_market_by_event_id(session, event_id)


def get_market_by_condition_id(session: Session, condition_id: str) -> models.Market | None:
    stmt = select(models.Market).where(models.Market.condition_id == condition_id)
    return session.scalars(stmt).first()


def get_markets_by_group_slug(session: Session, group_slug: str) -> list[models.Market]:
    stmt = (
        select(models.Market)
        .options(
            selectinload(models.Market.outcomes_rel),
            selectinload(models.Market.tags_rel),
            selectinload(models.Market.clob_tokens_rel),
            selectinload(models.Market.gamma_metadata_rel),
        )
        .where(models.Market.group_slug == group_slug)
        .order_by(models.Market.created_at.desc())
    )
    rows = session.execute(stmt).unique().scalars().all()
    return rows


def get_resolution_by_condition_id(session: Session, condition_id: str) -> models.Resolution | None:
    stmt = select(models.Resolution).where(models.Resolution.condition_id == condition_id)
    return session.scalars(stmt).first()


def create_or_update_market(session: Session, market_in: schemas.MarketCreate) -> models.Market:
    return shared_repository.upsert_market(session, market_in.model_dump())


def _replace_tags(market: models.Market, tags: list[str] | None) -> None:
    if tags is None:
        market.tags_rel = []
        return
    deduped: list[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            continue
        if tag in deduped:
            continue
        deduped.append(tag)
    market.tags_rel = [models.MarketTag(tag=tag) for tag in deduped]


def patch_market(session: Session, market: models.Market, update: schemas.MarketUpdate) -> models.Market:
    legacy_fields = {"outcomes", "outcome_prices", "clob_token_ids"}
    for field, value in update.model_dump(exclude_unset=True).items():
        if field in legacy_fields:
            continue
        if field == "tags":
            _replace_tags(market, value)
            continue
        if hasattr(market, field):
            setattr(market, field, value)
    return market


def search_markets(session: Session, query: str, limit: int) -> list[models.Market]:
    stmt = select(models.Market)
    stmt = _apply_text_search(session, stmt, query or "")
    stmt = stmt.limit(limit)
    return list(session.scalars(stmt))


def _apply_text_search(session: Session, stmt, search: str | None):
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
