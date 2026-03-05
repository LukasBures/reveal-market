"""Market routes and cache-aware handlers."""

from __future__ import annotations

import asyncio
import hmac
import inspect
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, cast

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from py_clob_client.client import ClobClient
from shared.cache_async import add_tag, add_tags, get_json, get_json_per, get_schema_tag, set_json
from shared.cache_keys import (
    clob_prices_history_cache_key,
    events_count_cache_key,
    markets_list_cache_key,
    resolution_cache_key,
    suggest_cache_key,
)
from shared.categories import canonical_category_from_slug
from shared.logging import log_event
from shared.onchain import OnChainConfigurationError
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud, repository_async, schemas
from app.database import get_session
from app.metrics import update_cache_context
from app.metrics_registry import MARKET_DETAIL_CACHE_COUNTER, MARKETS_CACHE_COUNTER, RESOLUTION_CACHE_COUNTER
from app.onchain import fetch_factory_markets
from app.runtime import goldsky_client, logger, settings
from app.services import markets as market_svc
from app.services.cache_client import get_cache_client, get_http_client

router = APIRouter()

CLOB_HISTORY_DEFAULT_HOST = "https://clob.polymarket.com"
CLOB_HISTORY_MAX_RANGE_SECONDS = 30 * 24 * 60 * 60
_MAX_DETAIL_MARKETS = 100
HistoryInterval = Literal["1m", "1h", "6h", "1d", "1w", "max"]


def _verify_internal_secret(secret_header: str | None) -> None:
    if not settings.internal_api_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="internal_secret_not_configured",
        )
    if not hmac.compare_digest(secret_header or "", settings.internal_api_secret.get_secret_value()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_internal_secret")


def _history_cache_ttl_seconds(interval: str | None) -> int:
    normalized = (interval or "").strip().lower()
    if normalized in {"1m", "1h"}:
        return 60
    if normalized == "6h":
        return 300
    if normalized == "1d":
        return 900
    if normalized == "1w":
        return 1800
    if normalized == "max":
        return 43200
    return 600


@router.get("/events", response_model=list[schemas.EventResponse], tags=["events"])
async def list_markets(
    request: Request,
    status: Annotated[str | None, Query(description="Filter markets by status")] = None,
    category: Annotated[str | None, Query(description="Filter markets by category")] = None,
    oracle: Annotated[str | None, Query(description="Filter markets by oracle address")] = None,
    search: Annotated[
        str | None,
        Query(min_length=2, max_length=200, description="Case-insensitive search over market titles"),
    ] = None,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=settings.max_page_size,
            description="Maximum number of markets to return",
        ),
    ] = settings.default_page_size,
    offset: Annotated[int, Query(ge=0, description="Offset into the result set")] = 0,
    order_by: Annotated[str | None, Query(description="Order results (popularity|recent|volume)")] = None,
    trending: Annotated[bool | None, Query(description="Return trending slice first")] = None,
    featured: Annotated[bool | None, Query(description="Return only featured markets", alias="only_featured")] = None,
    closes_within_hours: Annotated[
        int | None,
        Query(ge=1, le=720, description="Only return markets closing within this many hours"),
    ] = None,
    session: AsyncSession = Depends(get_session),
) -> list[schemas.EventResponse]:
    """List events with optional filters and heavy reliance on Redis caches."""

    if category:
        resolved = canonical_category_from_slug(category)
        if resolved:
            category = resolved[1]

    normalized_order_by = "volume" if order_by == "volume_24h_usd" else order_by
    popularity_mode = normalized_order_by == "popularity" or bool(trending)
    total_volume_mode = normalized_order_by == "volume"
    volume_mode = total_volume_mode
    if popularity_mode and not status:
        status = "active"
    normalized_search = search
    if search is not None:
        normalized = search.strip().lower()
        if len(normalized) > 120:
            normalized = normalized[:120]
        normalized_search = normalized
    cache_key = markets_list_cache_key(
        status,
        category,
        oracle,
        normalized_search,
        limit,
        offset,
        order_by=normalized_order_by or ("popularity" if popularity_mode else None),
        trending=trending,
        featured=featured,
        closes_within_hours=closes_within_hours,
    )
    cache = await get_cache_client()
    log_event(
        logger,
        logging.DEBUG,
        event="markets.list.request",
        message="processing markets list request",
        cache_key=cache_key,
        status=status,
        category=category,
        oracle=oracle,
        search=normalized_search,
        limit=limit,
        offset=offset,
        order_by=normalized_order_by,
        trending=bool(trending),
        featured=featured,
        closes_within_hours=closes_within_hours,
    )
    closes_after = None
    closes_before = None
    if closes_within_hours is not None:
        now = datetime.now(UTC)
        closes_after = now
        closes_before = now + timedelta(hours=closes_within_hours)
    start = time.perf_counter()
    cache_enabled = cache is not None and market_svc.should_cache_market_list(
        limit, offset, normalized_search, normalized_order_by
    )
    if cache_enabled:
        per_result = await get_json_per(cache, cache_key)
        cached_payload = per_result.data if per_result is not None else None
        hydrated = await market_svc.hydrate_cached_market_list(cache, cached_payload)
        if hydrated is not None:
            # Trigger background refresh when PER signals near-expiry (stampede protection)
            if per_result is not None and per_result.should_refresh:
                asyncio.create_task(market_svc.hydrate_markets_cache(source="per_refresh"))
            hydrated = await market_svc.enrich_market_models(session, hydrated)
            update_cache_context(request, cache_key=cache_key, hit=True, source="markets:list")
            MARKETS_CACHE_COUNTER.labels(outcome="hit", status=status or "*", category=category or "*").inc()
            duration = (time.perf_counter() - start) * 1000
            cached_models = market_svc.filter_markets_for_visibility(
                hydrated, hide_settled=(status or "").lower() == "active"
            )
            if volume_mode and cached_models:
                cached_models.sort(
                    key=lambda m: (
                        market_svc.market_volume_value(m, use_total=total_volume_mode),
                        getattr(m, "updated_at", None) or datetime.fromtimestamp(0, tz=UTC),
                    ),
                    reverse=True,
                )
            cached_events = market_svc.build_event_responses(cached_models)
            # Page caches (from hydration) are pre-sliced; trim to limit only.
            cached_events = cached_events[:limit]
            log_event(
                logger,
                logging.INFO,
                event="markets.list.cache_hit",
                message="served markets list from cache",
                cache_hit=True,
                duration_ms=round(duration, 2),
                cache_key=cache_key,
                status=status,
                category=category,
                oracle=oracle,
                search=normalized_search,
                limit=limit,
                offset=offset,
                result_count=len(cached_events),
                featured=featured,
                closes_within_hours=closes_within_hours,
            )
            return cached_events
        MARKETS_CACHE_COUNTER.labels(outcome="miss", status=status or "*", category=category or "*").inc()
        update_cache_context(request, cache_key=cache_key, hit=False, source="markets:list")
    else:
        MARKETS_CACHE_COUNTER.labels(outcome="bypass", status=status or "*", category=category or "*").inc()
        update_cache_context(request, cache_key=None, hit=False, source="markets:list")

    query_limit = limit
    if popularity_mode:
        query_limit = min(settings.max_page_size, max(limit * 4, settings.default_page_size))
    elif volume_mode:
        if total_volume_mode:
            query_limit = min(settings.max_page_size, max(limit * 3, settings.default_page_size))
        else:
            query_limit = min(settings.max_page_size, max(limit * 3, settings.default_page_size))
    # P4 optimisation: reduced multiplier from 3→2 to cut over-fetching.
    multiplier = 1 if total_volume_mode else 2
    query_limit = min(settings.max_page_size, max(query_limit, limit * multiplier))
    target_events = offset + limit
    batch_limit = query_limit
    batch_offset = 0
    collected: list[schemas.MarketResponse] = []
    seen_groups: set[str] = set()
    max_pagination_rounds = 20
    for _round in range(max_pagination_rounds):
        batch = await crud.get_markets(
            session,
            status=status,
            category=category,
            oracle=oracle,
            search=normalized_search,
            featured=featured,
            limit=batch_limit,
            offset=batch_offset,
            order_by=normalized_order_by,
            closes_after=closes_after,
            closes_before=closes_before,
        )
        if not batch:
            break
        for item in batch:
            model = schemas.MarketResponse.model_validate(item)
            collected.append(model)
            key = market_svc.derive_group_key(model)[0]
            seen_groups.add(key)
        if len(seen_groups) >= target_events:
            break
        if len(batch) < batch_limit:
            break
        batch_offset += batch_limit
    markets = collected
    market_models = await market_svc.enrich_market_models(session, markets)
    market_models = market_svc.filter_markets_for_visibility(
        market_models, hide_settled=(status or "").lower() == "active"
    )
    if popularity_mode:
        popularity_scores = {m.event_id: market_svc.compute_market_popularity(m) for m in market_models}
        selected = market_models
        if trending:
            trending_slice = [
                m for m in market_models if market_svc.is_trending_market(m, popularity_scores.get(m.event_id))
            ]
            if trending_slice:
                selected = trending_slice
        selected.sort(
            key=lambda m: (
                popularity_scores.get(m.event_id, 0),
                getattr(m, "updated_at", None) or datetime.fromtimestamp(0, tz=UTC),
            ),
            reverse=True,
        )
        market_models = selected
    elif normalized_order_by == "volume":
        market_models.sort(
            key=lambda m: (
                market_svc.market_volume_value(m, use_total=True),
                getattr(m, "updated_at", None) or datetime.fromtimestamp(0, tz=UTC),
            ),
            reverse=True,
        )
    # always coalesce groups and slice on events below
    if not market_models:
        log_event(
            logger,
            logging.INFO,
            event="markets.list.empty",
            message="no markets matched filters",
            status=status,
            category=category,
            oracle=oracle,
            search=search,
            limit=limit,
            offset=offset,
            order_by=normalized_order_by,
            trending=bool(trending),
        )
    events = market_svc.build_event_responses(market_models)
    page_events = events[offset : offset + limit]
    page_events = await market_svc.expand_event_groups_for_list(
        session,
        page_events,
        status=status,
        category=category,
        oracle=oracle,
        featured=featured,
        closes_after=closes_after,
        closes_before=closes_before,
    )
    # Extract the actual MarketResponse models from the EventResponse objects.
    # EventResponse.event_id is the *group key* (from derive_group_key), which
    # may differ from MarketResponse.event_id — so we pull from .markets instead.
    page_models = [m for event in page_events for m in event.markets]
    if cache_enabled and page_models:
        schema_tag = await get_schema_tag(cache, settings.schema_version_key)
        await market_svc.write_market_list_cache(cache, cache_key, page_models)
        await add_tag(cache, schema_tag, cache_key)
        await add_tag(cache, "markets:list", cache_key)
        await add_tags(
            cache,
            [f"market:{item.event_id}" for item in page_models if item.event_id],
            cache_key,
        )
        duration = (time.perf_counter() - start) * 1000
        log_event(
            logger,
            logging.INFO,
            event="markets.list.cache_miss",
            message="cached fresh markets list",
            cache_hit=False,
            duration_ms=round(duration, 2),
            cache_key=cache_key,
            status=status,
            category=category,
            oracle=oracle,
            search=normalized_search,
            limit=limit,
            offset=offset,
            result_count=len(market_models),
            order_by=normalized_order_by,
            trending=bool(trending),
            closes_within_hours=closes_within_hours,
        )
    else:
        duration = (time.perf_counter() - start) * 1000
        log_event(
            logger,
            logging.INFO,
            event="markets.list.response",
            message="served markets list without caching",
            cache_hit=False,
            duration_ms=round(duration, 2),
            cache_key=cache_key if cache_enabled else None,
            status=status,
            category=category,
            oracle=oracle,
            search=normalized_search,
            limit=limit,
            offset=offset,
            result_count=len(market_models),
            order_by=normalized_order_by,
            trending=bool(trending),
            closes_within_hours=closes_within_hours,
        )
    return page_events


@router.get("/categories/{category_slug}", response_model=list[schemas.MarketResponse], tags=["markets"])
async def list_markets_by_category(
    category_slug: str,
    request: Request,
    limit: Annotated[
        int,
        Query(ge=1, le=settings.max_page_size, description="Maximum number of markets to return"),
    ] = settings.default_page_size,
    offset: Annotated[int, Query(ge=0, description="Offset into the result set")] = 0,
    closes_within_hours: Annotated[
        int | None,
        Query(ge=1, le=720, description="Only return markets closing within this many hours"),
    ] = None,
    session: AsyncSession = Depends(get_session),
) -> list[schemas.MarketResponse]:
    """List markets for a category, with fallbacks when slugs are unfamiliar."""

    order_by = request.query_params.get("order_by")
    normalized_order_by = "volume" if order_by == "volume_24h_usd" else order_by
    volume_mode = normalized_order_by == "volume"
    total_volume_mode = normalized_order_by == "volume"
    start = time.perf_counter()
    cache = await get_cache_client()
    log_event(
        logger,
        logging.DEBUG,
        event="markets.category.request",
        message="processing category listing",
        category_slug=category_slug,
        limit=limit,
        offset=offset,
        order_by=normalized_order_by,
        closes_within_hours=closes_within_hours,
    )
    closes_after = None
    closes_before = None
    if closes_within_hours is not None:
        now = datetime.now(UTC)
        closes_after = now
        closes_before = now + timedelta(hours=closes_within_hours)
    category_value = market_svc.decode_slug(category_slug)
    lookup = market_svc.canonical_category_lookup(category_value)
    if lookup is None:
        log_event(
            logger,
            logging.WARNING,
            event="markets.category.invalid_slug",
            message="category slug not recognized",
            category_slug=category_slug,
            limit=limit,
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="category_not_found")
    category_slug_key, category_label = lookup
    cache_key = markets_list_cache_key(
        category_slug_key,
        None,
        None,
        None,
        limit,
        offset,
        order_by=normalized_order_by,
        closes_within_hours=closes_within_hours,
    )
    cache_enabled = cache is not None and market_svc.should_cache_market_list(limit, offset, None, normalized_order_by)
    if cache_enabled:
        per_result = await get_json_per(cache, cache_key)
        cached_payload = per_result.data if per_result is not None else None
        hydrated = await market_svc.hydrate_cached_market_list(cache, cached_payload)
        if hydrated is not None:
            if per_result is not None and per_result.should_refresh:
                asyncio.create_task(market_svc.hydrate_markets_cache(source="per_refresh"))
            hydrated = await market_svc.enrich_market_models(session, hydrated)
            update_cache_context(request, cache_key=cache_key, hit=True, source="markets:category")
            models_from_cache = market_svc.filter_markets_for_visibility(hydrated, hide_settled=False)
            if models_from_cache:
                models_from_cache = market_svc.coalesce_grouped_markets(
                    models_from_cache, use_total_volume=total_volume_mode
                )
            if volume_mode and models_from_cache:
                models_from_cache.sort(
                    key=lambda m: (
                        market_svc.market_volume_value(m, use_total=total_volume_mode),
                        getattr(m, "updated_at", None) or datetime.fromtimestamp(0, tz=UTC),
                    ),
                    reverse=True,
                )
            models_from_cache = models_from_cache[:limit]
            log_event(
                logger,
                logging.INFO,
                event="markets.category.cache_hit",
                message="served category markets from cache",
                category_slug=category_slug_key,
                limit=limit,
                result_count=len(models_from_cache),
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                closes_within_hours=closes_within_hours,
            )
            return models_from_cache
        update_cache_context(request, cache_key=cache_key, hit=False, source="markets:category")
    else:
        update_cache_context(request, cache_key=None, hit=False, source="markets:category")

    trending_category = category_slug_key == "trending"
    fetch_limit = limit
    fetch_offset = offset
    # P4 optimisation: reduced multiplier from 3→2 to cut over-fetching.
    multiplier = 1 if total_volume_mode else 2
    fetch_limit = min(settings.max_page_size, max(limit * multiplier, settings.default_page_size))
    log_event(
        logger,
        logging.DEBUG,
        event="markets.category.fetch",
        message="fetching category markets from database",
        category_slug=category_slug_key,
        category_label=category_label,
        trending=trending_category,
        limit=fetch_limit,
        offset=fetch_offset,
        order_by=normalized_order_by,
        closes_within_hours=closes_within_hours,
    )
    if trending_category:
        markets = await crud.get_markets(
            session,
            limit=fetch_limit,
            offset=fetch_offset,
            order_by=normalized_order_by,
            closes_after=closes_after,
            closes_before=closes_before,
        )
    else:
        markets = await crud.get_markets(
            session,
            category=category_label,
            limit=fetch_limit,
            offset=fetch_offset,
            order_by=normalized_order_by,
            closes_after=closes_after,
            closes_before=closes_before,
        )
    market_models = market_svc.filter_markets_for_visibility(
        await market_svc.enrich_market_models(session, [schemas.MarketResponse.model_validate(m) for m in markets]),
        hide_settled=False,
    )
    if not market_models and not trending_category and offset == 0:
        fallback_matches = await market_svc.fallback_markets_by_category_slug(session, category_slug_key, limit)
        if fallback_matches:
            market_models = market_svc.filter_markets_for_visibility(
                await market_svc.enrich_market_models(session, fallback_matches),
                hide_settled=False,
            )
    if market_models:
        market_models = market_svc.coalesce_grouped_markets(market_models, use_total_volume=total_volume_mode)
    if volume_mode and market_models:
        market_models.sort(
            key=lambda m: (
                market_svc.market_volume_value(m, use_total=total_volume_mode),
                getattr(m, "updated_at", None) or datetime.fromtimestamp(0, tz=UTC),
            ),
            reverse=True,
        )
    effective_offset = offset if fetch_offset == 0 else 0
    market_models = market_models[effective_offset : effective_offset + limit]
    if not market_models:
        log_event(
            logger,
            logging.INFO,
            event="markets.category.empty",
            message="no markets available for category",
            category_slug=category_slug_key,
            limit=limit,
            offset=offset,
            order_by=normalized_order_by,
            closes_within_hours=closes_within_hours,
        )
    if cache_enabled and market_models:
        schema_tag = await get_schema_tag(cache, settings.schema_version_key)
        await market_svc.write_market_list_cache(cache, cache_key, market_models)
        await add_tag(cache, schema_tag, cache_key)
        await add_tag(cache, "markets:category", cache_key)
        await add_tag(cache, f"category:{category_slug_key}", cache_key)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        log_event(
            logger,
            logging.INFO,
            event="markets.category.cache_miss",
            message="cached category markets",
            category_slug=category_slug_key,
            limit=limit,
            offset=offset,
            result_count=len(market_models),
            duration_ms=duration_ms,
            closes_within_hours=closes_within_hours,
        )
        update_cache_context(request, cache_key=cache_key, hit=False, source="markets:category")
    else:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        log_event(
            logger,
            logging.INFO,
            event="markets.category.cache_bypass",
            message="served category markets without cache write",
            category_slug=category_slug_key,
            limit=limit,
            offset=offset,
            result_count=len(market_models),
            duration_ms=duration_ms,
            closes_within_hours=closes_within_hours,
        )
        update_cache_context(request, cache_key=None, hit=False, source="markets:category")
    return market_models


@router.get("/events/by-key/{event_key}", response_model=schemas.EventResponse, tags=["events"])
async def get_event_by_key(
    event_key: str,
    session: AsyncSession = Depends(get_session),
) -> schemas.EventResponse:
    """Resolve event detail by event grouping key (preferred) with event id fallback."""

    normalized_key = (event_key or "").strip().lower()
    request_key = normalized_key or event_key
    requested_market_event_id: str | None = None

    async def _load_inferred_group_models(group_key: str) -> list[schemas.MarketResponse]:
        if "-" not in group_key:
            return []
        prefix = group_key.split("-", 1)[0].strip().lower()
        if not prefix or prefix == group_key:
            return []
        candidates = await crud.get_markets_by_group_slug(session, prefix)
        if not candidates:
            candidates = await crud.get_markets_by_event_key(session, prefix)
        if not candidates:
            return []
        candidate_models = await market_svc.enrich_market_models(
            session, [schemas.MarketResponse.model_validate(item) for item in candidates], include_siblings=True
        )
        return [item for item in candidate_models if market_svc.derive_group_key(item)[0] == group_key]

    cache = await get_cache_client()
    if cache is not None:
        cached = await get_json(cache, market_svc.market_detail_cache_key(request_key))
        if cached is None and normalized_key and normalized_key != request_key:
            cached = await get_json(cache, market_svc.market_detail_cache_key(normalized_key))
        if cached is not None:
            model = schemas.MarketResponse.model_validate(cached)
            raw_group_slug = getattr(model, "group_slug", None) or ""
            if raw_group_slug:
                normalized_group_slug = market_svc._normalize_group_slug(raw_group_slug)
                group_markets = await crud.get_markets_by_group_slug(session, raw_group_slug, limit=500)
                if len(group_markets) <= 1 and normalized_group_slug != raw_group_slug:
                    group_markets = await crud.get_markets_by_group_slug_pattern(
                        session, normalized_group_slug, limit=500
                    )
                if market_svc._is_temporal_series_slug(raw_group_slug):
                    closes_at = getattr(model, "closes_at", None)
                    if isinstance(closes_at, datetime):
                        ref_date = closes_at.date()
                        group_markets = [
                            m for m in group_markets if m.closes_at is not None and m.closes_at.date() == ref_date
                        ]
                if group_markets:
                    market_models_cached = await market_svc.enrich_market_models(
                        session,
                        [schemas.MarketResponse.model_validate(m) for m in group_markets],
                        include_siblings=True,
                    )
                    event = market_svc.build_event_responses(market_models_cached)[0]
                    if len(event.markets) > _MAX_DETAIL_MARKETS:
                        event.markets = event.markets[:_MAX_DETAIL_MARKETS]
                    return event
            await market_svc.enrich_market_models(session, [model], include_siblings=True)
            return market_svc.build_event_responses([model])[0]
    markets = []
    market_models: list[schemas.MarketResponse] | None = None
    # Try public_event_id lookup first (8-char hex IDs)
    if normalized_key:
        markets = await crud.get_markets_by_public_event_id(session, normalized_key)
    if not markets and normalized_key:
        markets = await crud.get_markets_by_group_slug(session, normalized_key, limit=500)
        if markets and market_svc._is_temporal_series_slug(normalized_key):
            ref_closes = getattr(markets[0], "closes_at", None)
            if ref_closes is not None:
                ref_date = ref_closes.date()
                markets = [m for m in markets if m.closes_at is not None and m.closes_at.date() == ref_date]
    if not markets:
        market = await crud.get_market_by_event_id(session, event_key)
        if market is None:
            market = await crud.get_market_by_event_id(session, normalized_key)
        if market is None:
            if normalized_key:
                markets = await crud.get_markets_by_event_key(session, normalized_key)
            if not markets and normalized_key:
                market_models = await _load_inferred_group_models(normalized_key)
                if market_models:
                    markets = []
            if not markets and not market_models:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="event_not_found")
        else:
            requested_market_event_id = market.event_id
            group_slug = getattr(market, "group_slug", None)
            event_group_key = getattr(market, "event_key", None)
            if group_slug:
                raw_slug = str(group_slug)
                normalized_slug = market_svc._normalize_group_slug(raw_slug)
                markets = await crud.get_markets_by_group_slug(session, raw_slug, limit=500)
                # If the raw slug only matched a subset, retry with a
                # pattern query so range-variant markets are included.
                if len(markets) <= 1 and normalized_slug != raw_slug:
                    markets = await crud.get_markets_by_group_slug_pattern(session, normalized_slug, limit=500)
                if markets and market_svc._is_temporal_series_slug(str(group_slug)):
                    ref_closes = getattr(market, "closes_at", None)
                    if ref_closes is not None:
                        ref_date = ref_closes.date()
                        markets = [m for m in markets if m.closes_at is not None and m.closes_at.date() == ref_date]
            if not markets and event_group_key:
                markets = await crud.get_markets_by_event_key(session, str(event_group_key))
            if not markets:
                markets = [market]
    if market_models is None:
        market_models = await market_svc.enrich_market_models(
            session, [schemas.MarketResponse.model_validate(m) for m in markets], include_siblings=True
        )
    if requested_market_event_id:
        selected_market = next(
            (item for item in market_models if str(getattr(item, "event_id", "")) == requested_market_event_id), None
        )
        if selected_market is not None:
            selected_group_key, _ = market_svc.derive_group_key(selected_market)
            if selected_group_key and selected_group_key != "unknown":
                matching_group_models = [
                    item for item in market_models if market_svc.derive_group_key(item)[0] == selected_group_key
                ]
                if matching_group_models:
                    market_models = matching_group_models
            else:
                market_models = [selected_market]
    if normalized_key:
        matching_models = [item for item in market_models if market_svc.derive_group_key(item)[0] == normalized_key]
        if matching_models:
            market_models = matching_models
        elif normalized_key in market_svc.GENERIC_GROUP_SLUGS:
            inferred_groups: dict[str, list[schemas.MarketResponse]] = {}
            for item in market_models:
                inferred_key = market_svc.derive_group_key(item)[0]
                if not inferred_key or inferred_key == "unknown" or inferred_key == normalized_key:
                    continue
                inferred_groups.setdefault(inferred_key, []).append(item)
            if inferred_groups:
                now = datetime.now(UTC)

                def _rank_bucket(entry: tuple[str, list[schemas.MarketResponse]]) -> tuple[int, float]:
                    _slug, items = entry
                    active_closes = [
                        closes_at
                        for closes_at in (getattr(item, "closes_at", None) for item in items)
                        if isinstance(closes_at, datetime)
                        and (closes_at.replace(tzinfo=UTC) if closes_at.tzinfo is None else closes_at) >= now
                    ]
                    next_close = min(active_closes).timestamp() if active_closes else float("inf")
                    return (len(items), -next_close)

                best_slug, best_items = max(inferred_groups.items(), key=_rank_bucket)
                log_event(
                    logger,
                    logging.INFO,
                    event="markets.event.disambiguated_generic_key",
                    message="resolved generic event key to inferred event group",
                    requested_key=normalized_key,
                    selected_group=best_slug,
                    candidates=len(inferred_groups),
                )
                market_models = best_items
    if market_models:
        cache = await get_cache_client()
        for market_model in market_models:
            cache_key = market_svc.market_detail_cache_key(market_model.event_id)
            ttl_seconds = market_svc.resolved_cache_ttl(market_model.status, getattr(market_model, "resolved_at", None))
            if cache is not None and ttl_seconds > 0:
                payload = market_model.model_dump(mode="json")
                await set_json(cache, cache_key, payload, ttl_seconds)
                await add_tag(cache, f"market:{market_model.event_id}", cache_key)
                if getattr(market_model, "condition_id", None):
                    await add_tag(cache, f"resolution:{str(market_model.condition_id).lower()}", cache_key)
                if getattr(market_model, "group_slug", None):
                    await add_tag(cache, f"group:{str(market_model.group_slug)}", cache_key)
                if getattr(market_model, "event_key", None):
                    await add_tag(cache, f"group:{str(market_model.event_key)}", cache_key)
                public_eid = getattr(market_model, "public_event_id", None)
                if public_eid:
                    alias_key = market_svc.market_detail_cache_key(public_eid)
                    await set_json(cache, alias_key, payload, ttl_seconds)
                    await add_tag(cache, f"market:{market_model.event_id}", alias_key)
    events = market_svc.build_event_responses(market_models)
    event = events[0]
    if len(event.markets) > _MAX_DETAIL_MARKETS:
        event.markets = event.markets[:_MAX_DETAIL_MARKETS]
    return event


@router.get("/events/onchain", tags=["events"], include_in_schema=False)
async def list_onchain_markets():
    """Return markets discovered directly from the on-chain factory contract."""

    cfg = settings
    try:
        addresses = await fetch_factory_markets(cfg)
    except OnChainConfigurationError as exc:
        log_event(
            logger,
            logging.WARNING,
            "markets.onchain.unconfigured",
            "on-chain configuration missing",
            error=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="onchain_not_configured") from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("failed to fetch on-chain markets")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="onchain_query_failed") from exc
    return {"markets": addresses}


@router.get("/events/stats", response_model=list[schemas.MarketStatusBreakdown], tags=["events"])
async def market_stats(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[schemas.MarketStatusBreakdown]:
    """Return counts of markets per status, cached for fast health checks."""

    start = time.perf_counter()
    cache = await get_cache_client()
    cache_available = cache is not None
    log_event(logger, logging.DEBUG, "markets.stats.request", "processing market stats request")
    cached = await get_json(cache, market_svc.MARKETS_STATS_KEY)
    if cached is not None:
        update_cache_context(request, cache_key=market_svc.MARKETS_STATS_KEY, hit=True, source="markets:stats")
        duration = (time.perf_counter() - start) * 1000
        log_event(
            logger,
            logging.INFO,
            event="markets.stats.cache_hit",
            message="served market stats from cache",
            cache_hit=True,
            duration_ms=round(duration, 2),
            result_count=len(cached),
        )
        return [schemas.MarketStatusBreakdown.model_validate(item) for item in cached]
    stats = await crud.get_market_stats(session)
    payload = [jsonable_encoder(item) for item in stats]
    duration = (time.perf_counter() - start) * 1000
    if cache_available:
        schema_tag = await get_schema_tag(cache, settings.schema_version_key)
        await set_json(cache, market_svc.MARKETS_STATS_KEY, payload, settings.cache_ttl_seconds)
        await add_tag(cache, schema_tag, market_svc.MARKETS_STATS_KEY)
        await add_tag(cache, "markets:stats", market_svc.MARKETS_STATS_KEY)
        log_event(
            logger,
            logging.INFO,
            event="markets.stats.cache_miss",
            message="cached fresh market stats",
            cache_hit=False,
            duration_ms=round(duration, 2),
            result_count=len(stats),
        )
        cache_key = market_svc.MARKETS_STATS_KEY
    else:
        log_event(
            logger,
            logging.INFO,
            event="markets.stats.cache_bypass",
            message="served market stats without cache",
            cache_hit=False,
            duration_ms=round(duration, 2),
            result_count=len(stats),
        )
        cache_key = None
    update_cache_context(request, cache_key=cache_key, hit=False, source="markets:stats")
    return stats


@router.get("/events/count", response_model=schemas.EventCountResponse, tags=["events"])
async def count_events(
    request: Request,
    status: Annotated[str | None, Query(description="Filter markets by status")] = None,
    category: Annotated[str | None, Query(description="Filter markets by category")] = None,
    oracle: Annotated[str | None, Query(description="Filter markets by oracle address")] = None,
    search: Annotated[
        str | None,
        Query(min_length=2, max_length=200, description="Case-insensitive search over market titles"),
    ] = None,
    featured: Annotated[bool | None, Query(description="Return only featured markets", alias="only_featured")] = None,
    session: AsyncSession = Depends(get_session),
) -> schemas.EventCountResponse:
    """Return distinct event group count for sitemap paging."""

    normalized_search = search
    if search is not None:
        normalized = search.strip().lower()
        if len(normalized) > 120:
            normalized = normalized[:120]
        normalized_search = normalized

    cache_key = events_count_cache_key(
        status=status,
        category=category,
        oracle=oracle,
        search=normalized_search,
        featured=featured,
    )
    cache = await get_cache_client()
    cached = await get_json(cache, cache_key)
    if cached is not None:
        update_cache_context(request, cache_key=cache_key, hit=True, source="events:count")
        return schemas.EventCountResponse.model_validate(cached)

    total = await crud.count_events(
        session,
        status=status,
        category=category,
        oracle=oracle,
        search=normalized_search,
        featured=featured,
    )

    payload = jsonable_encoder({"total": total})
    if cache is not None:
        schema_tag = await get_schema_tag(cache, settings.schema_version_key)
        await set_json(cache, cache_key, payload, settings.cache_ttl_seconds)
        await add_tag(cache, schema_tag, cache_key)
        await add_tag(cache, "events:count", cache_key)
    update_cache_context(request, cache_key=cache_key, hit=False, source="events:count")
    return schemas.EventCountResponse(total=total)


@router.get("/events/suggest", response_model=list[schemas.MarketResponse], tags=["events"])
async def suggest_markets(
    request: Request,
    q: Annotated[str, Query(min_length=2, max_length=200, description="Search term for suggestions")],
    limit: Annotated[int, Query(ge=1, le=25, description="Maximum number of suggestions to return")] = 5,
    session: AsyncSession = Depends(get_session),
) -> list[schemas.MarketResponse]:
    """Return a short suggestion list, caching the normalized query payload."""

    start = time.perf_counter()
    cache = await get_cache_client()
    cache_available = cache is not None
    log_event(
        logger,
        logging.DEBUG,
        event="markets.suggest.request",
        message="processing suggestion request",
        query=q,
        limit=limit,
    )
    normalized_query = q.strip()
    cache_key = suggest_cache_key(normalized_query, limit)
    cached = await get_json(cache, cache_key)
    if cached is not None:
        update_cache_context(request, cache_key=cache_key, hit=True, source="markets:suggest")
        models_from_cache = [schemas.MarketResponse.model_validate(item) for item in cached]
        await market_svc.enrich_market_models(session, models_from_cache)
        log_event(
            logger,
            logging.INFO,
            event="markets.suggest.cache_hit",
            message="served suggestions from cache",
            query=normalized_query,
            limit=limit,
            result_count=len(models_from_cache),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return models_from_cache

    # Over-fetch to compensate for multi-outcome events sharing the same event_id.
    # filter_markets_for_visibility de-duplicates by event_id, so fetching 4x
    # ensures we still return `limit` distinct events after dedup.
    raw_limit = min(limit * 4, 100)
    results = await crud.search_markets(session, normalized_query, raw_limit)
    market_models = [schemas.MarketResponse.model_validate(m) for m in results]
    filtered = market_svc.filter_markets_for_visibility(
        await market_svc.enrich_market_models(session, market_models),
        dedup_by_group_key=True,
    )
    filtered = filtered[:limit]
    if not filtered:
        log_event(
            logger,
            logging.INFO,
            event="markets.suggest.empty",
            message="no suggestions found for query",
            query=normalized_query,
            limit=limit,
        )
    payload = [item.model_dump(mode="json") for item in filtered]
    if cache_available:
        schema_tag = await get_schema_tag(cache, settings.schema_version_key)
        await set_json(cache, cache_key, payload, settings.cache_ttl_seconds)
        await add_tag(cache, schema_tag, cache_key)
        await add_tag(cache, "markets:suggest", cache_key)
        log_event(
            logger,
            logging.INFO,
            event="markets.suggest.cache_miss",
            message="cached suggestion results",
            query=normalized_query,
            limit=limit,
            result_count=len(filtered),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
    else:
        log_event(
            logger,
            logging.INFO,
            event="markets.suggest.cache_bypass",
            message="served suggestions without cache",
            query=normalized_query,
            limit=limit,
            result_count=len(filtered),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
    update_cache_context(request, cache_key=cache_key if cache_available else None, hit=False, source="markets:suggest")
    return filtered


@router.get("/resolution/{condition_id_hex}", response_model=schemas.ResolutionSummary, tags=["markets"])
async def read_resolution(
    condition_id_hex: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> schemas.ResolutionSummary:
    """Return the resolution summary for a condition id with cache + Goldsky fallback."""

    start = time.perf_counter()
    cache = await get_cache_client()
    cache_available = cache is not None
    log_event(
        logger,
        logging.DEBUG,
        event="markets.resolution.request",
        message="fetching resolution summary",
        condition_id=condition_id_hex,
    )
    normalized_condition = condition_id_hex.lower()
    cache_key = resolution_cache_key(normalized_condition)
    cached = await get_json(cache, cache_key)
    if cached is not None:
        RESOLUTION_CACHE_COUNTER.labels(outcome="hit").inc()
        update_cache_context(request, cache_key=cache_key, hit=True, source="markets:resolution")
        cached_summary = schemas.ResolutionSummary.model_validate(cached)
        log_event(
            logger,
            logging.INFO,
            event="markets.resolution.cache_hit",
            message="served resolution summary from cache",
            condition_id=normalized_condition,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return cached_summary

    market = await crud.get_market_by_condition_id(session, normalized_condition)
    record = await crud.get_resolution_by_condition_id(session, normalized_condition)
    market_outcomes = await market_svc.load_outcomes_for_market(session, market)

    summary_model: schemas.ResolutionSummary | None = None
    if record is not None:
        if market and (record.event_id is None or record.market_id is None):
            record.event_id = market.event_id
            record.market_id = market.id
        summary_model = market_svc.build_resolution_summary_from_record(
            record,
            market,
            market_outcomes=market_outcomes,
        )
    elif goldsky_client is not None:
        try:
            summary_result = goldsky_client.resolution_summary(
                normalized_condition,
                market_outcomes or None,
                len(market_outcomes) if market_outcomes else None,
            )
            if inspect.isawaitable(summary_result):
                summary_payload = cast(dict[str, Any] | None, await summary_result)
            else:
                summary_payload = cast(dict[str, Any] | None, summary_result)
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                logger,
                logging.WARNING,
                event="markets.resolution.goldsky_failed",
                message="failed to fetch resolution from goldsky",
                condition_id=normalized_condition,
                error=str(exc),
            )
        else:
            if summary_payload:
                if market:
                    summary_payload.setdefault("marketId", market.id)
                    summary_payload.setdefault("eventId", market.event_id)
                    summary_payload.setdefault("title", market.title)
                    summary_payload.setdefault("slug", market.slug)
                    summary_payload.setdefault("oracle", market.oracle)
                    summary_payload.setdefault("outcomes", market_outcomes or summary_payload.get("outcomes", []))
                log_event(
                    logger,
                    logging.INFO,
                    event="markets.resolution.goldsky",
                    message="served resolution summary via goldsky fallback",
                    condition_id=normalized_condition,
                )

                try:
                    summary_model = schemas.ResolutionSummary.model_validate(summary_payload)
                    persisted_payload = {
                        "condition_id": normalized_condition,
                        "source": summary_model.source,
                        "resolved": summary_model.resolved,
                        "payouts": summary_model.payouts or [],
                        "winners": [
                            winner.model_dump() if hasattr(winner, "model_dump") else winner
                            for winner in (summary_model.winners or [])
                        ],
                        "outcomes": summary_model.outcomes or [],
                        "oracle": summary_model.oracle,
                        "question_id": summary_model.question_id,
                        "transaction_hash": summary_model.transaction_hash,
                        "block_number": summary_model.block_number,
                        "block_timestamp": summary_model.block_timestamp,
                        "winning_outcome_id": summary_model.winning_outcome_id,
                        "rake_bps": summary_model.rake_bps
                        if summary_model.rake_bps is not None
                        else getattr(market, "rake_bps", None),
                        "request_id": summary_model.request_id,
                        "checked_at": summary_model.checked_at or datetime.now(tz=UTC),
                        "market_id": getattr(market, "id", None) if market else None,
                        "event_id": getattr(market, "event_id", None) if market else None,
                    }
                    await repository_async.upsert_resolution(session, persisted_payload)
                    await session.flush()
                except Exception as exc:  # pragma: no cover - defensive persistence
                    log_event(
                        logger,
                        logging.WARNING,
                        event="markets.resolution.persist_failed",
                        message="failed to persist resolution from fallback",
                        condition_id=normalized_condition,
                        error=str(exc),
                    )

    if summary_model is None:
        if record is not None:
            summary_model = market_svc.build_resolution_summary_from_record(
                record,
                market,
                market_outcomes=market_outcomes,
            )
    if summary_model is None:
        RESOLUTION_CACHE_COUNTER.labels(outcome="miss").inc()
        log_event(
            logger,
            logging.WARNING,
            event="markets.resolution.missing",
            message="resolution not found",
            condition_id=normalized_condition,
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resolution_not_found")

    if market is not None and getattr(market, "id", None) is not None:
        settlement = await repository_async.get_settlement_by_market_id(session, market.id)
        if settlement:
            market_svc.attach_settlement_to_resolution(summary_model, settlement)

    if cache_available:
        cache_payload = summary_model.model_dump(mode="json", by_alias=True)
        if summary_model.checked_at is not None:
            cache_payload["checkedAt"] = summary_model.checked_at.isoformat()
        if summary_model.block_timestamp is not None:
            cache_payload["blockTimestamp"] = summary_model.block_timestamp.isoformat()
        schema_tag = await get_schema_tag(cache, settings.schema_version_key)
        await set_json(cache, cache_key, cache_payload, settings.cache_ttl_seconds)
        await add_tag(cache, schema_tag, cache_key)
        await add_tag(cache, f"resolution:{normalized_condition}", cache_key)
        log_event(
            logger,
            logging.INFO,
            event="markets.resolution.cache_miss",
            message="cached resolution summary",
            condition_id=normalized_condition,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
    else:
        log_event(
            logger,
            logging.INFO,
            event="markets.resolution.cache_bypass",
            message="served resolution without cache",
            condition_id=normalized_condition,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
    if cache_available:
        RESOLUTION_CACHE_COUNTER.labels(outcome="miss").inc()
    else:
        RESOLUTION_CACHE_COUNTER.labels(outcome="bypass").inc()
    update_cache_context(
        request, cache_key=cache_key if cache_available else None, hit=False, source="markets:resolution"
    )
    return summary_model


@router.get("/markets/{market_id}/history", response_model=schemas.PriceHistoryResponse, tags=["markets"])
async def market_price_history(
    request: Request,
    market_id: str,
    outcome: Annotated[
        str | None,
        Query(description="Outcome index or yes/no label for the market token"),
    ] = None,
    token_id: Annotated[str | None, Query(description="Explicit CLOB token id override")] = None,
    interval: Annotated[
        HistoryInterval | None,
        Query(description="Duration window ending now (mutually exclusive with startTs/endTs)"),
    ] = None,
    start_ts: Annotated[int | None, Query(ge=0, alias="startTs")] = None,
    end_ts: Annotated[int | None, Query(ge=0, alias="endTs")] = None,
    fidelity: Annotated[int | None, Query(ge=1, le=1440)] = None,
    session: AsyncSession = Depends(get_session),
) -> schemas.PriceHistoryResponse:
    """Return cached CLOB price history for a market/outcome combination."""

    start = time.perf_counter()
    normalized_market_id = market_id.strip()
    if not normalized_market_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="market_id_required")

    if interval and (start_ts is not None or end_ts is not None):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="interval_exclusive")
    if start_ts is not None and end_ts is not None:
        if end_ts < start_ts:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_time_range")
        if end_ts - start_ts > CLOB_HISTORY_MAX_RANGE_SECONDS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="range_too_large")
    if interval is None and start_ts is None and end_ts is None:
        interval = "1d"

    market = await crud.get_market_by_event_id(session, normalized_market_id)
    if market is None:
        market = await crud.get_market_by_condition_id(session, normalized_market_id)
    if market is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="market_not_found")

    token_rows = sorted(
        list(getattr(market, "clob_tokens_rel", []) or []),
        key=lambda row: getattr(row, "id", 0),
    )
    token_ids = [row.token_id for row in token_rows if row.token_id]
    gamma_meta = getattr(market, "gamma_metadata_rel", None)
    if not token_ids and gamma_meta is not None:
        if getattr(gamma_meta, "clob_token_id_yes", None):
            token_ids.append(str(gamma_meta.clob_token_id_yes))
        if getattr(gamma_meta, "clob_token_id_no", None):
            token_ids.append(str(gamma_meta.clob_token_id_no))

    resolved_token_id = token_id.strip() if isinstance(token_id, str) else None
    if resolved_token_id and token_ids and resolved_token_id not in token_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="clob_token_not_found")
    if not resolved_token_id:
        if not token_ids:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="clob_token_missing")
        if outcome is None:
            if len(token_ids) == 1:
                resolved_token_id = token_ids[0]
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="outcome_required")
        else:
            normalized_outcome = outcome.strip().lower()
            if normalized_outcome in {"yes", "no"}:
                match = next(
                    (row.token_id for row in token_rows if row.side == normalized_outcome and row.token_id),
                    None,
                )
                if match:
                    resolved_token_id = match
                elif len(token_ids) >= 2:
                    resolved_token_id = token_ids[0] if normalized_outcome == "yes" else token_ids[1]
            else:
                try:
                    outcome_index = int(normalized_outcome)
                except (TypeError, ValueError):
                    outcome_index = None
                if outcome_index is not None and 0 <= outcome_index < len(token_ids):
                    resolved_token_id = token_ids[outcome_index]
    if not resolved_token_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="clob_token_not_found")

    cache = await get_cache_client()
    cache_key = clob_prices_history_cache_key(resolved_token_id, interval, fidelity, start_ts, end_ts)
    if cache is not None:
        cached_payload = await get_json(cache, cache_key)
        if cached_payload is not None:
            try:
                cached_response = schemas.PriceHistoryResponse.model_validate(cached_payload)
            except Exception:
                cached_response = None
            if cached_response is not None:
                update_cache_context(request, cache_key=cache_key, hit=True, source="markets:history")
                log_event(
                    logger,
                    logging.INFO,
                    event="markets.history.cache_hit",
                    message="served market history from cache",
                    cache_hit=True,
                    duration_ms=round((time.perf_counter() - start) * 1000, 2),
                    market_id=normalized_market_id,
                    token_id=resolved_token_id,
                    interval=interval,
                    fidelity=fidelity,
                )
                return cached_response

    params: dict[str, str | int | float] = {"market": resolved_token_id}
    if interval:
        params["interval"] = interval
    if fidelity is not None:
        params["fidelity"] = fidelity
    if start_ts is not None:
        params["startTs"] = start_ts
    if end_ts is not None:
        params["endTs"] = end_ts

    host = str(settings.clob_host) if settings.clob_host else CLOB_HISTORY_DEFAULT_HOST
    url = f"{host.rstrip('/')}/prices-history"
    try:
        client = await get_http_client(settings.polymarket_timeout_seconds)
        clob_response = await client.get(url, params=params)
    except httpx.RequestError as exc:
        log_event(
            logger,
            logging.WARNING,
            event="markets.history.error",
            message="failed to fetch clob history",
            market_id=normalized_market_id,
            token_id=resolved_token_id,
            error=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="clob_request_failed") from exc

    if clob_response.status_code == status.HTTP_404_NOT_FOUND:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="clob_market_not_found")
    if clob_response.status_code >= 400:
        log_event(
            logger,
            logging.WARNING,
            event="markets.history.error",
            message="clob history returned error",
            market_id=normalized_market_id,
            token_id=resolved_token_id,
            status_code=clob_response.status_code,
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="clob_request_failed")

    payload_data = clob_response.json()
    payload: dict[str, Any] = payload_data if isinstance(payload_data, dict) else {}
    raw_history = payload.get("history")
    history: list[schemas.PriceHistoryPoint] = []
    if isinstance(raw_history, list):
        for item in raw_history:
            if not isinstance(item, dict):
                continue
            ts_raw = item.get("t")
            price_raw = item.get("p")
            if ts_raw is None or price_raw is None:
                continue
            try:
                timestamp = int(ts_raw)
                price = float(price_raw)
            except (TypeError, ValueError):
                continue
            history.append(schemas.PriceHistoryPoint(t=timestamp, p=price))

    response_payload = schemas.PriceHistoryResponse(history=history, source="clob")
    if cache is not None:
        ttl_seconds = _history_cache_ttl_seconds(interval)
        response_dump = response_payload.model_dump(mode="json")
        await set_json(cache, cache_key, response_dump, ttl_seconds)
        schema_tag = await get_schema_tag(cache, settings.schema_version_key)
        await add_tag(cache, schema_tag, cache_key)
        if getattr(market, "event_id", None):
            await add_tag(cache, f"market:{market.event_id}", cache_key)

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    log_event(
        logger,
        logging.INFO,
        event="markets.history.response",
        message="served market history",
        market_id=normalized_market_id,
        token_id=resolved_token_id,
        interval=interval,
        fidelity=fidelity,
        result_count=len(history),
        duration_ms=duration_ms,
    )
    update_cache_context(
        request, cache_key=cache_key if cache is not None else None, hit=False, source="markets:history"
    )
    return response_payload


@router.get("/events/{event_id}", response_model=schemas.EventResponse, tags=["events"])
async def read_event_by_id(
    event_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> schemas.EventResponse:
    """Return a single event detail record by event id, hydrating siblings when cached."""

    cache_key = market_svc.market_detail_cache_key(event_id)
    cache = await get_cache_client()
    cache_available = cache is not None
    log_event(
        logger,
        logging.DEBUG,
        event="markets.detail.request",
        message="processing market detail request",
        event_id=event_id,
        cache_key=cache_key,
    )
    start = time.perf_counter()
    cached = await get_json(cache, cache_key)
    if cached is not None:
        duration = (time.perf_counter() - start) * 1000
        model = schemas.MarketResponse.model_validate(cached)
        await market_svc.enrich_market_models(session, [model], include_siblings=True)
        update_cache_context(request, cache_key=cache_key, hit=True, source="markets:detail")
        MARKET_DETAIL_CACHE_COUNTER.labels(outcome="hit").inc()
        log_event(
            logger,
            logging.INFO,
            event="markets.detail.cache_hit",
            message="served market detail from cache",
            cache_hit=True,
            duration_ms=round(duration, 2),
            event_id=event_id,
            result_count=1,
        )
        return market_svc.build_event_responses([model])[0]

    market = await crud.get_market_by_event_id(session, event_id)
    if not market:
        MARKET_DETAIL_CACHE_COUNTER.labels(outcome="miss").inc()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="market_not_found")
    response = (
        await market_svc.enrich_market_models(
            session, [schemas.MarketResponse.model_validate(market)], include_siblings=True
        )
    )[0]
    duration = (time.perf_counter() - start) * 1000
    if cache_available:
        schema_tag = await get_schema_tag(cache, settings.schema_version_key)
        ttl_seconds = market_svc.resolved_cache_ttl(
            response.status, response.resolved_at if hasattr(response, "resolved_at") else None
        )
        if ttl_seconds > 0:
            await set_json(cache, cache_key, response.model_dump(mode="json"), ttl_seconds)
            await add_tag(cache, schema_tag, cache_key)
            await add_tag(cache, f"market:{event_id}", cache_key)
            if getattr(response, "condition_id", None):
                await add_tag(cache, f"resolution:{str(response.condition_id).lower()}", cache_key)
            if getattr(response, "event_key", None):
                await add_tag(cache, f"group:{str(response.event_key)}", cache_key)
            elif getattr(response, "group_slug", None):
                await add_tag(cache, f"group:{str(response.group_slug)}", cache_key)
            log_event(
                logger,
                logging.INFO,
                event="markets.detail.cache_miss",
                message="cached fresh market detail",
                cache_hit=False,
                duration_ms=round(duration, 2),
                event_id=event_id,
                result_count=1,
            )
    else:
        log_event(
            logger,
            logging.INFO,
            event="markets.detail.cache_bypass",
            message="served market detail without cache",
            cache_hit=False,
            duration_ms=round(duration, 2),
            event_id=event_id,
            result_count=1,
        )
    if cache_available:
        MARKET_DETAIL_CACHE_COUNTER.labels(outcome="miss").inc()
    else:
        MARKET_DETAIL_CACHE_COUNTER.labels(outcome="bypass").inc()
    update_cache_context(request, cache_key=cache_key if cache_available else None, hit=False, source="markets:detail")
    return market_svc.build_event_responses([response])[0]


@router.get(
    "/clob/orderbook/{token_id}",
    response_model=schemas.ClobOrderBookResponse,
    tags=["markets"],
    include_in_schema=False,
)
async def clob_order_book(token_id: str) -> schemas.ClobOrderBookResponse:
    """Fetch the CLOB orderbook via the async threadpool to avoid blocking the loop."""

    if not settings.clob_host:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="clob_unavailable")
    try:
        client = ClobClient(str(settings.clob_host))
        summary = await asyncio.to_thread(client.get_order_book, token_id)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="clob.orderbook.error",
            message="failed to fetch clob orderbook",
            token_id=token_id,
            error=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="clob_request_failed") from exc
    log_event(
        logger,
        logging.INFO,
        event="clob.orderbook.success",
        message="fetched clob orderbook",
        token_id=token_id,
    )
    return schemas.ClobOrderBookResponse.from_summary(summary)


@router.post(
    "/events",
    response_model=schemas.MarketResponse,
    tags=["events"],
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def upsert_market(
    market_in: schemas.MarketCreate,
    session: AsyncSession = Depends(get_session),
    internal_secret: str | None = Header(default=None, alias="X-Internal-Secret"),
) -> schemas.MarketResponse:
    """Create or update a market record and invalidate relevant caches."""

    _verify_internal_secret(internal_secret)
    start = time.perf_counter()
    log_event(
        logger,
        logging.INFO,
        event="markets.create.request",
        message="creating or updating market",
        event_id=market_in.event_id,
        category=market_in.category,
        oracle=market_in.oracle,
    )
    payload = market_in.model_dump()
    for legacy in ("outcomes", "outcome_prices", "tags", "clob_token_ids"):
        payload.pop(legacy, None)
    market = await crud.create_or_update_market(session, schemas.MarketCreate(**payload))
    await session.flush()
    event_id_value = cast(str | None, getattr(market, "event_id", None))
    await market_svc.invalidate_market_cache(
        event_id_value,
        cast(str | None, getattr(market, "condition_id", None)),
        cast(str | None, getattr(market, "group_slug", None)),
        cast(str | None, getattr(market, "event_key", None)),
    )
    duration = (time.perf_counter() - start) * 1000
    log_event(
        logger,
        logging.INFO,
        event="markets.create.success",
        message="market persisted",
        event_id=market.event_id,
        category=market.category,
        duration_ms=round(duration, 2),
    )
    response = (await market_svc.enrich_market_models(session, [schemas.MarketResponse.model_validate(market)]))[0]
    return response


@router.patch(
    "/events/{event_id}",
    response_model=schemas.MarketResponse,
    tags=["events"],
    include_in_schema=False,
)
async def update_market(
    event_id: str,
    update: schemas.MarketUpdate,
    session: AsyncSession = Depends(get_session),
    internal_secret: str | None = Header(default=None, alias="X-Internal-Secret"),
) -> schemas.MarketResponse:
    """Partial patch for a market record with cache invalidation."""

    _verify_internal_secret(internal_secret)
    market = await crud.get_market_by_event_id(session, event_id)
    if not market:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="market_not_found")
    start = time.perf_counter()
    log_event(
        logger,
        logging.INFO,
        event="markets.update.request",
        message="patching market",
        event_id=event_id,
        fields=list(update.model_dump(exclude_unset=True).keys()),
    )
    await crud.patch_market(session, market, update)
    await session.flush()
    await session.refresh(market)
    await market_svc.invalidate_market_cache(
        event_id,
        cast(str | None, getattr(market, "condition_id", None)),
        cast(str | None, getattr(market, "group_slug", None)),
        cast(str | None, getattr(market, "event_key", None)),
    )
    duration = (time.perf_counter() - start) * 1000
    log_event(
        logger,
        logging.INFO,
        event="markets.update.success",
        message="market updated",
        event_id=event_id,
        duration_ms=round(duration, 2),
    )
    response = (await market_svc.enrich_market_models(session, [schemas.MarketResponse.model_validate(market)]))[0]
    return response
