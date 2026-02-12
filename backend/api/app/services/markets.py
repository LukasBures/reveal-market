"""Market service helpers for cache hydration, enrichment, and normalization.

These functions keep caching logic centralized so routes stay thin and async,
handling Redis tagging, cache TTL rules for resolved markets, and DB lookups for
outcomes, tags, and Gamma metadata.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from urllib.parse import unquote_plus

from app import crud, models, schemas
from app.database import session_scope
from app.runtime import (
    TRENDING_MIN_LIQUIDITY,
    TRENDING_MIN_ORDERBOOK,
    TRENDING_MIN_SCORE,
    TRENDING_MIN_TRADES,
    TRENDING_MIN_VOLUME_24H,
    logger,
    settings,
)
from app.services.cache_client import get_cache_client
from redis.asyncio import Redis
from redis.exceptions import RedisError
from shared.cache_async import add_tag, get_json, get_json_many, get_schema_tag, invalidate_tag, set_json
from shared.cache_keys import (
    group_cache_key,
    market_stats_cache_key,
    markets_list_cache_key,
)
from shared.categories import canonical_category_from_slug
from shared.logging import log_event
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

MARKETS_STATS_KEY = "v1:markets:stats"
MARKET_DETAIL_PREFIX = "v1:markets:detail"


def derive_group_key(market: schemas.MarketResponse) -> tuple[str, str | None]:
    """Return the group key and optional display title for event grouping."""

    event_key = (getattr(market, "event_key", None) or "").strip().lower()
    if event_key:
        return event_key, None
    slug = (getattr(market, "group_slug", None) or "").strip().lower()
    if slug:
        return slug, None
    event_id = (getattr(market, "event_id", None) or "").strip()
    if event_id:
        return event_id.lower(), None
    return "unknown", None


def build_resolution_summary_from_record(
    record: models.Resolution,
    market: models.Market | schemas.MarketResponse | None = None,
    market_outcomes: list[str] | None = None,
) -> schemas.ResolutionSummary:
    """Convert a Resolution row into the API schema, filling gaps from market data."""

    outcomes = market_outcomes or []
    payouts = record.payouts or []
    winners = record.winners or derive_winners_from_payouts(payouts, outcomes)
    winning_outcome_id = record.winning_outcome_id
    if winning_outcome_id is None and winners:
        winning_outcome_id = winners[0].get("index")
    checked_at = record.checked_at or record.created_at
    payload: dict[str, object] = {
        "source": record.source,
        "condition_id": record.condition_id,
        "resolved": record.resolved,
        "outcomes": outcomes or [],
        "payouts": payouts or [],
        "winners": winners or [],
        "checked_at": checked_at,
        "market_id": getattr(record, "market_id", None),
        "event_id": record.event_id or (market.event_id if market else None),
        "title": market.title if market else None,
        "slug": market.slug if market else None,
        "oracle": record.oracle or (market.oracle if market else None),
        "question_id": record.question_id,
        "transaction_hash": record.transaction_hash,
        "block_number": record.block_number,
        "block_timestamp": record.block_timestamp,
        "winning_outcome_id": winning_outcome_id,
        "rake_bps": record.rake_bps if record.rake_bps is not None else getattr(market, "rake_bps", None),
        "request_id": record.request_id,
        "created_at": getattr(record, "created_at", None),
        "updated_at": getattr(record, "updated_at", None),
    }
    return schemas.ResolutionSummary.model_validate(payload)


def derive_winners_from_payouts(payouts: list[int] | None, outcomes: list[str] | None) -> list[dict[str, Any]]:
    """Derive winner metadata from a list of payout amounts."""

    winners: list[dict[str, Any]] = []
    if not payouts:
        return winners
    valid_payouts: list[tuple[int, int]] = []
    for index, raw in enumerate(payouts):
        try:
            value = int(raw)
        except (TypeError, ValueError):
            logger.debug("Skipping payout that cannot be coerced to int", exc_info=True)
            value = None
        if value is None:
            continue
        valid_payouts.append((index, value))
    if not valid_payouts:
        return winners
    max_value = max(value for _, value in valid_payouts)
    if max_value <= 0:
        return winners
    labels = outcomes or []
    for index, value in valid_payouts:
        if value == max_value:
            label = labels[index] if index < len(labels) else None
            winners.append({"index": index, "label": label, "payout": value})
    return winners


def build_market_caps() -> schemas.MarketCaps:
    """Return the current stake caps derived from settings."""

    return schemas.MarketCaps(
        max_stake_zen=Decimal(str(settings.max_stake_zen)),
        max_user_stake_per_market_zen=Decimal(str(settings.max_user_stake_per_market_zen)),
        max_market_stake_zen=Decimal(str(settings.max_market_stake_zen)),
    )


def filter_markets_for_visibility(
    markets: list[schemas.MarketResponse], *, hide_settled: bool = False
) -> list[schemas.MarketResponse]:
    """Apply visibility rules (category allowlist, skip closed, de-dupe by event_id).

    hide_settled controls whether settled/cancelled markets are stripped (used for active feeds),
    while detail pages and broad listings can keep them.
    """

    category_allow = {item.lower() for item in settings.market_category_allowlist if isinstance(item, str)}
    disallowed_statuses = {
        models.MarketStatusEnum.SETTLED.value.lower(),
        models.MarketStatusEnum.CANCELLED.value.lower(),
    }
    allowed_statuses = {status.value.lower() for status in models.MarketStatusEnum}
    if hide_settled:
        allowed_statuses.difference_update(disallowed_statuses)
    else:
        allowed_statuses.update(disallowed_statuses)
    allowed_statuses.update({"", "active", "open", "live", "resolved"})
    filtered: list[schemas.MarketResponse] = []
    seen_events: set[str] = set()
    settled_filtered = 0

    for market in markets:
        # Filter by category allowlist when configured.
        if category_allow:
            if not isinstance(market.category, str) or market.category.lower() not in category_allow:
                continue

        status_normalized = str(getattr(market, "status", "") or "").lower()
        # When hide_settled is requested (homepage/active feeds), only expose commit-state markets.
        if hide_settled:
            if status_normalized != models.MarketStatusEnum.COMMIT.value:
                settled_filtered += 1
                continue

        # Skip explicitly closed markets and records with unknown statuses for other feeds.
        if getattr(market, "closed", False) is True or (
            status_normalized and status_normalized not in allowed_statuses
        ):
            continue

        event_id = getattr(market, "event_id", None)
        if isinstance(event_id, str):
            if event_id in seen_events:
                continue
            seen_events.add(event_id)

        filtered.append(market)

    removed = len(markets) - len(filtered)
    if removed > 0:
        log_event(
            logger,
            logging.DEBUG,
            event="markets.list.filtered",
            message="filtered markets via visibility rules",
            removed=removed,
            remaining=len(filtered),
            category_allowlist=list(category_allow) if category_allow else None,
            settled_filtered=settled_filtered or None,
        )
    return filtered


def market_record_cache_key(event_id: str) -> str:
    return f"market:{event_id}"


def market_detail_cache_key(event_id: str) -> str:
    return f"{MARKET_DETAIL_PREFIX}:{event_id}"


def resolved_cache_ttl(status: str | None, resolved_at: datetime | None) -> int:
    """Compute cache TTL; resolved markets expire 12 hours after resolution."""

    resolved = resolved_at
    if isinstance(resolved_at, str):
        try:
            resolved = datetime.fromisoformat(resolved_at.replace("Z", "+00:00"))
        except ValueError:
            resolved = None
    if status and status.lower() in {"settled", "cancelled"} and isinstance(resolved, datetime):
        delta = (resolved - datetime.now(tz=UTC)) + timedelta(hours=12)
        seconds = int(delta.total_seconds())
        if seconds <= 0:
            return 0
        return min(seconds, settings.market_record_cache_ttl_seconds)
    return settings.market_record_cache_ttl_seconds


def should_cache_market_list(limit: int, offset: int, search_query: str | None, order_by: str | None = None) -> bool:
    """Gate caching so deep pagination/search traffic doesn't pollute Redis."""

    normalized_order_by = "volume" if order_by == "volume_24h_usd" else order_by
    if search_query:
        return False
    if normalized_order_by == "volume" and (
        offset >= settings.cache_hydrate_limit or offset + limit > settings.cache_hydrate_limit
    ):
        return False
    if offset > settings.cacheable_market_offset_limit:
        return False
    return limit <= settings.cacheable_market_limit


def sanitize_market_response(market: schemas.MarketResponse) -> dict[str, Any]:
    payload = market.model_dump(mode="json")
    return payload


async def hydrate_cached_market_list(cache: Redis | None, cached_payload: Any) -> list[schemas.MarketResponse] | None:
    """Rehydrate cached list payloads into MarketResponse models."""

    if cached_payload is None:
        return None
    if isinstance(cached_payload, list):
        return [schemas.MarketResponse.model_validate(item) for item in cached_payload]
    if isinstance(cached_payload, dict):
        event_ids = cached_payload.get("event_ids")
        if not isinstance(event_ids, list):
            return None
        markets: list[schemas.MarketResponse] = []
        for event_id in event_ids:
            if not isinstance(event_id, str):
                return None
            record = await get_json(cache, market_record_cache_key(event_id))
            if record is None:
                return None
            markets.append(schemas.MarketResponse.model_validate(record))
        return markets
    return None


async def write_market_list_cache(cache: Redis | None, cache_key: str, markets: list[schemas.MarketResponse]) -> None:
    """Write list payload and per-market detail caches with tagging."""

    if cache is None or not markets:
        return
    event_ids: list[str] = []
    for market in markets:
        sanitized = sanitize_market_response(market)
        event_id = sanitized.get("event_id")
        if not isinstance(event_id, str):
            continue
        event_ids.append(event_id)
        condition_id = sanitized.get("condition_id")
        record_key = market_record_cache_key(event_id)
        ttl_seconds = resolved_cache_ttl(sanitized.get("status"), sanitized.get("resolved_at"))
        if ttl_seconds > 0:
            await set_json(cache, record_key, sanitized, ttl_seconds)
            await add_tag(cache, f"market:{event_id}", record_key)
            if isinstance(condition_id, str):
                await add_tag(cache, f"resolution:{condition_id.lower()}", record_key)
    if not event_ids:
        return
    payload = {
        "event_ids": event_ids,
        "generated_at": datetime.now(tz=UTC).isoformat(),
    }
    await set_json(cache, cache_key, payload, settings.cache_ttl_seconds)


def decode_slug(value: str) -> str:
    """Decode percent-encoded slugs from URLs into normalized strings."""

    return unquote_plus(value or "").strip()


def slugify_value(value: str) -> str:
    """Lowercase and dash-separate arbitrary strings for consistent grouping."""

    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def build_event_responses(
    markets: list[schemas.MarketResponse], *, coalesce_groups: bool = True
) -> list[schemas.EventResponse]:
    """Build event responses for list endpoints."""

    if not coalesce_groups:
        events: list[schemas.EventResponse] = []
        for market in markets:
            event_id = (getattr(market, "event_id", None) or "unknown").strip()
            group_slug = (
                getattr(market, "event_key", None) or getattr(market, "group_slug", None) or ""
            ).strip().lower() or event_id
            events.append(
                schemas.EventResponse(
                    event_id=event_id,
                    title=market.title,
                    category=market.category,
                    group_slug=group_slug,
                    image_url=market.image_url,
                    starts_at=market.starts_at,
                    closes_at=market.closes_at,
                    markets=[market],
                    aggregate_volume_24h_usd=market.volume_24h_usd,
                    aggregate_volume_total_usd=market.volume
                    if market.volume is not None
                    else market.orderbook_volume_usd,
                    aggregate_liquidity_usd=market.liquidity_usd,
                )
            )
        return events

    grouped: dict[str, list[schemas.MarketResponse]] = {}
    group_titles: dict[str, str | None] = {}
    for market in markets:
        key, title_override = derive_group_key(market)
        grouped.setdefault(key, []).append(market)
        if title_override and key not in group_titles:
            group_titles[key] = title_override

    grouped_events: list[schemas.EventResponse] = []
    for key, items in grouped.items():
        items.sort(
            key=lambda item: (
                safe_float(getattr(item, "group_position", None))
                if safe_float(getattr(item, "group_position", None)) is not None
                else float("inf"),
                getattr(item, "event_id", "") or "",
            )
        )
        primary = items[0]
        volumes = [item.volume_24h_usd for item in items if item.volume_24h_usd is not None]
        liquidities = [item.liquidity_usd for item in items if item.liquidity_usd is not None]
        aggregate_volume: float | None
        aggregate_liquidity: float | None
        if volumes and len({float(value) for value in volumes}) == 1:
            aggregate_volume = float(volumes[0])
        else:
            aggregate_volume = float(sum(volumes)) if volumes else None
        total_volumes = [item.volume for item in items if item.volume is not None]
        if total_volumes and len({float(value) for value in total_volumes}) == 1:
            aggregate_volume_total = float(total_volumes[0])
        else:
            aggregate_volume_total = float(sum(total_volumes)) if total_volumes else None
        if liquidities and len({float(value) for value in liquidities}) == 1:
            aggregate_liquidity = float(liquidities[0])
        else:
            aggregate_liquidity = float(sum(liquidities)) if liquidities else None
        if aggregate_volume is None and primary.volume_24h_usd is not None:
            aggregate_volume = primary.volume_24h_usd
        if aggregate_volume_total is None and primary.volume is not None:
            aggregate_volume_total = primary.volume
        if aggregate_volume_total is None and primary.orderbook_volume_usd is not None:
            aggregate_volume_total = primary.orderbook_volume_usd
        if aggregate_liquidity is None and primary.liquidity_usd is not None:
            aggregate_liquidity = primary.liquidity_usd
        if aggregate_volume_total is not None and aggregate_volume is None:
            aggregate_volume = aggregate_volume_total
        title_value = group_titles.get(key) or primary.title
        grouped_events.append(
            schemas.EventResponse(
                event_id=key,
                title=title_value,
                category=primary.category,
                group_slug=key,
                image_url=primary.image_url,
                starts_at=primary.starts_at,
                closes_at=primary.closes_at,
                markets=items,
                aggregate_volume_24h_usd=aggregate_volume,
                aggregate_volume_total_usd=aggregate_volume_total,
                aggregate_liquidity_usd=aggregate_liquidity,
            )
        )
    return grouped_events


def apply_market_caps(market: schemas.MarketResponse) -> None:
    """Attach stake caps to a market model if missing."""

    if getattr(market, "caps", None) is None:
        market.caps = build_market_caps()


def safe_float(value: Any) -> float | None:
    """Coerce values to float while discarding NaNs and invalid inputs."""

    if value is None:
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return None if numeric != numeric else numeric  # NaN guard
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return None if numeric != numeric else numeric


def safe_int(value: Any) -> int | None:
    """Coerce values to int while ignoring invalid inputs."""

    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _apply_market_stats(target: schemas.MarketResponse | schemas.MarketSibling, stats: dict[str, Any]) -> None:
    if not stats:
        return
    value_map = {
        "best_bid": safe_float,
        "best_ask": safe_float,
        "spread": safe_float,
        "volume": safe_float,
        "open_interest": safe_float,
        "liquidity_usd": safe_float,
        "volume_24h_usd": safe_float,
        "orderbook_volume_usd": safe_float,
        "trades_quantity": safe_int,
    }
    for field, converter in value_map.items():
        raw = stats.get(field)
        if raw is None:
            continue
        parsed = converter(raw)
        if parsed is not None and hasattr(target, field):
            setattr(target, field, parsed)


async def _fetch_market_stats(cache: Redis | None, event_ids: list[str]) -> dict[str, dict[str, Any]]:
    if cache is None or not event_ids:
        return {}
    key_map = {event_id: market_stats_cache_key(event_id) for event_id in event_ids if event_id}
    if not key_map:
        return {}
    raw = await get_json_many(cache, list(key_map.values()))
    stats: dict[str, dict[str, Any]] = {}
    for event_id, key in key_map.items():
        payload = raw.get(key)
        if isinstance(payload, dict):
            stats[event_id] = payload
    return stats


def _group_slug_expression():
    return func.coalesce(models.Market.event_key, models.Market.group_slug, models.MarketGammaMetadata.group_slug)


def _total_volume_expression():
    return func.coalesce(
        models.MarketGammaMetadata.volume,
        models.MarketGammaMetadata.volume_clob,
        models.Market.orderbook_volume_usd,
        0,
    )


def normalize_datetime(dt: datetime | None) -> datetime | None:
    """Ensure datetimes are timezone-aware (UTC) for deterministic comparisons."""

    if dt is None:
        return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=UTC)
    return dt


async def load_group_aggregates(session: AsyncSession, slugs: set[str]) -> dict[str, dict[str, float | None]]:
    """Aggregate liquidity/volume for all markets in provided group slugs."""

    if not slugs:
        return {}
    aggregates: dict[str, dict[str, float | None]] = {}
    cache = await get_cache_client()
    if cache is None:
        group_expr = _group_slug_expression()
        total_volume_expr = _total_volume_expression()
        stmt = (
            select(
                group_expr.label("group_slug"),
                func.sum(models.Market.volume_24h_usd),
                func.sum(models.Market.liquidity_usd),
                func.sum(total_volume_expr),
            )
            .outerjoin(models.MarketGammaMetadata, models.MarketGammaMetadata.market_id == models.Market.id)
            .where(group_expr.in_(list(slugs)))
            .group_by(group_expr)
        )
        result = await session.execute(stmt)
        for slug, volume_sum, liquidity_sum, total_sum in result:
            if not slug:
                continue
            aggregates[slug] = {
                "volume_24h_usd": safe_float(volume_sum),
                "liquidity_usd": safe_float(liquidity_sum),
                "volume_total": safe_float(total_sum),
            }
        return aggregates

    group_expr = _group_slug_expression()
    stmt = (
        select(
            models.Market.event_id,
            group_expr.label("group_slug"),
            models.Market.volume_24h_usd,
            models.Market.liquidity_usd,
            models.Market.orderbook_volume_usd,
            models.MarketGammaMetadata.volume,
            models.MarketGammaMetadata.volume_clob,
        )
        .outerjoin(models.MarketGammaMetadata, models.MarketGammaMetadata.market_id == models.Market.id)
        .where(group_expr.in_(list(slugs)))
    )
    slug_map: dict[str, list[str]] = {}
    fallback: dict[str, dict[str, float | None]] = {}
    event_ids: list[str] = []
    result = await session.execute(stmt)
    for event_id, slug, volume_24h_usd, liquidity_usd, orderbook_volume_usd, volume_total, volume_clob in result:
        if not slug or not event_id:
            continue
        event_id = str(event_id)
        slug_map.setdefault(slug, []).append(event_id)
        event_ids.append(event_id)
        fallback[event_id] = {
            "volume_24h_usd": safe_float(volume_24h_usd),
            "liquidity_usd": safe_float(liquidity_usd),
            "volume_total": safe_float(volume_total) or safe_float(volume_clob) or safe_float(orderbook_volume_usd),
        }

    stats_map = await _fetch_market_stats(cache, event_ids)

    def _sum_values(values: Iterable[float | None]) -> float | None:
        total = 0.0
        has_value = False
        for value in values:
            if value is None:
                continue
            total += float(value)
            has_value = True
        return total if has_value else None

    for slug, events in slug_map.items():
        volume_values: list[float | None] = []
        liquidity_values: list[float | None] = []
        total_values: list[float | None] = []
        for event_id in events:
            stats = stats_map.get(event_id)
            fallback_values = fallback.get(event_id, {})
            volume_value = safe_float(stats.get("volume_24h_usd")) if stats else None
            liquidity_value = safe_float(stats.get("liquidity_usd")) if stats else None
            total_value = None
            if stats:
                total_value = safe_float(stats.get("volume"))
                if total_value is None:
                    total_value = safe_float(stats.get("orderbook_volume_usd"))
            volume_values.append(volume_value if volume_value is not None else fallback_values.get("volume_24h_usd"))
            liquidity_values.append(
                liquidity_value if liquidity_value is not None else fallback_values.get("liquidity_usd")
            )
            total_values.append(total_value if total_value is not None else fallback_values.get("volume_total"))
        if not events:
            continue
        aggregates[slug] = {
            "volume_24h_usd": _sum_values(volume_values),
            "liquidity_usd": _sum_values(liquidity_values),
            "volume_total": _sum_values(total_values),
        }
    return aggregates


async def get_group_siblings(session: AsyncSession, group_slug: str) -> list[schemas.MarketSibling]:
    """Return sibling markets for a given group slug, caching the payload."""

    normalized = (group_slug or "").strip().lower()
    if not normalized:
        return []
    cache = await get_cache_client()
    cache_key = group_cache_key(normalized)
    cached = await get_json(cache, cache_key)
    if cached is not None:
        try:
            return [schemas.MarketSibling.model_validate(item) for item in cached]
        except (ValueError, TypeError) as exc:  # pragma: no cover - defensive cache parse
            log_event(
                logger,
                logging.DEBUG,
                event="markets.group.cache_parse_failed",
                message="failed to parse cached siblings payload",
                group_slug=normalized,
                error=str(exc),
            )

    result = await session.execute(select(models.Market).where(models.Market.event_key == normalized))
    markets = result.scalars().all()
    if not markets:
        return []
    ids = [m.id for m in markets if m.id is not None]
    outcome_map: dict[int, list[models.MarketOutcome]] = {}
    if ids:
        outcome_rows = (
            await session.execute(
                select(models.MarketOutcome)
                .where(models.MarketOutcome.market_id.in_(ids))
                .order_by(models.MarketOutcome.market_id, models.MarketOutcome.outcome_id)
            )
        ).scalars()
        for row in outcome_rows:
            outcome_map.setdefault(row.market_id, []).append(row)
    meta_map: dict[int, models.MarketGammaMetadata] = {}
    if ids:
        meta_rows = (
            await session.execute(
                select(models.MarketGammaMetadata).where(models.MarketGammaMetadata.market_id.in_(ids))
            )
        ).scalars()
        meta_map = {row.market_id: row for row in meta_rows}

    cache = await get_cache_client()
    event_ids = [record.event_id for record in markets if isinstance(record.event_id, str)]
    stats_map = await _fetch_market_stats(cache, event_ids)

    siblings_raw: list[tuple[schemas.MarketSibling, datetime | None, str | None, float | None]] = []
    for record in markets:
        meta = meta_map.get(record.id)
        outcomes = outcome_map.get(getattr(record, "id", -1), [])
        prices_raw = [float(row.price) if row.price is not None else None for row in outcomes]
        title_value = getattr(meta, "group_item_title", None) if meta else None
        position = getattr(record, "group_position", None)
        outcome_prices: list[float] | None = None
        if any(p is not None for p in prices_raw):
            outcome_prices = [float(p) for p in prices_raw if p is not None]

        stats = stats_map.get(record.event_id) if isinstance(record.event_id, str) else None
        liquidity_value = safe_float(stats.get("liquidity_usd")) if stats else None
        volume_value = safe_float(stats.get("volume_24h_usd")) if stats else None

        sibling = schemas.MarketSibling(
            event_id=record.event_id,
            title=record.title,
            group_item_title=title_value,
            group_item_threshold=None,
            group_position=position,
            outcome_prices=outcome_prices,
            liquidity_usd=liquidity_value if liquidity_value is not None else safe_float(record.liquidity_usd),
            volume_24h_usd=volume_value if volume_value is not None else safe_float(record.volume_24h_usd),
        )
        siblings_raw.append(
            (
                sibling,
                normalize_datetime(getattr(record, "closes_at", None)),
                getattr(record, "slug", None) or sibling.event_id,
                position,
            )
        )

    def _sort_key(item: tuple[schemas.MarketSibling, datetime | None, str | None, float | None]):
        sibling, closes_at, slug_value, position_value = item
        primary = position_value if position_value is not None else float("inf")
        close_ts = closes_at or datetime.max.replace(tzinfo=UTC)
        return primary, close_ts, slug_value or sibling.event_id

    siblings_raw.sort(key=_sort_key)
    siblings = [item[0] for item in siblings_raw]
    if cache is not None and siblings:
        try:
            schema_tag = await get_schema_tag(cache, settings.schema_version_key)
            await set_json(
                cache, cache_key, [sib.model_dump(mode="json") for sib in siblings], settings.cache_ttl_seconds
            )
            await add_tag(cache, schema_tag, cache_key)
            await add_tag(cache, "markets:group", cache_key)
            await add_tag(cache, f"group:{normalized}", cache_key)
        except (RedisError, TypeError, ValueError) as exc:  # pragma: no cover - cache best-effort
            if logger.isEnabledFor(logging.DEBUG):
                log_event(
                    logger,
                    logging.DEBUG,
                    event="markets.group.cache_write_failed",
                    message="failed to persist siblings cache payload",
                    group_slug=normalized,
                    error=str(exc),
                )
    return siblings


def sum_sibling_volume(siblings: list[schemas.MarketSibling]) -> float | None:
    """Sum volume across sibling markets while ignoring missing values."""

    total = 0.0
    any_value = False
    for sibling in siblings:
        value = safe_float(getattr(sibling, "volume_24h_usd", None))
        if value is not None:
            total += value
            any_value = True
    return total if any_value else None


def sum_sibling_liquidity(siblings: list[schemas.MarketSibling]) -> float | None:
    """Sum liquidity across sibling markets while ignoring missing values."""

    total = 0.0
    any_value = False
    for sibling in siblings:
        value = safe_float(getattr(sibling, "liquidity_usd", None))
        if value is not None:
            total += value
            any_value = True
    return total if any_value else None


def market_volume_value(market: schemas.MarketResponse, *, use_total: bool = False) -> float:
    if use_total:
        primary = getattr(market, "volume", None)
        fallback = getattr(market, "orderbook_volume_usd", None)
    else:
        primary = getattr(market, "volume_24h_usd", None)
        fallback = getattr(market, "orderbook_volume_usd", None)
    value = safe_float(primary)
    if value is None:
        value = safe_float(fallback)
    return value or 0.0


def coalesce_grouped_markets(
    markets: list[schemas.MarketResponse], *, use_total_volume: bool = False
) -> list[schemas.MarketResponse]:
    """Collapse markets sharing a group into a single representative."""

    grouped: dict[str, schemas.MarketResponse] = {}
    standalone: list[schemas.MarketResponse] = []

    def _prefer_candidate(candidate: schemas.MarketResponse, incumbent: schemas.MarketResponse) -> bool:
        cand_volume = market_volume_value(candidate, use_total=use_total_volume)
        inc_volume = market_volume_value(incumbent, use_total=use_total_volume)
        if cand_volume > inc_volume:
            return True
        if cand_volume < inc_volume:
            return False
        cand_pos_raw = getattr(candidate, "group_position", None)
        inc_pos_raw = getattr(incumbent, "group_position", None)
        cand_pos = safe_float(cand_pos_raw)
        inc_pos = safe_float(inc_pos_raw)
        if cand_pos is not None and inc_pos is not None:
            if cand_pos < inc_pos:
                return True
            if cand_pos > inc_pos:
                return False
        elif cand_pos is not None:
            return True
        elif inc_pos is not None:
            return False
        cand_event = getattr(candidate, "event_id", "") or ""
        inc_event = getattr(incumbent, "event_id", "") or ""
        return cand_event < inc_event

    for market in markets:
        slug = getattr(market, "event_key", None) or getattr(market, "group_slug", None)
        if not slug:
            standalone.append(market)
            continue
        existing = grouped.get(slug)
        if existing is None or _prefer_candidate(market, existing):
            grouped[slug] = market
    return standalone + list(grouped.values())


async def attach_group_fields(
    session: AsyncSession, markets: list[schemas.MarketResponse], *, include_siblings: bool = False
) -> None:
    """Populate group-level aggregates and siblings onto market models."""

    slug_map: dict[str, list[schemas.MarketResponse]] = {}
    for market in markets:
        slug = getattr(market, "event_key", None) or getattr(market, "group_slug", None)
        if not slug:
            continue
        slug_map.setdefault(slug, []).append(market)
    if not slug_map:
        return
    aggregates = await load_group_aggregates(session, set(slug_map.keys()))
    for slug, group_markets in slug_map.items():
        siblings: list[schemas.MarketSibling] | None = None
        if include_siblings:
            siblings = await get_group_siblings(session, slug)
        aggregate = aggregates.get(slug)
        aggregate_volume = aggregate.get("volume_24h_usd") if aggregate else None
        aggregate_volume_total = aggregate.get("volume_total") if aggregate else None
        aggregate_liquidity = aggregate.get("liquidity_usd") if aggregate else None
        if siblings is not None:
            aggregate_volume = aggregate_volume or sum_sibling_volume(siblings)
            aggregate_liquidity = aggregate_liquidity or sum_sibling_liquidity(siblings)
        for market in group_markets:
            if siblings is not None:
                market.siblings = siblings
            if aggregate_volume is not None:
                market.volume_24h_usd = aggregate_volume
            if aggregate_volume_total is not None:
                market.volume = aggregate_volume_total
            if aggregate_liquidity is not None:
                market.liquidity_usd = aggregate_liquidity


async def load_normalized_fields(session: AsyncSession, markets: list[schemas.MarketResponse]) -> None:
    """Populate outcomes, prices, tags, clob tokens, and gamma metadata onto market models."""

    id_map: dict[int, schemas.MarketResponse] = {}
    for market in markets:
        mid = getattr(market, "id", None)
        if isinstance(mid, int):
            id_map[mid] = market
    if not id_map:
        return
    market_ids = list(id_map.keys())
    event_ids = [target.event_id for target in id_map.values() if isinstance(getattr(target, "event_id", None), str)]
    cache = await get_cache_client()
    stats_map = await _fetch_market_stats(cache, event_ids)

    outcome_rows = (
        await session.execute(
            select(models.MarketOutcome)
            .where(models.MarketOutcome.market_id.in_(market_ids))
            .order_by(models.MarketOutcome.market_id, models.MarketOutcome.outcome_id)
        )
    ).scalars()
    outcome_map: dict[int, list[models.MarketOutcome]] = {}
    for outcome_row in outcome_rows:
        mid = getattr(outcome_row, "market_id", None)
        try:
            mid_int = int(mid) if mid is not None else None
        except (TypeError, ValueError):
            mid_int = None
        if mid_int is None:
            continue
        outcome_map.setdefault(mid_int, []).append(outcome_row)
    for mid, target in id_map.items():
        outcomes = outcome_map.get(mid, [])
        labels = [outcome_row.label for outcome_row in outcomes]
        prices_raw = [float(outcome_row.price) if outcome_row.price is not None else None for outcome_row in outcomes]
        target.outcomes = labels or None
        target.outcome_prices = (
            [float(price) for price in prices_raw if price is not None]
            if any(p is not None for p in prices_raw)
            else None
        )

    tag_rows = (
        await session.execute(
            select(models.MarketTag).where(models.MarketTag.market_id.in_(market_ids)).order_by(models.MarketTag.tag)
        )
    ).scalars()
    tag_map: dict[int, list[str]] = {}
    tag_iter: Iterable[models.MarketTag] = cast(Iterable[models.MarketTag], tag_rows)
    for tag_row in tag_iter:
        mid = getattr(tag_row, "market_id", None)
        try:
            mid_int = int(mid) if mid is not None else None
        except (TypeError, ValueError):
            mid_int = None
        if mid_int is None or tag_row.tag is None:
            continue
        tag_map.setdefault(mid_int, []).append(str(tag_row.tag))
    for mid, target in id_map.items():
        target.tags = tag_map.get(mid) or None

    token_rows = (
        await session.execute(
            select(models.MarketClobToken)
            .where(models.MarketClobToken.market_id.in_(market_ids))
            .order_by(models.MarketClobToken.id)
        )
    ).scalars()
    token_map: dict[int, list[str]] = {}
    token_iter: Iterable[models.MarketClobToken] = cast(Iterable[models.MarketClobToken], token_rows)
    for token_row in token_iter:
        mid = getattr(token_row, "market_id", None)
        try:
            mid_int = int(mid) if mid is not None else None
        except (TypeError, ValueError):
            mid_int = None
        if mid_int is None or not token_row.token_id:
            continue
        token_map.setdefault(mid_int, []).append(str(token_row.token_id))
    for mid, target in id_map.items():
        tokens = token_map.get(mid, [])
        target.clob_token_ids = tokens or None

    meta_rows = (
        await session.execute(
            select(models.MarketGammaMetadata).where(models.MarketGammaMetadata.market_id.in_(market_ids))
        )
    ).scalars()
    meta_map: dict[int, models.MarketGammaMetadata] = {}
    meta_iter: Iterable[models.MarketGammaMetadata] = cast(Iterable[models.MarketGammaMetadata], meta_rows)
    for meta_row in meta_iter:
        mid = getattr(meta_row, "market_id", None)
        try:
            mid_int = int(mid) if mid is not None else None
        except (TypeError, ValueError):
            mid_int = None
        if mid_int is None:
            continue
        meta_map[mid_int] = meta_row
    for mid, target in id_map.items():
        meta = meta_map.get(mid)
        if not meta:
            continue
        if meta.description:
            target.description = meta.description
        if meta.resolution_source:
            target.resolution_source = meta.resolution_source
        gamma_token_ids: list[str] = []
        if meta.clob_token_id_yes:
            gamma_token_ids.append(str(meta.clob_token_id_yes))
        if meta.clob_token_id_no:
            gamma_token_ids.append(str(meta.clob_token_id_no))
        if gamma_token_ids:
            target.clob_token_ids = gamma_token_ids
        if meta.order_price_min_tick_size is not None:
            target.price_tick_size = Decimal(str(meta.order_price_min_tick_size))
        if meta.order_min_size is not None:
            target.order_min_size = Decimal(str(meta.order_min_size))
        if meta.enable_order_book is not None:
            target.enable_order_book = meta.enable_order_book
        if meta.best_bid is not None:
            target.best_bid = float(meta.best_bid)
        if meta.best_ask is not None:
            target.best_ask = float(meta.best_ask)
        if meta.spread is not None:
            target.spread = float(meta.spread)
        try:
            if meta.volume is not None:
                target.volume = float(meta.volume)
        except (TypeError, ValueError):
            target.volume = target.volume if hasattr(target, "volume") else None
        try:
            if meta.liquidity is not None:
                target.liquidity_usd = float(meta.liquidity)
        except (TypeError, ValueError):
            target.liquidity_usd = target.liquidity_usd or None
        try:
            if meta.volume is not None:
                target.volume_24h_usd = float(meta.volume)
        except (TypeError, ValueError):
            target.volume_24h_usd = target.volume_24h_usd or None
        try:
            if meta.volume_clob is not None:
                target.orderbook_volume_usd = float(meta.volume_clob)
            elif meta.volume is not None:
                target.orderbook_volume_usd = float(meta.volume)
        except (TypeError, ValueError):
            target.orderbook_volume_usd = target.orderbook_volume_usd or None
        if meta.group_slug and not getattr(target, "group_slug", None):
            target.group_slug = meta.group_slug
        if meta.group_item_title and not getattr(target, "group_item_title", None):
            target.group_item_title = meta.group_item_title
        if isinstance(getattr(target, "event_id", None), str):
            stats = stats_map.get(target.event_id)
            if stats:
                _apply_market_stats(target, stats)


def attach_resolution_to_market(
    market: schemas.MarketResponse,
    resolution: models.Resolution | None = None,
) -> None:
    if resolution is None or market is None:
        return
    try:
        market.resolution = build_resolution_summary_from_record(resolution, market=market)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="markets.resolution.hydrate_failed",
            message="failed to attach resolution to market",
            event_id=getattr(market, "event_id", None),
            condition_id=getattr(resolution, "condition_id", None),
            error=str(exc),
        )
        return


def attach_settlement_to_resolution(
    summary: schemas.ResolutionSummary | None, settlement: models.Settlement | None = None
) -> None:
    if summary is None or settlement is None:
        return
    summary.proof_status = settlement.proof_status
    summary.proof_request_id = settlement.proof_request_id
    summary.proof_hash = settlement.proof_hash
    summary.submission_status = settlement.submission_status
    summary.settlement_tx_hash = settlement.settlement_tx_hash
    summary.settlement_submitted_at = settlement.settlement_submitted_at
    summary.merkle_root = settlement.merkle_root


def augment_market_models(markets: list[schemas.MarketResponse]) -> list[schemas.MarketResponse]:
    for market in markets:
        apply_market_caps(market)
    return markets


def compute_market_popularity(market: schemas.MarketResponse) -> float:
    """Weighted popularity score combining liquidity, volume, orderbook, and trades."""

    def clamp(value: Any) -> float:
        try:
            if value is None:
                return 0.0
            numeric = float(value)
            return numeric if numeric > 0 else 0.0
        except (TypeError, ValueError):
            return 0.0

    liquidity = clamp(getattr(market, "liquidity_usd", None))
    volume = clamp(getattr(market, "volume_24h_usd", None))
    orderbook = clamp(getattr(market, "orderbook_volume_usd", None))
    trades = clamp(getattr(market, "trades_quantity", None))
    score = (liquidity**0.5) * 0.4 + (volume**0.5) * 0.35 + (orderbook**0.5) * 0.2 + (trades**0.5) * 0.05
    return score if score > 0 and score == score else 0.0


def is_trending_market(market: schemas.MarketResponse, popularity: float | None = None) -> bool:
    """Apply minimum thresholds to decide whether a market is trending-worthy."""

    liquidity = getattr(market, "liquidity_usd", None) or 0
    volume = getattr(market, "volume_24h_usd", None) or 0
    orderbook = getattr(market, "orderbook_volume_usd", None) or 0
    trades = getattr(market, "trades_quantity", None) or 0
    popularity = popularity if popularity is not None else compute_market_popularity(market)
    return (
        popularity >= TRENDING_MIN_SCORE
        and liquidity >= TRENDING_MIN_LIQUIDITY
        and volume >= TRENDING_MIN_VOLUME_24H
        and (orderbook >= TRENDING_MIN_ORDERBOOK or orderbook == 0)
        and (trades >= TRENDING_MIN_TRADES or trades == 0)
    )


async def load_resolution_records(
    session: AsyncSession, markets: list[schemas.MarketResponse]
) -> dict[str, models.Resolution]:
    """Fetch resolution rows for a set of condition ids and return a lookup map."""

    condition_ids = []
    for market in markets:
        condition = getattr(market, "condition_id", None)
        if isinstance(condition, str):
            condition_ids.append(condition.lower())
    if not condition_ids:
        return {}
    stmt = select(models.Resolution).where(models.Resolution.condition_id.in_(condition_ids))
    records: dict[str, models.Resolution] = {}
    for record in await session.scalars(stmt):
        if record.condition_id:
            records[record.condition_id.lower()] = record
    return records


async def load_outcomes_for_market(
    session: AsyncSession, market: models.Market | schemas.MarketResponse | None
) -> list[str]:
    """Return ordered outcome labels for a market id, or an empty list."""

    if market is None:
        return []
    mid = getattr(market, "id", None)
    if not isinstance(mid, int):
        return []
    rows = (
        await session.execute(
            select(models.MarketOutcome.label)
            .where(models.MarketOutcome.market_id == mid)
            .order_by(models.MarketOutcome.outcome_id)
        )
    ).scalars()
    return list(rows)


async def load_settlement_records(
    session: AsyncSession, markets: list[schemas.MarketResponse]
) -> dict[int, models.Settlement]:
    """Fetch settlement rows for a set of market ids."""

    market_ids = [getattr(market, "id", None) for market in markets if getattr(market, "id", None)]
    if not market_ids:
        return {}
    stmt = select(models.Settlement).where(models.Settlement.market_id.in_(market_ids))
    records: dict[int, models.Settlement] = {}
    for record in await session.scalars(stmt):
        if record.market_id is not None:
            records[int(record.market_id)] = record
    return records


def attach_settlement_to_market(
    market: schemas.MarketResponse,
    settlement: models.Settlement | None = None,
) -> None:
    if market is None or settlement is None:
        return
    market.merkle_root = settlement.merkle_root
    market.commitments_count = settlement.commitments_count
    market.batch_roots = settlement.batch_roots
    market.batch_counts = settlement.batch_counts
    market.proof_status = settlement.proof_status
    market.proof_request_id = settlement.proof_request_id
    market.proof_hash = settlement.proof_hash
    market.submission_status = settlement.submission_status
    market.settlement_tx_hash = settlement.settlement_tx_hash
    market.settlement_submitted_at = settlement.settlement_submitted_at


async def enrich_market_models(
    session: AsyncSession, markets: list[schemas.MarketResponse], *, include_siblings: bool = False
) -> list[schemas.MarketResponse]:
    """Attach normalized fields, group data, caps, and resolutions to markets."""

    await load_normalized_fields(session, markets)
    await attach_group_fields(session, markets, include_siblings=include_siblings)
    augment_market_models(markets)
    resolution_map = await load_resolution_records(session, markets)
    settlement_map = await load_settlement_records(session, markets)
    for market in markets:
        condition = getattr(market, "condition_id", None)
        if isinstance(condition, str):
            resolution = resolution_map.get(condition.lower())
            if resolution:
                attach_resolution_to_market(market, resolution)
        settlement = settlement_map.get(getattr(market, "id", 0))
        if settlement:
            attach_settlement_to_market(market, settlement)
    return markets


async def fallback_markets_by_category_slug(
    session: AsyncSession, slug: str, limit: int
) -> list[schemas.MarketResponse]:
    """Fetch markets when canonical category labels fail by matching on slugified category."""

    normalized = slug.strip().lower()
    if not normalized:
        return []
    buffer_size = min(settings.max_page_size * 2, max(limit * 2, settings.default_page_size))
    candidates = await crud.get_markets(session, limit=buffer_size, offset=0)
    matched: list[schemas.MarketResponse] = []
    for candidate in candidates:
        category_value = getattr(candidate, "category", None) or ""
        matched_slug = slugify_value(str(category_value)) == normalized
        if matched_slug:
            matched.append(schemas.MarketResponse.model_validate(candidate))
            if len(matched) >= limit:
                break
    if matched:
        log_event(
            logger,
            logging.INFO,
            event="markets.category.fallback",
            message="populated category via slug fallback",
            category_slug=normalized,
            fallback_count=len(matched),
        )
        matched = await enrich_market_models(session, matched)
    return matched


def canonical_category_lookup(raw: str) -> tuple[str, str] | None:
    return canonical_category_from_slug(raw)


async def invalidate_market_cache(
    event_id: str | None = None,
    condition_id: str | None = None,
    group_slug: str | None = None,
    event_key: str | None = None,
) -> None:
    """Invalidate all cache tags touching a market/detail/resolution/group."""

    cache = await get_cache_client()
    log_event(
        logger,
        logging.DEBUG,
        event="markets.cache.invalidate",
        message="invalidating markets cache",
        event_id=event_id,
        condition_id=condition_id,
    )
    await invalidate_tag(cache, "markets:list")
    await invalidate_tag(cache, "markets:stats")
    await invalidate_tag(cache, "markets:category")
    await invalidate_tag(cache, "markets:tag")
    await invalidate_tag(cache, "markets:suggest")
    await invalidate_tag(cache, "markets:group")
    if event_id:
        await invalidate_tag(cache, f"market:{event_id}")
    if condition_id:
        await invalidate_tag(cache, f"resolution:{condition_id.lower()}")
    if group_slug:
        await invalidate_tag(cache, f"group:{group_slug}")
    if event_key:
        await invalidate_tag(cache, f"group:{event_key}")


async def hydrate_markets_cache(
    source: str = "manual",
    *,
    limit: int | None = None,
    order_by: str | None = None,
    status: str | None = "active",
    coalesce_groups: bool = True,
) -> dict[str, Any]:
    """Populate the hottest markets into Redis directly from Postgres."""

    cache = await get_cache_client()
    target_limit = limit or settings.cache_hydrate_limit or settings.cacheable_market_limit
    target_order_by = order_by or settings.cache_hydrate_order_by
    if target_order_by == "volume_24h_usd":
        target_order_by = "volume"
    target_status = status or "active"
    summary = {
        "source": source,
        "status": "skipped",
        "limit": target_limit,
        "order_by": target_order_by,
        "status_filter": target_status,
        "coalesce_groups": coalesce_groups,
    }
    if cache is None:
        summary["reason"] = "redis_unavailable"
        return summary
    if target_limit is None or target_limit <= 0:
        summary["reason"] = "invalid_limit"
        return summary
    hydrated_limit = min(
        max(1, int(target_limit)),
        settings.cacheable_market_limit,
        settings.max_page_size,
    )
    start_time = time.perf_counter()
    lock_key = "lock:markets_cache:hydrate"
    lock_acquired = False
    lock_ttl = max(30, settings.cache_ttl_seconds)
    if cache is not None:
        try:
            lock_acquired = bool(await cache.set(lock_key, "1", ex=lock_ttl, nx=True))
        except RedisError:
            lock_acquired = False
    if cache is not None and not lock_acquired:
        summary["status"] = "skipped"
        summary["reason"] = "hydrate_in_progress"
        return summary
    try:
        async with session_scope() as session:
            records = await crud.get_markets(
                session,
                status=target_status,
                limit=hydrated_limit,
                offset=0,
                order_by=target_order_by,
                coalesce_groups=coalesce_groups,
            )
            market_models = filter_markets_for_visibility(
                await enrich_market_models(session, [schemas.MarketResponse.model_validate(m) for m in records])
            )
        if coalesce_groups:
            market_models = coalesce_grouped_markets(market_models, use_total_volume=target_order_by == "volume")
        if target_order_by == "volume":
            market_models.sort(
                key=lambda m: (
                    market_volume_value(m, use_total=True),
                    getattr(m, "updated_at", None) or datetime.fromtimestamp(0, tz=UTC),
                ),
                reverse=True,
            )
        if not market_models:
            summary["reason"] = "no_markets"
            return summary
        max_items = min(len(market_models), settings.cache_hydrate_limit)
        market_models = market_models[:max_items]
        schema_tag = await get_schema_tag(cache, settings.schema_version_key)
        cache_key = markets_list_cache_key(
            target_status,
            None,
            None,
            None,
            hydrated_limit,
            0,
            order_by=target_order_by,
            coalesce_groups=coalesce_groups,
        )
        await write_market_list_cache(cache, cache_key, market_models)
        await add_tag(cache, schema_tag, cache_key)
        await add_tag(cache, "markets:list", cache_key)

        page_size = min(
            max(1, settings.cache_hydrate_page_size),
            settings.cacheable_market_limit,
            settings.max_page_size,
            hydrated_limit,
        )
        total_to_cache = min(len(market_models), settings.cache_hydrate_limit)
        page_cache_keys: list[str] = []
        for start in range(0, total_to_cache, page_size):
            slice_items = market_models[start : start + page_size]
            slice_key = markets_list_cache_key(
                target_status,
                None,
                None,
                None,
                page_size,
                start,
                order_by=target_order_by,
                coalesce_groups=coalesce_groups,
            )
            await write_market_list_cache(cache, slice_key, slice_items)
            await add_tag(cache, schema_tag, slice_key)
            await add_tag(cache, "markets:list", slice_key)
            page_cache_keys.append(slice_key)

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        log_event(
            logger,
            logging.INFO,
            event="markets.cache.hydrate",
            message="hydrated markets cache from database",
            source=source,
            limit=hydrated_limit,
            order_by=target_order_by,
            result_count=len(market_models),
            cache_key=cache_key,
            page_cache_keys=page_cache_keys,
            duration_ms=duration_ms,
        )
        summary.update(
            {
                "status": "hydrated",
                "limit": hydrated_limit,
                "result_count": len(market_models),
                "cache_key": cache_key,
                "page_cache_keys": page_cache_keys,
                "duration_ms": duration_ms,
            }
        )
        return summary
    finally:
        if cache is not None and lock_acquired:
            try:
                await cache.delete(lock_key)
            except RedisError:
                pass
