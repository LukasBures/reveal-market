from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from shared import repository_async as shared_repository
from sqlalchemy import and_, case, exists, func, literal_column, or_, over, select
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
            closes_after=closes_after,
            closes_before=closes_before,
        )
    stmt = select(models.Market).options(
        selectinload(models.Market.outcomes_rel),
        selectinload(models.Market.tags_rel),
        selectinload(models.Market.clob_tokens_rel),
        selectinload(models.Market.gamma_metadata_rel),
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
    live_case = case(
        (
            and_(
                models.Market.status == models.MarketStatusEnum.COMMIT.value,
                or_(models.Market.closes_at.is_(None), models.Market.closes_at > now),
                or_(models.Market.commits_blocked_at.is_(None), models.Market.commits_blocked_at > now),
            ),
            1,
        ),
    )
    finalized_case = case(
        (models.Market.resolution_status == models.ResolutionStatusEnum.FINAL.value, 1),
    )
    stmt = select(
        func.count(models.Market.id).label("total"),
        func.count(live_case).label("live"),
        func.count(finalized_case).label("finalized"),
    )
    row = (await session.execute(stmt)).one()
    total, live, finalized = int(row.total), int(row.live), int(row.finalized)
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
    stmt = (
        select(models.Market)
        .options(
            selectinload(models.Market.outcomes_rel),
            selectinload(models.Market.tags_rel),
            selectinload(models.Market.clob_tokens_rel),
            selectinload(models.Market.gamma_metadata_rel),
        )
        .where(models.Market.event_id == event_id)
    )
    return (await session.scalars(stmt)).first()


async def get_market_by_condition_id(session: AsyncSession, condition_id: str) -> models.Market | None:
    stmt = (
        select(models.Market)
        .options(
            selectinload(models.Market.outcomes_rel),
            selectinload(models.Market.tags_rel),
            selectinload(models.Market.clob_tokens_rel),
            selectinload(models.Market.gamma_metadata_rel),
        )
        .where(models.Market.condition_id == condition_id)
    )
    return (await session.scalars(stmt)).first()


async def get_markets_by_group_slug(session: AsyncSession, group_slug: str, *, limit: int = 500) -> list[models.Market]:
    normalized_slug = (group_slug or "").strip().lower()
    if not normalized_slug:
        return []
    stmt = (
        select(models.Market)
        .options(
            selectinload(models.Market.outcomes_rel),
            selectinload(models.Market.tags_rel),
            selectinload(models.Market.clob_tokens_rel),
            selectinload(models.Market.gamma_metadata_rel),
        )
        .outerjoin(models.MarketGammaMetadata, models.MarketGammaMetadata.market_id == models.Market.id)
        .where(
            or_(
                models.Market.group_slug == normalized_slug,
                models.MarketGammaMetadata.group_slug == normalized_slug,
            )
        )
        .order_by(models.Market.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows: list[models.Market] = list(result.unique().scalars().all())
    return rows


async def get_markets_by_group_slug_pattern(
    session: AsyncSession, pattern: str, *, limit: int = 500
) -> list[models.Market]:
    """LIKE-based lookup: ``will-elon-musk-post-tweets`` becomes
    ``%will%elon%musk%post%tweets%`` so all range variants match."""
    if not pattern or not pattern.strip():
        return []
    like_expr = "%" + "%".join(pattern.strip().lower().split("-")) + "%"
    stmt = (
        select(models.Market)
        .options(
            selectinload(models.Market.outcomes_rel),
            selectinload(models.Market.tags_rel),
            selectinload(models.Market.clob_tokens_rel),
            selectinload(models.Market.gamma_metadata_rel),
        )
        .outerjoin(models.MarketGammaMetadata, models.MarketGammaMetadata.market_id == models.Market.id)
        .where(
            or_(
                models.Market.group_slug.ilike(like_expr),
                models.MarketGammaMetadata.group_slug.ilike(like_expr),
            )
        )
        .order_by(models.Market.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.unique().scalars().all())


async def get_markets_by_public_event_id(session: AsyncSession, public_id: str) -> list[models.Market]:
    normalized = (public_id or "").strip().lower()
    if not normalized:
        return []
    stmt = (
        select(models.Market)
        .options(
            selectinload(models.Market.outcomes_rel),
            selectinload(models.Market.tags_rel),
            selectinload(models.Market.clob_tokens_rel),
            selectinload(models.Market.gamma_metadata_rel),
        )
        .where(models.Market.public_event_id == normalized)
        .order_by(models.Market.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.unique().scalars().all())


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
            selectinload(models.Market.gamma_metadata_rel),
        )
        .where(models.Market.event_key == normalized_key)
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
        stmt = stmt.where(func.lower(models.Market.category) == normalized_category)
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
    closes_after: datetime | None = None,
    closes_before: datetime | None = None,
) -> list[models.Market]:
    group_expr = _volume_group_expression()
    volume_expr = _volume_value_expression()

    # CTE: compute group-level totals with filters applied once.
    group_stmt = (
        select(
            group_expr.label("volume_group"),
            func.coalesce(func.sum(volume_expr), 0).label("total_volume"),
            func.max(models.Market.updated_at).label("last_updated_at"),
            func.max(models.Market.created_at).label("last_created_at"),
        )
        .select_from(models.Market)
        .outerjoin(models.MarketGammaMetadata, models.MarketGammaMetadata.market_id == models.Market.id)
    )
    group_stmt = _apply_common_filters(group_stmt, status=status, category=category, oracle=oracle, featured=featured)
    group_stmt = _apply_text_search(session, group_stmt, search, apply_default_order=False)
    if closes_after or closes_before:
        group_stmt = group_stmt.where(models.Market.closes_at.isnot(None))
        if closes_after:
            group_stmt = group_stmt.where(models.Market.closes_at >= closes_after)
        if closes_before:
            group_stmt = group_stmt.where(models.Market.closes_at <= closes_before)
    group_cte = (
        group_stmt.group_by(group_expr)
        .order_by(
            func.coalesce(func.sum(volume_expr), 0).desc(),
            func.max(models.Market.updated_at).desc(),
            func.max(models.Market.created_at).desc(),
        )
        .offset(offset)
        .limit(limit)
    ).cte("group_volumes")

    # Fetch market IDs ordered by group volume via CTE join.
    id_stmt = (
        select(models.Market.id)
        .outerjoin(models.MarketGammaMetadata, models.MarketGammaMetadata.market_id == models.Market.id)
        .join(group_cte, group_expr == group_cte.c.volume_group)
    )
    id_stmt = _apply_common_filters(id_stmt, status=status, category=category, oracle=oracle, featured=featured)
    id_stmt = _apply_text_search(session, id_stmt, search, apply_default_order=False)
    if closes_after or closes_before:
        id_stmt = id_stmt.where(models.Market.closes_at.isnot(None))
        if closes_after:
            id_stmt = id_stmt.where(models.Market.closes_at >= closes_after)
        if closes_before:
            id_stmt = id_stmt.where(models.Market.closes_at <= closes_before)
    id_stmt = id_stmt.order_by(
        group_cte.c.total_volume.desc(),
        group_cte.c.last_updated_at.desc(),
        group_cte.c.last_created_at.desc(),
        _volume_value_expression().desc(),
        models.Market.updated_at.desc(),
    )
    id_rows = await session.execute(id_stmt)
    market_ids = [row[0] for row in id_rows]
    if not market_ids:
        return []

    # Fetch full objects with relationships only for matching IDs.
    stmt = (
        select(models.Market)
        .options(
            selectinload(models.Market.outcomes_rel),
            selectinload(models.Market.tags_rel),
            selectinload(models.Market.clob_tokens_rel),
            selectinload(models.Market.gamma_metadata_rel),
        )
        .where(models.Market.id.in_(market_ids))
    )
    result = await session.execute(stmt)
    rows: list[models.Market] = list(result.unique().scalars().all())

    # Preserve the CTE-driven order.
    id_order = {mid: idx for idx, mid in enumerate(market_ids)}
    rows.sort(key=lambda m: id_order.get(m.id, len(id_order)))
    return rows


async def get_grouped_events(
    session: AsyncSession,
    *,
    status: str | None = None,
    category: str | None = None,
    oracle: str | None = None,
    search: str | None = None,
    featured: bool | None = None,
    limit: int = 20,
    offset: int = 0,
    order_by: str | None = None,
    closes_after: datetime | None = None,
    closes_before: datetime | None = None,
) -> list[models.Market]:
    """Fetch one representative market per group using SQL window functions.

    This avoids the 3-4x over-fetch by selecting the best candidate per group
    at the DB level (via ``ROW_NUMBER() OVER (PARTITION BY group_key)``),
    paginating those, then eagerly loading relationships only for survivors.
    """
    group_expr = _volume_group_expression()
    volume_expr = _volume_value_expression()

    # Determine ordering for the representative selection (within each group).
    inner_order: tuple[Any, ...]
    if order_by == "volume":
        inner_order = (volume_expr.desc(), models.Market.updated_at.desc())
    else:
        inner_order = (models.Market.created_at.desc(),)

    # Build an inner query that numbers rows within each group.
    inner = (
        select(
            models.Market.id,
            group_expr.label("_grp"),
            over(
                func.row_number(),
                partition_by=group_expr,
                order_by=inner_order,
            ).label("_rn"),
        )
        .select_from(models.Market)
        .outerjoin(models.MarketGammaMetadata, models.MarketGammaMetadata.market_id == models.Market.id)
    )
    inner = _apply_common_filters(inner, status=status, category=category, oracle=oracle, featured=featured)
    inner = _apply_text_search(session, inner, search, apply_default_order=False)
    if closes_after or closes_before:
        inner = inner.where(models.Market.closes_at.isnot(None))
        if closes_after:
            inner = inner.where(models.Market.closes_at >= closes_after)
        if closes_before:
            inner = inner.where(models.Market.closes_at <= closes_before)
    inner = inner.subquery("ranked")

    # Select only the best representative per group (_rn == 1) and paginate.
    winner_ids_stmt = select(inner.c.id).where(inner.c._rn == 1).order_by(inner.c._grp).offset(offset).limit(limit)
    id_rows = await session.execute(winner_ids_stmt)
    winner_ids = [row[0] for row in id_rows]
    if not winner_ids:
        return []

    # Fetch full market objects with relationships only for winners.
    stmt = (
        select(models.Market)
        .options(
            selectinload(models.Market.outcomes_rel),
            selectinload(models.Market.tags_rel),
            selectinload(models.Market.clob_tokens_rel),
            selectinload(models.Market.gamma_metadata_rel),
        )
        .where(models.Market.id.in_(winner_ids))
    )
    result = await session.execute(stmt)
    rows: list[models.Market] = list(result.unique().scalars().all())

    # Preserve the paginated order.
    id_order = {mid: idx for idx, mid in enumerate(winner_ids)}
    rows.sort(key=lambda m: id_order.get(m.id, len(id_order)))
    return rows


async def search_markets(
    session: AsyncSession, query: str, limit: int, *, active_only: bool = True
) -> list[models.Market]:
    stmt = select(models.Market).options(
        selectinload(models.Market.outcomes_rel),
        selectinload(models.Market.tags_rel),
        selectinload(models.Market.clob_tokens_rel),
        selectinload(models.Market.gamma_metadata_rel),
    )
    if active_only:
        stmt = stmt.where(
            models.Market.status.in_(
                [
                    models.MarketStatusEnum.COMMIT.value,
                    models.MarketStatusEnum.LOCKED.value,
                ]
            )
        )
    stmt = _apply_text_search(session, stmt, query or "")
    stmt = stmt.limit(limit)
    result = await session.scalars(stmt)
    return list(result)


def _apply_text_search(session: AsyncSession, stmt, search: str | None, apply_default_order: bool = True):
    search_value = (search or "").strip()
    if not search_value:
        return stmt.order_by(models.Market.created_at.desc()) if apply_default_order else stmt

    pattern = f"%{search_value}%"
    gamma_title_match = exists().where(
        models.MarketGammaMetadata.market_id == models.Market.id,
        models.MarketGammaMetadata.group_item_title.ilike(pattern),
    )
    fallback_clause = or_(
        models.Market.title.ilike(pattern),
        models.Market.slug.ilike(pattern),
        models.Market.category.ilike(pattern),
        models.Market.oracle.ilike(pattern),
        gamma_title_match,
    )

    if _supports_full_text(session):
        vector: Any = literal_column("markets.search_vector")
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
