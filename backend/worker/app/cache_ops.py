"""Cache invalidation and resolution cache write helpers."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from redis.asyncio import Redis
from redis.exceptions import RedisError
from shared import cache_async as shared_cache
from shared.cache_keys import resolution_cache_key
from shared.logging import log_event

from . import runtime
from .metrics import CACHE_INVALIDATION_COUNTER, CacheInvalidationReport

logger = runtime.logger

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
                    if logger.isEnabledFor(logging.DEBUG):
                        log_event(
                            logger,
                            logging.DEBUG,
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
