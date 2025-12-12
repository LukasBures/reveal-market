"""Async worker orchestration: fetch, persist, cache, and heartbeat publishing."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from shared import cache_async as shared_cache
from shared import models as shared_models
from shared.logging import log_event, start_heartbeat_logger
from sqlalchemy import func, select

from . import runtime
from .cache_ops import invalidate_cache_tags, persist_resolution_cache_updates
from .database import session_scope
from .fetcher import build_filters_from_settings
from .market_sync import (
    SyncSummary,
    apply_retention_cleanup_async,
    backfill_missing_resolutions_async,
    collect_market_changes_with_summary,
    log_resolution_gaps_async,
)
from .prime import prime_featured_views, prime_markets_cache
from .proofs import run_prover_jobs
from .schema import SchemaSyncResult, ensure_schema, propagate_schema_revision

logger = runtime.logger


def _calculate_sleep(start_time: float) -> float:
    """Determine how long the worker should sleep to honour the poll interval."""
    elapsed = time.time() - start_time
    return max(runtime.settings.poll_interval_seconds - elapsed, 0)


def _empty_sync_stats(latency_ms: float = 0.0) -> dict[str, float | int | str | bool]:
    """Return a zeroed-out stats payload so callers can keep metrics flowing."""
    rounded_latency = round(latency_ms, 2)
    return {
        "markets_processed": 0,
        "markets_changed": 0,
        "resolutions_changed": 0,
        "categories_changed": 0,
        "latency_ms": rounded_latency,
        "markets_created": 0,
        "markets_updated": 0,
        "markets_deleted": 0,
        "summaries_enqueued": 0,
        "proofs_generated": 0,
        "cache_invalidations": 0,
        "resolution_gaps": 0,
        "resolutions_backfilled": 0,
        "market_errors": 0,
        "polymarket_ok": False,
        "redis_available": False,
        "timestamp": datetime.now(UTC).isoformat(),
    }


async def publish_heartbeat(redis_client: Redis | None, stats: dict[str, Any]) -> None:
    """Update a Redis key so external monitors can assert liveness."""

    if redis_client is None:
        return
    payload = {
        "service": runtime.settings.app_name,
        "component": "worker",
        "environment": runtime.settings.environment,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "markets_processed": stats.get("markets_processed", 0),
        "markets_changed": stats.get("markets_changed", 0),
        "resolutions_changed": stats.get("resolutions_changed", 0),
        "latency_ms": stats.get("latency_ms"),
        "markets_created": stats.get("markets_created"),
        "markets_updated": stats.get("markets_updated"),
        "markets_deleted": stats.get("markets_deleted"),
        "summaries_enqueued": stats.get("summaries_enqueued"),
        "proofs_generated": stats.get("proofs_generated"),
        "cache_invalidations": stats.get("cache_invalidations"),
        "resolution_gaps": stats.get("resolution_gaps"),
        "market_errors": stats.get("market_errors"),
        "polymarket_ok": bool(stats.get("polymarket_ok", False)),
        "redis_available": True,
    }

    attempts = max(1, runtime.settings.heartbeat_max_retries)
    backoff = max(runtime.settings.heartbeat_retry_backoff_seconds, 0.0)
    max_backoff = max(runtime.settings.heartbeat_retry_backoff_max_seconds, 0.0)
    for attempt in range(1, attempts + 1):
        try:
            await redis_client.set(
                runtime.settings.heartbeat_key,
                json.dumps(payload),
                ex=runtime.settings.heartbeat_ttl_seconds,
            )
            log_event(
                logger,
                logging.DEBUG,
                event="worker.heartbeat.published",
                message="published worker heartbeat",
                markets_processed=payload["markets_processed"],
                markets_changed=payload["markets_changed"],
                resolutions_changed=payload["resolutions_changed"],
                latency_ms=payload["latency_ms"],
                resolution_gaps=payload.get("resolution_gaps"),
                heartbeat_key=runtime.settings.heartbeat_key,
            )
            return
        except Exception as exc:  # pragma: no cover - defensive
            if attempt >= attempts:
                log_event(
                    logger,
                    logging.WARNING,
                    event="worker.heartbeat.error",
                    message="failed to publish worker heartbeat",
                    error=str(exc),
                )
                return
            delay = backoff * (2 ** (attempt - 1))
            if max_backoff > 0:
                delay = min(delay, max_backoff)
            if delay > 0:
                await asyncio.sleep(delay)


async def _handle_sync_failure(
    exc: Exception, start: float, redis_client: Redis | None, schema_state: SchemaSyncResult
):
    """Uniform error handler for sync failures so logging and heartbeats stay consistent."""

    logger.exception(
        "failed to synchronise markets",
        extra={"event": "worker.persist.error", "error": str(exc)},
    )
    latency_ms = (time.perf_counter() - start) * 1000
    stats = _empty_sync_stats(round(latency_ms, 2))
    stats["redis_available"] = redis_client is not None
    log_event(
        logger,
        logging.WARNING,
        event="worker.sync.skipped",
        message="skipping market sync due to upstream failure",
        error=str(exc),
    )
    await publish_heartbeat(redis_client, stats)
    await propagate_schema_revision(redis_client, schema_state)
    return stats


async def _sync_polymarket_feed(redis_client: Redis | None) -> tuple[SyncSummary, int, int, float]:
    """Ingest paginated Polymarket data and apply retention/backfill passes."""
    start = time.perf_counter()
    summary = SyncSummary()
    gap_count = 0
    total_fetched = 0
    log_event(
        logger,
        logging.INFO,
        event="worker.fetch.begin",
        message="starting polymarket fetch",
        page_size=runtime.settings.polymarket_page_size,
        max_pages=runtime.settings.polymarket_max_pages,
    )
    async with session_scope() as session:
        page_no = 0
        async for page in runtime.polymarket_client.fetch_markets_paginated(
            page_size=runtime.settings.polymarket_page_size,
            max_pages=runtime.settings.polymarket_max_pages,
            order=runtime.settings.polymarket_order,
            ascending=runtime.settings.polymarket_sort_ascending,
            closed=runtime.settings.polymarket_closed_filter,
            extra_params=build_filters_from_settings(runtime.settings),
        ):
            page_no += 1
            total_fetched += len(page)
            log_event(
                logger,
                logging.DEBUG,
                event="worker.fetch.page",
                message="fetched polymarket page",
                page=page_no,
                count=len(page),
                total=total_fetched,
            )
            summary = await collect_market_changes_with_summary(session, page, redis_client, summary=summary)
            await session.flush()
            await session.commit()
            session.expunge_all()
        await apply_retention_cleanup_async(session, summary)
        backfilled = await backfill_missing_resolutions_async(session, summary)
        if backfilled:
            log_event(
                logger,
                logging.INFO,
                event="worker.resolution.backfill_complete",
                message="backfilled missing resolution snapshots",
                count=backfilled,
            )
        gap_count = await log_resolution_gaps_async(session)
        log_event(
            logger,
            logging.INFO,
            event="worker.sync.postprocess",
            message="post-processing completed",
            retention_deleted=summary.markets_deleted,
            resolutions_backfilled=summary.resolutions_backfilled,
            resolution_gaps=gap_count,
        )
    latency_ms = (time.perf_counter() - start) * 1000
    return summary, total_fetched, gap_count, latency_ms


async def process_once(redis_client: Redis | None = None) -> dict[str, float | int | str | bool]:
    """Fetch markets, persist them, and emit a heartbeat once."""

    log_event(
        logger,
        logging.INFO,
        event="worker.sync.begin",
        message="starting worker sync tick",
        poll_interval_seconds=runtime.settings.poll_interval_seconds,
    )
    schema_state = await ensure_schema()
    log_event(
        logger,
        logging.DEBUG,
        event="worker.schema.state",
        message="schema check finished for sync tick",
        changed=schema_state.changed,
        current_revision=schema_state.current_revision,
        previous_revision=schema_state.previous_revision,
    )
    tick_start = time.perf_counter()
    try:
        summary, total_fetched, gap_count, latency_ms = await _sync_polymarket_feed(redis_client)
    except Exception as exc:  # pragma: no cover - defensive
        return await _handle_sync_failure(exc, tick_start, redis_client, schema_state)

    summary.proofs_generated = await run_prover_jobs(summary, redis_client)
    log_event(
        logger,
        logging.DEBUG,
        event="worker.proof.jobs_complete",
        message="processed settlement proof jobs",
        proofs_generated=summary.proofs_generated,
    )
    cache_report = await invalidate_cache_tags(redis_client, summary)
    stats = summary.to_stats(total_fetched, latency_ms, cache_report.total)
    stats["resolution_gaps"] = gap_count
    stats["polymarket_ok"] = True

    log_event(
        logger,
        logging.INFO,
        event="worker.sync.summary",
        message="sync tick complete",
        processed=total_fetched,
        created=summary.markets_created,
        updated=summary.markets_updated,
        deleted=summary.markets_deleted,
        resolutions=len(summary.changed_conditions),
        resolutions_backfilled=summary.resolutions_backfilled,
        summaries=summary.summaries_enqueued,
        proofs=summary.proofs_generated,
        latency_ms=round(latency_ms, 2),
        cache_invalidations=cache_report.total,
        market_errors=summary.failed_markets,
        active_markets=stats.get("active_markets"),
        total_markets=stats.get("total_markets"),
    )

    stats["redis_available"] = redis_client is not None
    try:
        async with session_scope() as session:
            total_markets_result = await session.execute(select(func.count(shared_models.Market.id)))
            active_markets_result = await session.execute(
                select(func.count(shared_models.Market.id)).where(shared_models.Market.closed.is_(False))
            )
            stats["total_markets"] = int(total_markets_result.scalar_one() or 0)
            stats["active_markets"] = int(active_markets_result.scalar_one() or 0)
    except Exception as exc:  # pragma: no cover - best-effort diagnostics
        log_event(
            logger,
            logging.DEBUG,
            event="worker.metrics.count_failed",
            message="failed to compute market counts",
            error=str(exc),
        )
    await publish_heartbeat(redis_client, stats)
    await propagate_schema_revision(redis_client, schema_state)
    await persist_resolution_cache_updates(redis_client, summary)
    return stats


async def record_batch_stats(
    redis_client: Redis | None,
    sync_stats: dict[str, float | int | str | bool],
    prime_stats: dict[str, Any],
) -> None:
    """Persist batch-level metrics for observability dashboards."""

    if redis_client is None:
        return
    payload = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "markets_processed": sync_stats.get("markets_processed", 0),
        "markets_changed": sync_stats.get("markets_changed", 0),
        "resolutions_changed": sync_stats.get("resolutions_changed", 0),
        "categories_changed": sync_stats.get("categories_changed", 0),
        "latency_ms": sync_stats.get("latency_ms"),
        "prime": prime_stats,
    }
    try:
        await shared_cache.set_json(
            redis_client, runtime.settings.batch_stats_key, payload, runtime.settings.batch_stats_ttl_seconds
        )
        log_event(
            logger,
            logging.DEBUG,
            event="worker.batch_stats.published",
            message="recorded worker batch stats",
            markets_processed=payload["markets_processed"],
            markets_changed=payload["markets_changed"],
            categories_changed=payload["categories_changed"],
            cache_prime_status=prime_stats.get("status"),
            cache_key=prime_stats.get("cache_key"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="worker.batch_stats.write_failed",
            message="failed to write worker batch stats to cache",
            error=str(exc),
        )


async def _run_worker_tick(redis_client: Redis | None) -> None:
    """Execute a single worker tick with cache priming in parallel."""

    async with asyncio.TaskGroup() as tg:
        process_task = tg.create_task(process_once(redis_client))
        prime_markets_task = tg.create_task(prime_markets_cache(redis_client))
        prime_featured_task = tg.create_task(prime_featured_views(redis_client))

    sync_stats = process_task.result()
    prime_stats = prime_markets_task.result()
    prime_stats.update(prime_featured_task.result())
    await record_batch_stats(redis_client, sync_stats, prime_stats)


async def run_worker() -> None:
    """Main polling loop that downloads markets and writes them into the database asynchronously."""
    try:
        redis_client = Redis.from_url(runtime.settings.redis_url, decode_responses=True)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="worker.redis.error",
            message="unable to connect to redis for heartbeats",
            error=str(exc),
        )
        redis_client = None

    log_event(
        logger,
        logging.INFO,
        event="worker.startup",
        message="starting reveal-market sync worker",
        poll_interval_seconds=runtime.settings.poll_interval_seconds,
        page_size=runtime.settings.polymarket_page_size,
    )
    heartbeat_stop = start_heartbeat_logger(
        logger,
        service_name="reveal_market.worker",
        interval_seconds=runtime.settings.container_heartbeat_seconds,
        message="Worker container heartbeat",
    )
    try:
        while True:
            loop_start = time.time()
            await _run_worker_tick(redis_client)
            await asyncio.sleep(_calculate_sleep(loop_start))
    finally:
        heartbeat_stop.set()
