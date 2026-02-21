from __future__ import annotations

from datetime import UTC, datetime

from shared import repository_async as shared_repository
from sqlalchemy import func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from . import models, schemas


async def get_markets(
    session: AsyncSession,
    *,
    status: str | None = None,
    category: str | None = None,
    oracle: str | None = None,
    search: str | None = None,
    featured: bool | None = None,
    limit: int = 100,
    offset: int = 0,
    order_by: str | None = None,
    coalesce_groups: bool = False,
    closes_after: datetime | None = None,
    closes_before: datetime | None = None,
) -> list[models.Market]:
    # Always sort by lifetime volume; keep volume_24h_usd as a legacy alias.
    if order_by == "volume_24h_usd":
        order_by = "volume"
    if order_by == "volume" and coalesce_groups:
        return await _get_markets_by_total_volume(
            session,
            status=status,
            category=category,
            oracle=oracle,
            search=search,
            featured=featured,
            limit=limit,
            offset=offset,
        )
    stmt = select(models.Market).options(
        selectinload(models.Market.outcomes_rel),
        selectinload(models.Market.tags_rel),
        selectinload(models.Market.clob_tokens_rel),
    )
    stmt = _apply_common_filters(stmt, status=status, category=category, oracle=oracle, featured=featured)
    stmt = _apply_text_search(session, stmt, search, apply_default_order=order_by is None)
    if closes_after or closes_before:
        stmt = stmt.where(models.Market.closes_at.isnot(None))
        if closes_after:
            stmt = stmt.where(models.Market.closes_at >= closes_after)
        if closes_before:
            stmt = stmt.where(models.Market.closes_at <= closes_before)
    if order_by == "volume_24h_usd":
        stmt = stmt.order_by(
            models.Market.volume_24h_usd.desc(),
            models.Market.updated_at.desc(),
            models.Market.created_at.desc(),
        )
    elif order_by == "volume":
        stmt = stmt.outerjoin(models.MarketGammaMetadata).order_by(
            _volume_value_expression().desc(),
            models.Market.updated_at.desc(),
            models.Market.created_at.desc(),
        )
    else:
        stmt = stmt.order_by(models.Market.created_at.desc())
    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    rows: list[models.Market] = list(result.unique().scalars().all())
    return rows


async def get_market_stats(session: AsyncSession) -> list[schemas.MarketStatusBreakdown]:
    now = datetime.now(UTC)
    live_stmt = select(func.count(models.Market.id)).where(
        models.Market.status == models.MarketStatusEnum.COMMIT.value,
        or_(models.Market.closes_at.is_(None), models.Market.closes_at > now),
        or_(models.Market.commits_blocked_at.is_(None), models.Market.commits_blocked_at > now),
    )
    live = int((await session.execute(live_stmt)).scalar_one() or 0)

    finalized_stmt = select(func.count(models.Market.id)).where(
        models.Market.resolution_status == models.ResolutionStatusEnum.FINAL.value
    )
    finalized = int((await session.execute(finalized_stmt)).scalar_one() or 0)

    total_stmt = select(func.count(models.Market.id))
    total = int((await session.execute(total_stmt)).scalar_one() or 0)
    ended = max(total - live, 0)

    return [
        schemas.MarketStatusBreakdown(status="live", count=live),
        schemas.MarketStatusBreakdown(status="ended", count=ended),
        schemas.MarketStatusBreakdown(status="finalized", count=finalized),
        schemas.MarketStatusBreakdown(status="total", count=total),
    ]


async def count_events(
    session: AsyncSession,
    *,
    status: str | None = None,
    category: str | None = None,
    oracle: str | None = None,
    search: str | None = None,
    featured: bool | None = None,
) -> int:
    group_expr = _volume_group_expression()
    stmt = select(func.count(func.distinct(group_expr)))
    stmt = stmt.select_from(models.Market)
    stmt = stmt.outerjoin(models.MarketGammaMetadata, models.MarketGammaMetadata.market_id == models.Market.id)
    stmt = _apply_common_filters(stmt, status=status, category=category, oracle=oracle, featured=featured)
    stmt = _apply_text_search(session, stmt, search, apply_default_order=False)
    return int((await session.execute(stmt)).scalar_one() or 0)


async def get_market_by_event_id(session: AsyncSession, event_id: str) -> models.Market | None:
    stmt = select(models.Market).where(models.Market.event_id == event_id)
    return (await session.scalars(stmt)).first()


async def get_market_by_condition_id(session: AsyncSession, condition_id: str) -> models.Market | None:
    stmt = select(models.Market).where(models.Market.condition_id == condition_id)
    return (await session.scalars(stmt)).first()


async def get_markets_by_group_slug(session: AsyncSession, group_slug: str) -> list[models.Market]:
    normalized_slug = (group_slug or "").strip().lower()
    if not normalized_slug:
        return []
    stmt = (
        select(models.Market)
        .options(
            selectinload(models.Market.outcomes_rel),
            selectinload(models.Market.tags_rel),
            selectinload(models.Market.clob_tokens_rel),
        )
        .outerjoin(models.MarketGammaMetadata, models.MarketGammaMetadata.market_id == models.Market.id)
        .where(
            or_(
                func.lower(models.Market.group_slug) == literal(normalized_slug),
                func.lower(models.MarketGammaMetadata.group_slug) == literal(normalized_slug),
            )
        )
        .order_by(models.Market.created_at.desc())
    )
    result = await session.execute(stmt)
    rows: list[models.Market] = list(result.unique().scalars().all())
    return rows


async def get_markets_by_event_key(session: AsyncSession, event_key: str) -> list[models.Market]:
    normalized_key = (event_key or "").strip().lower()
    if not normalized_key:
        return []
    stmt = (
        select(models.Market)
        .options(
            selectinload(models.Market.outcomes_rel),
            selectinload(models.Market.tags_rel),
            selectinload(models.Market.clob_tokens_rel),
        )
        .where(func.lower(models.Market.event_key) == literal(normalized_key))
        .order_by(models.Market.created_at.desc())
    )
    result = await session.execute(stmt)
    rows: list[models.Market] = list(result.unique().scalars().all())
    return rows


async def get_resolution_by_condition_id(session: AsyncSession, condition_id: str) -> models.Resolution | None:
    stmt = select(models.Resolution).where(models.Resolution.condition_id == condition_id)
    return (await session.scalars(stmt)).first()


async def create_or_update_market(session: AsyncSession, market_in: schemas.MarketCreate) -> models.Market:
    return await shared_repository.upsert_market(session, market_in.model_dump())


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


async def patch_market(session: AsyncSession, market: models.Market, update: schemas.MarketUpdate) -> models.Market:
    legacy_fields = {"outcomes", "outcome_prices", "clob_token_ids"}
    for field, value in update.model_dump(exclude_unset=True).items():
        if field in legacy_fields:
            continue
        if field == "tags":
            _replace_tags(market, value)
            continue
        if hasattr(market, field):
            setattr(market, field, value)
    session.add(market)
    return market


def _apply_common_filters(stmt, *, status: str | None, category: str | None, oracle: str | None, featured: bool | None):
    if status == "active":
        stmt = stmt.where(
            models.Market.status == models.MarketStatusEnum.COMMIT.value,
        )
    elif status and status.lower() not in {"any", "all"}:
        stmt = stmt.where(models.Market.status == status)
    if category:
        normalized_category = category.lower()
        stmt = stmt.where(func.lower(models.Market.category) == literal(normalized_category))
    if oracle:
        stmt = stmt.where(models.Market.oracle == oracle)
    if featured:
        stmt = stmt.where(models.Market.featured.is_(True))
    return stmt


def _volume_group_expression():
    return func.coalesce(
        models.Market.group_slug,
        models.MarketGammaMetadata.group_slug,
        models.Market.event_key,
        models.Market.event_id,
    )


def _volume_value_expression():
    return func.coalesce(
        models.MarketGammaMetadata.volume,
        models.MarketGammaMetadata.volume_clob,
        models.Market.orderbook_volume_usd,
        0,
    )


async def _get_markets_by_total_volume(
    session: AsyncSession,
    *,
    status: str | None,
    category: str | None,
    oracle: str | None,
    search: str | None,
    featured: bool | None,
    limit: int,
    offset: int,
) -> list[models.Market]:
    group_expr = _volume_group_expression()
    volume_expr = _volume_value_expression()
    aggregate_stmt = (
        select(
            group_expr.label("volume_group"),
            func.coalesce(func.sum(volume_expr), 0).label("total_volume"),
            func.max(models.Market.updated_at).label("last_updated_at"),
            func.max(models.Market.created_at).label("last_created_at"),
        )
        .select_from(models.Market)
        .outerjoin(models.MarketGammaMetadata, models.MarketGammaMetadata.market_id == models.Market.id)
    )
    aggregate_stmt = _apply_common_filters(
        aggregate_stmt, status=status, category=category, oracle=oracle, featured=featured
    )
    aggregate_stmt = _apply_text_search(session, aggregate_stmt, search, apply_default_order=False)
    aggregate_stmt = (
        aggregate_stmt.group_by(group_expr)
        .order_by(
            func.coalesce(func.sum(volume_expr), 0).desc(),
            func.max(models.Market.updated_at).desc(),
            func.max(models.Market.created_at).desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    aggregate_rows = await session.execute(aggregate_stmt)
    group_order = [row[0] for row in aggregate_rows if row[0] is not None]
    if not group_order:
        return []

    markets_stmt = (
        select(models.Market)
        .options(
            selectinload(models.Market.outcomes_rel),
            selectinload(models.Market.tags_rel),
            selectinload(models.Market.clob_tokens_rel),
        )
        .outerjoin(models.MarketGammaMetadata, models.MarketGammaMetadata.market_id == models.Market.id)
        .where(group_expr.in_(group_order))
    )
    markets_stmt = _apply_common_filters(
        markets_stmt, status=status, category=category, oracle=oracle, featured=featured
    )
    markets_stmt = _apply_text_search(session, markets_stmt, search, apply_default_order=False)
    result = await session.execute(markets_stmt)
    rows: list[models.Market] = list(result.unique().scalars().all())

    def _group_key(market: models.Market) -> str | None:
        return (
            getattr(market, "group_slug", None)
            or getattr(market, "event_key", None)
            or getattr(market, "event_id", None)
        )

    def _volume_value(market: models.Market) -> float:
        raw = getattr(market, "orderbook_volume_usd", None)
        try:
            return float(raw) if raw is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _updated_timestamp(market: models.Market) -> float:
        timestamp = getattr(market, "updated_at", None) or getattr(market, "created_at", None)
        if isinstance(timestamp, datetime):
            try:
                return float(timestamp.timestamp())
            except (OverflowError, OSError, ValueError):
                return 0.0
        return 0.0

    order_lookup = {value: index for index, value in enumerate(group_order)}
    rows.sort(
        key=lambda market: (
            order_lookup.get(_group_key(market), len(order_lookup)),
            -_volume_value(market),
            -_updated_timestamp(market),
        )
    )
    return rows


async def search_markets(session: AsyncSession, query: str, limit: int) -> list[models.Market]:
    stmt = select(models.Market)
    stmt = _apply_text_search(session, stmt, query or "")
    stmt = stmt.limit(limit)
    result = await session.scalars(stmt)
    return list(result)


def _apply_text_search(session: AsyncSession, stmt, search: str | None, apply_default_order: bool = True):
    search_value = (search or "").strip()
    if not search_value:
        return stmt.order_by(models.Market.created_at.desc()) if apply_default_order else stmt

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
        if apply_default_order:
            rank = func.ts_rank_cd(vector, query)
            return stmt.order_by(rank.desc(), models.Market.created_at.desc())
        return stmt
    stmt = stmt.where(fallback_clause)
    return stmt.order_by(models.Market.created_at.desc()) if apply_default_order else stmt


def _supports_full_text(session: AsyncSession) -> bool:
    bind = session.get_bind()
    if bind is None:
        return False
    return bind.dialect.name == "postgresql"
