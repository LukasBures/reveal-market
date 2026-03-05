"""Cache invalidation and resolution cache write helpers."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from redis.asyncio import Redis
from redis.exceptions import RedisError
from shared import cache_async as shared_cache
from shared import models as shared_models
from shared.cache_keys import group_markets_cache_key, resolution_cache_key
from shared.logging import log_event
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from . import runtime
from .metrics import CACHE_INVALIDATION_COUNTER, CacheInvalidationReport

logger = runtime.logger  # type: ignore[has-type]

if TYPE_CHECKING:
    from .market_sync import SyncSummary


async def invalidate_cache_tags(redis_client: Redis | None, summary: SyncSummary) -> CacheInvalidationReport:
    """Invalidate worker cache tags in parallel based on a SyncSummary."""
    report = CacheInvalidationReport()
    if redis_client is None:
        return report

    tags: list[str] = []
    if summary.changed_events or summary.changed_categories:
        tags.extend(["markets:list", "category:trending", "markets:suggest"])
    if summary.stats_dirty and summary.changed_events:
        tags.append("markets:stats")
    if summary.changed_group_slugs:
        tags.append("markets:group")
    for event_id in summary.changed_events:
        tags.append(f"market:{event_id}")
    for condition_id in summary.changed_conditions:
        tags.append(f"resolution:{condition_id}")
    for category_slug in summary.changed_categories:
        tags.append(f"category:{category_slug}")
    for group_slug in summary.changed_group_slugs:
        tags.append(f"group:{group_slug}")

    if tags:
        semaphore = asyncio.Semaphore(8)

        async def _invalidate_async(tag: str) -> None:
            async with semaphore:
                try:
                    removed = await shared_cache.invalidate_tag(redis_client, tag)
                    report.record(tag, removed)
                except (RedisError, RuntimeError, ValueError) as exc:  # pragma: no cover - defensive
                    log_event(
                        logger,
                        logging.WARNING,
                        event="worker.cache.invalidate_failed",
                        message="failed to invalidate cache tag",
                        tag=tag,
                        error=str(exc),
                    )

        await asyncio.gather(*(_invalidate_async(tag) for tag in tags))

    if summary.changed_categories:
        CACHE_INVALIDATION_COUNTER.labels(type="category").inc(len(summary.changed_categories))
    report.log()
    return report


async def persist_resolution_cache_updates(redis_client: Redis | None, summary: SyncSummary) -> None:
    """Write fresh resolution snapshots to Redis for downstream API reads."""
    if redis_client is None or not summary.resolution_cache_updates:
        return

    semaphore = asyncio.Semaphore(8)

    async def _write(condition_id: str, payload: dict[str, Any]) -> None:
        async with semaphore:
            try:
                await shared_cache.set_json(
                    redis_client,
                    resolution_cache_key(condition_id),
                    payload,
                    runtime.settings.markets_cache_ttl_seconds,
                )
            except (RedisError, RuntimeError, ValueError) as exc:  # pragma: no cover - defensive
                if logger.isEnabledFor(logging.DEBUG):
                    log_event(
                        logger,
                        logging.DEBUG,
                        event="worker.cache.resolution_write_failed",
                        message="failed to persist resolution cache payload",
                        condition_id=condition_id,
                        error=str(exc),
                    )

    await asyncio.gather(*(_write(condition_id, payload) for condition_id, payload in summary.resolution_cache_updates))


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _to_float(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _serialize_market_for_group_cache(market: shared_models.Market) -> dict[str, Any]:
    meta = market.gamma_metadata_rel
    outcomes = sorted(market.outcomes_rel, key=lambda row: row.outcome_id or 0) if market.outcomes_rel else []
    tags = sorted({row.tag for row in market.tags_rel if row.tag}) if market.tags_rel else []
    clob_tokens = [row.token_id for row in market.clob_tokens_rel if row.token_id] if market.clob_tokens_rel else []
    prices_raw = [row.price for row in outcomes]
    outcome_prices = None
    if any(price is not None for price in prices_raw):
        outcome_prices = [float(price) for price in prices_raw if price is not None]
    liquidity = _to_float(market.liquidity_usd)
    volume_24h = _to_float(market.volume_24h_usd)
    orderbook_volume = _to_float(market.orderbook_volume_usd)
    if meta:
        if liquidity is None:
            liquidity = _to_float(meta.liquidity)
        if volume_24h is None:
            volume_24h = _to_float(meta.volume)
        if orderbook_volume is None:
            orderbook_volume = _to_float(meta.volume_clob) or _to_float(meta.volume)
    payload: dict[str, Any] = {
        "event_id": market.event_id,
        "title": market.title,
        "category": market.category,
        "slug": market.slug,
        "metadata_uri": market.metadata_uri,
        "oracle": market.oracle,
        "factory": market.factory,
        "market_address": market.market_address,
        "status": market.status,
        "public_event_id": market.public_event_id,
        "group_slug": market.group_slug or (meta.group_slug if meta else None),
        "event_key": market.event_key,
        "group_item_title": meta.group_item_title if meta else None,
        "group_item_threshold": None,
        "group_position": market.group_position,
        "rake_bps": market.rake_bps,
        "condition_id": market.condition_id,
        "question_id": market.question_id,
        "image_url": market.image_url,
        "closed": market.closed,
        "resolution_status": market.resolution_status,
        "resolution_reason": market.resolution_reason,
        "commits_blocked_at": _to_iso(market.commits_blocked_at),
        "uma_resolution_status": market.uma_resolution_status,
        "closes_at": _to_iso(market.closes_at),
        "starts_at": _to_iso(market.starts_at),
        "orders_opened_at": _to_iso(market.orders_opened_at),
        "resolution_source": market.resolution_source or (meta.resolution_source if meta else None),
        "market_maker": market.market_maker,
        "order_min_size": _to_float(market.order_min_size),
        "price_tick_size": _to_float(market.price_tick_size),
        "enable_order_book": market.enable_order_book,
        "clob_token_ids": clob_tokens or None,
        "image_variants": market.image_variants,
        "featured": market.featured,
        "liquidity_usd": liquidity,
        "volume_24h_usd": volume_24h,
        "orderbook_volume_usd": orderbook_volume,
        "trades_quantity": market.trades_quantity,
        "best_bid": _to_float(meta.best_bid) if meta else None,
        "best_ask": _to_float(meta.best_ask) if meta else None,
        "spread": _to_float(meta.spread) if meta else None,
        "volume": _to_float(meta.volume) if meta else None,
        "outcomes": [row.label for row in outcomes] if outcomes else None,
        "outcome_prices": outcome_prices,
        "tags": tags or None,
    }
    return payload


async def persist_group_markets_cache(
    session: AsyncSession,
    redis_client: Redis | None,
    group_slugs: set[str],
    ttl_seconds: int,
) -> int:
    if redis_client is None or not group_slugs:
        return 0
    total_written = 0
    for slug in group_slugs:
        normalized = (slug or "").strip().lower()
        if not normalized:
            continue
        group_expr = func.coalesce(
            shared_models.Market.group_slug,
            shared_models.MarketGammaMetadata.group_slug,
            shared_models.Market.event_key,
        )
        stmt = (
            select(shared_models.Market)
            .options(
                selectinload(shared_models.Market.outcomes_rel),
                selectinload(shared_models.Market.tags_rel),
                selectinload(shared_models.Market.clob_tokens_rel),
                selectinload(shared_models.Market.gamma_metadata_rel),
            )
            .outerjoin(
                shared_models.MarketGammaMetadata,
                shared_models.MarketGammaMetadata.market_id == shared_models.Market.id,
            )
            .where(group_expr == normalized)
        )
        result = await session.execute(stmt)
        rows = list(result.unique().scalars().all())
        if not rows:
            continue
        rows.sort(
            key=lambda m: (
                m.group_position if m.group_position is not None else float("inf"),
                m.event_id or "",
            )
        )
        payload = [_serialize_market_for_group_cache(row) for row in rows]
        cache_key = group_markets_cache_key(normalized)
        await shared_cache.set_json(redis_client, cache_key, payload, ttl_seconds)
        await shared_cache.add_tag(redis_client, f"group:{normalized}", cache_key)
        await shared_cache.add_tag(redis_client, "markets:group", cache_key)
        total_written += 1
    return total_written
