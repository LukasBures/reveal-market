"""Cache priming helpers for homepage, categories, and suggest endpoints."""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import quote_plus

import httpx
from redis.asyncio import Redis
from shared import cache_async as shared_cache
from shared.cache_keys import markets_list_cache_key, suggest_cache_key
from shared.logging import log_event

from . import runtime

logger = runtime.logger


async def prime_markets_cache(
    redis_client: Redis | None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Fetch and cache the homepage markets list so the API responds instantly."""

    limit = runtime.settings.markets_cache_limit
    base_offset = runtime.settings.markets_cache_offset
    order_by_setting = runtime.settings.markets_cache_order_by
    order_by = "volume" if order_by_setting == "volume_24h_usd" else order_by_setting
    max_pages = max(1, runtime.settings.markets_cache_prime_pages)
    cache_key = markets_list_cache_key(None, None, None, None, limit, base_offset, order_by=order_by)
    summary: dict[str, Any] = {
        "status": "skipped",
        "limit": limit,
        "offset": base_offset,
        "order_by": order_by,
        "cache_key": cache_key,
        "pages": [],
    }

    if redis_client is None:
        summary["reason"] = "redis_unavailable"
        return summary
    if not runtime.settings.prime_markets_cache_enabled:
        summary["reason"] = "disabled"
        return summary
    if not runtime.settings.api_base_url:
        summary["reason"] = "api_base_url_missing"
        return summary

    url = f"{runtime.settings.api_base_url.rstrip('/')}/markets"
    start = time.perf_counter()
    page_summaries: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(
            timeout=runtime.settings.cache_prime_timeout_seconds, transport=transport
        ) as client:
            for page_index in range(max_pages):
                offset = base_offset + page_index * limit
                params: dict[str, int | str] = {"limit": limit, "offset": offset}
                if order_by:
                    params["order_by"] = order_by
                response = await client.get(url, params=params)  # type: ignore[arg-type]
                response.raise_for_status()
                payload = response.json()
                result_count = len(payload) if isinstance(payload, list) else 0
                page_key = markets_list_cache_key(None, None, None, None, limit, offset, order_by=order_by)
                page_summary = {
                    "offset": offset,
                    "cache_key": page_key,
                    "result_count": result_count,
                }
                page_summaries.append(page_summary)
                try:
                    await shared_cache.set_json(
                        redis_client, page_key, payload, runtime.settings.markets_cache_ttl_seconds
                    )
                    schema_tag = await shared_cache.get_schema_tag(redis_client, runtime.settings.schema_version_key)
                    await shared_cache.add_tag(redis_client, schema_tag, page_key)
                    await shared_cache.add_tag(redis_client, "markets:list", page_key)
                except Exception as exc:  # pragma: no cover - defensive
                    log_event(
                        logger,
                        logging.WARNING,
                        event="worker.cache.prime_write_failed",
                        message="failed to store primed homepage cache",
                        cache_key=page_key,
                        error=str(exc),
                    )
                if result_count < limit:
                    break
    except Exception as exc:  # pragma: no cover - defensive
        duration_ms = (time.perf_counter() - start) * 1000
        log_event(
            logger,
            logging.WARNING,
            event="worker.cache.prime_failed",
            message="failed to prime homepage markets cache",
            limit=limit,
            offset=base_offset,
            cache_key=cache_key,
            error=str(exc),
        )
        summary.update(
            {
                "status": "error",
                "error": str(exc),
                "duration_ms": round(duration_ms, 2),
            }
        )
        return summary

    duration_ms = (time.perf_counter() - start) * 1000
    total_results = sum(page.get("result_count", 0) for page in page_summaries)
    summary.update(
        {
            "status": "primed",
            "duration_ms": round(duration_ms, 2),
            "result_count": total_results,
            "cache_key": page_summaries[0]["cache_key"] if page_summaries else cache_key,
            "pages": page_summaries,
        }
    )
    log_event(
        logger,
        logging.DEBUG,
        event="worker.cache.primed",
        message="prefetched markets via API",
        limit=limit,
        order_by=order_by,
        pages=len(page_summaries),
        total_result_count=total_results,
        duration_ms=round(duration_ms, 2),
    )
    return summary


async def prime_featured_views(
    redis_client: Redis | None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    suggestion_ttls: dict[str, int] = {}
    summary: dict[str, Any] = {
        "categories_primed": 0,
        "suggestions_primed": 0,
        "suggestion_ttls": suggestion_ttls,
    }
    if redis_client is None or not runtime.settings.api_base_url:
        return summary
    if not runtime.settings.featured_categories and not runtime.settings.featured_suggest_queries:
        return summary
    base_url = runtime.settings.api_base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=runtime.settings.cache_prime_timeout_seconds, transport=transport) as client:
        for category in runtime.settings.featured_categories:
            slug = quote_plus(category)
            params = {"limit": runtime.settings.category_cache_limit}
            try:
                response = await client.get(f"{base_url}/categories/{slug}", params=params)
                if response.is_success:
                    summary["categories_primed"] += 1
            except Exception as exc:
                log_event(
                    logger,
                    logging.WARNING,
                    event="worker.cache.featured_category_failed",
                    message="failed to prime category cache",
                    category=category,
                    error=str(exc),
                )
        for query in runtime.settings.featured_suggest_queries:
            suggest_params: dict[str, str | int] = {"q": query, "limit": runtime.settings.suggest_cache_limit}
            try:
                response = await client.get(f"{base_url}/markets/suggest", params=suggest_params)
                if response.is_success:
                    summary["suggestions_primed"] += 1
                    key = suggest_cache_key(query, runtime.settings.suggest_cache_limit)
                    try:
                        ttl = await redis_client.ttl(key)
                    except Exception as exc:  # pragma: no cover - defensive
                        log_event(
                            logger,
                            logging.WARNING,
                            event="worker.cache.suggest_ttl_failed",
                            message="failed to read suggestion cache ttl",
                            query=query,
                            error=str(exc),
                        )
                        ttl = runtime.settings.markets_cache_ttl_seconds
                    ttl_value = ttl if isinstance(ttl, (int, float)) else None
                    if ttl_value is None or ttl_value < 0:
                        ttl_value = runtime.settings.markets_cache_ttl_seconds
                    suggestion_ttls[query] = int(ttl_value)
            except Exception as exc:
                log_event(
                    logger,
                    logging.WARNING,
                    event="worker.cache.featured_suggest_failed",
                    message="failed to prime suggestion cache",
                    query=query,
                    error=str(exc),
                )

    log_event(
        logger,
        logging.DEBUG,
        event="worker.cache.featured",
        message="primed featured caches",
        categories=runtime.settings.featured_categories,
        suggest_queries=runtime.settings.featured_suggest_queries,
        categories_primed=summary["categories_primed"],
        suggestions_primed=summary["suggestions_primed"],
        suggestion_ttls=summary["suggestion_ttls"],
    )
    return summary
