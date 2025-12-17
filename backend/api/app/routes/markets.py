"""Market routes and cache-aware handlers."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from datetime import UTC, datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from py_clob_client.client import ClobClient
from shared.cache_async import add_tag, add_tags, get_json, get_schema_tag, set_json
from shared.cache_keys import markets_list_cache_key, resolution_cache_key, suggest_cache_key
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
from app.services.cache_client import get_cache_client

router = APIRouter()


@router.get("/markets", response_model=list[schemas.MarketResponse], tags=["markets"])
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
    coalesce_groups: Annotated[
        bool | None, Query(description="Return a single representative per group_slug", alias="coalesce_groups")
    ] = None,
    session: AsyncSession = Depends(get_session),
) -> list[schemas.MarketResponse]:
    """List markets with optional filters and heavy reliance on Redis caches."""

    coalesce_mode = bool(coalesce_groups)
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
        coalesce_groups=coalesce_groups,
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
        coalesce_groups=coalesce_mode,
    )
    start = time.perf_counter()
    cache_enabled = cache is not None and market_svc.should_cache_market_list(
        limit, offset, normalized_search, normalized_order_by
    )
    if cache_enabled:
        cached_payload = await get_json(cache, cache_key)
        hydrated = await market_svc.hydrate_cached_market_list(cache, cached_payload)
        if hydrated is not None:
            hydrated = await market_svc.enrich_market_models(session, hydrated)
            update_cache_context(request, cache_key=cache_key, hit=True, source="markets:list")
            MARKETS_CACHE_COUNTER.labels(outcome="hit", status=status or "*", category=category or "*").inc()
            duration = (time.perf_counter() - start) * 1000
            cached_models = market_svc.filter_markets_for_visibility(hydrated)
            if coalesce_mode and cached_models:
                cached_models = market_svc.coalesce_grouped_markets(cached_models, use_total_volume=total_volume_mode)
            if volume_mode and cached_models:
                cached_models.sort(
                    key=lambda m: (
                        market_svc.market_volume_value(m, use_total=total_volume_mode),
                        getattr(m, "updated_at", None) or datetime.fromtimestamp(0, tz=UTC),
                    ),
                    reverse=True,
                )
            cached_models = cached_models[:limit]
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
                result_count=len(cached_models),
                featured=featured,
                coalesce_groups=coalesce_mode,
            )
            return cached_models
        MARKETS_CACHE_COUNTER.labels(outcome="miss", status=status or "*", category=category or "*").inc()
        update_cache_context(request, cache_key=cache_key, hit=False, source="markets:list")
    else:
        MARKETS_CACHE_COUNTER.labels(outcome="bypass", status=status or "*", category=category or "*").inc()
        update_cache_context(request, cache_key=None, hit=False, source="markets:list")

    query_limit = limit
    query_offset = offset
    if popularity_mode:
        query_limit = min(settings.max_page_size, max(limit * 4, settings.default_page_size))
        query_offset = 0
    elif volume_mode:
        if total_volume_mode and coalesce_mode:
            query_limit = min(settings.max_page_size, max(limit * 3, settings.default_page_size))
        else:
            query_limit = min(settings.max_page_size, max(limit * 3, settings.default_page_size))
        query_offset = offset
    if coalesce_mode:
        multiplier = 1 if total_volume_mode else 3
        query_limit = min(settings.max_page_size, max(query_limit, limit * multiplier))
    markets = await crud.get_markets(
        session,
        status=status,
        category=category,
        oracle=oracle,
        search=normalized_search,
        featured=featured,
        limit=query_limit,
        offset=query_offset,
        order_by=normalized_order_by,
        coalesce_groups=coalesce_mode,
    )
    market_models = await market_svc.enrich_market_models(
        session, [schemas.MarketResponse.model_validate(m) for m in markets]
    )
    market_models = market_svc.filter_markets_for_visibility(market_models)
    if coalesce_mode and market_models:
        market_models = market_svc.coalesce_grouped_markets(market_models, use_total_volume=total_volume_mode)
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
    effective_offset = offset if query_offset == 0 else 0
    market_models = market_models[effective_offset : effective_offset + limit]
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
    if cache_enabled and market_models:
        schema_tag = await get_schema_tag(cache, settings.schema_version_key)
        await market_svc.write_market_list_cache(cache, cache_key, market_models)
        await add_tag(cache, schema_tag, cache_key)
        await add_tag(cache, "markets:list", cache_key)
        await add_tags(
            cache,
            [f"market:{item.event_id}" for item in market_models if item.event_id],
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
        )
    return market_models


@router.get("/categories/{category_slug}", response_model=list[schemas.MarketResponse], tags=["markets"])
async def list_markets_by_category(
    category_slug: str,
    request: Request,
    limit: Annotated[
        int,
        Query(ge=1, le=settings.max_page_size, description="Maximum number of markets to return"),
    ] = settings.default_page_size,
    offset: Annotated[int, Query(ge=0, description="Offset into the result set")] = 0,
    coalesce_groups: Annotated[
        bool | None, Query(description="Return a single representative per group_slug", alias="coalesce_groups")
    ] = None,
    session: AsyncSession = Depends(get_session),
) -> list[schemas.MarketResponse]:
    """List markets for a category, with fallbacks when slugs are unfamiliar."""

    order_by = request.query_params.get("order_by")
    normalized_order_by = "volume" if order_by == "volume_24h_usd" else order_by
    volume_mode = normalized_order_by == "volume"
    total_volume_mode = normalized_order_by == "volume"
    coalesce_mode = bool(coalesce_groups)
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
        coalesce_groups=bool(coalesce_groups),
    )
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
        coalesce_groups=coalesce_groups,
    )
    cache_enabled = cache is not None and market_svc.should_cache_market_list(limit, offset, None, normalized_order_by)
    if cache_enabled:
        cached_payload = await get_json(cache, cache_key)
        hydrated = await market_svc.hydrate_cached_market_list(cache, cached_payload)
        if hydrated is not None:
            hydrated = await market_svc.enrich_market_models(session, hydrated)
            update_cache_context(request, cache_key=cache_key, hit=True, source="markets:category")
            models_from_cache = market_svc.filter_markets_for_visibility(hydrated)
            if coalesce_mode and models_from_cache:
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
                coalesce_groups=coalesce_mode,
            )
            return models_from_cache
        update_cache_context(request, cache_key=cache_key, hit=False, source="markets:category")
    else:
        update_cache_context(request, cache_key=None, hit=False, source="markets:category")

    trending_category = category_slug_key == "trending"
    fetch_limit = limit
    fetch_offset = offset
    if coalesce_mode:
        multiplier = 1 if total_volume_mode else 3
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
    )
    if trending_category:
        markets = await crud.get_markets(
            session,
            limit=fetch_limit,
            offset=fetch_offset,
            order_by=normalized_order_by,
            coalesce_groups=coalesce_mode,
        )
    else:
        markets = await crud.get_markets(
            session,
            category=category_label,
            limit=fetch_limit,
            offset=fetch_offset,
            order_by=normalized_order_by,
            coalesce_groups=coalesce_mode,
        )
    market_models = market_svc.filter_markets_for_visibility(
        await market_svc.enrich_market_models(session, [schemas.MarketResponse.model_validate(m) for m in markets])
    )
    if not market_models and not trending_category and offset == 0:
        fallback_matches = await market_svc.fallback_markets_by_category_slug(session, category_slug_key, limit)
        if fallback_matches:
            market_models = market_svc.filter_markets_for_visibility(
                await market_svc.enrich_market_models(session, fallback_matches)
            )
    if coalesce_mode and market_models:
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
        )
        update_cache_context(request, cache_key=None, hit=False, source="markets:category")
    return market_models


@router.get("/markets/group/{group_slug}", response_model=schemas.GroupedMarketsResponse, tags=["markets"])
async def list_grouped_markets(
    group_slug: str,
    session: AsyncSession = Depends(get_session),
) -> schemas.GroupedMarketsResponse:
    """Return markets that belong to a group_slug plus aggregate metrics."""

    normalized_slug = group_slug.strip().lower()
    markets = await crud.get_markets_by_group_slug(session, normalized_slug)
    if not markets:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="group_not_found")
    market_models = await market_svc.enrich_market_models(
        session, [schemas.MarketResponse.model_validate(m) for m in markets], include_siblings=True
    )

    def _group_sort_key(market: schemas.MarketResponse):
        position = getattr(market, "group_position", None)
        threshold = getattr(market, "group_item_threshold", None)
        closes_at = market_svc.normalize_datetime(getattr(market, "closes_at", None))
        return (
            position if position is not None else threshold if threshold is not None else float("inf"),
            closes_at or datetime.max.replace(tzinfo=UTC),
            getattr(market, "slug", None) or getattr(market, "event_id", ""),
        )

    market_models.sort(key=_group_sort_key)
    aggregate_volume = market_svc.safe_float(market_models[0].volume_24h_usd) if market_models else None
    aggregate_liquidity = market_svc.safe_float(market_models[0].liquidity_usd) if market_models else None
    return schemas.GroupedMarketsResponse(
        group_slug=normalized_slug,
        markets=market_models,
        aggregate_volume_24h_usd=aggregate_volume,
        aggregate_liquidity_usd=aggregate_liquidity,
    )


@router.get("/markets/onchain", tags=["markets"], include_in_schema=False)
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


@router.get("/markets/stats", response_model=list[schemas.MarketStatusBreakdown], tags=["markets"])
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


@router.get("/markets/suggest", response_model=list[schemas.MarketResponse], tags=["markets"])
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

    results = await crud.search_markets(session, normalized_query, limit)
    market_models = [schemas.MarketResponse.model_validate(m) for m in results]
    filtered = market_svc.filter_markets_for_visibility(await market_svc.enrich_market_models(session, market_models))
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


@router.get("/markets/{event_id}", response_model=schemas.MarketResponse, tags=["markets"])
async def read_market(
    event_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> schemas.MarketResponse:
    """Return a single market detail record, hydrating siblings when cached."""

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
        return model

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
            if getattr(response, "group_slug", None):
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
    return response


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
    "/markets",
    response_model=schemas.MarketResponse,
    tags=["markets"],
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def upsert_market(
    market_in: schemas.MarketCreate, session: AsyncSession = Depends(get_session)
) -> schemas.MarketResponse:
    """Create or update a market record and invalidate relevant caches."""

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
    "/markets/{event_id}",
    response_model=schemas.MarketResponse,
    tags=["markets"],
    include_in_schema=False,
)
async def update_market(
    event_id: str, update: schemas.MarketUpdate, session: AsyncSession = Depends(get_session)
) -> schemas.MarketResponse:
    """Partial patch for a market record with cache invalidation."""

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
