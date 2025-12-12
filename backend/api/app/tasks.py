"""Background tasks for the API process (metrics, cache refreshers, quote sweeps).

All loops are async and cancellable so uvicorn shutdowns and tests can stop
them cleanly without leaving dangling threads.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import UTC, datetime

from redis.exceptions import RedisError
from shared.logging import log_event, start_heartbeat_logger
from shared.migrations import get_current_revision
from sqlalchemy.exc import SQLAlchemyError

from app import repository_async
from app.database import run_migrations, session_scope
from app.metrics_registry import PRICING_COUNTER
from app.runtime import logger, request_metrics, settings
from app.services.cache_client import get_cache_client
from app.services.markets import hydrate_markets_cache

_RNG = random.SystemRandom()


async def record_schema_revision_tag() -> None:
    """Persist the current Alembic revision to DB and Redis for cache tagging/health."""

    cache = await get_cache_client()
    try:
        revision = get_current_revision(settings.database_url)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="schema.revision.resolve_failed",
            message="failed to resolve schema revision after migrations",
            error=str(exc),
        )
        return
    if revision is None:
        log_event(
            logger,
            logging.WARNING,
            event="schema.revision.missing",
            message="schema revision missing after migrations",
        )
        return
    try:
        async with session_scope() as session:
            await repository_async.record_schema_version(session, revision, key=settings.schema_version_key)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="schema.revision.persist_failed",
            message="failed to record schema revision",
            revision=revision,
            error=str(exc),
        )
    if cache is not None:
        try:
            await cache.set(settings.schema_version_key, revision)
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                logger,
                logging.WARNING,
                event="schema.revision.cache_failed",
                message="failed to write schema revision cache tag",
                revision=revision,
                error=str(exc),
            )


async def publish_api_heartbeat() -> None:
    """Publish an API heartbeat payload to Redis for dashboards/health checks."""

    client = await get_cache_client()
    if client is None:
        return
    snapshot = request_metrics.snapshot()
    payload = {
        "service": settings.app_name,
        "component": "api",
        "environment": settings.environment,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "uptime_seconds": snapshot.get("window_seconds"),
        "metrics": {
            **snapshot,
            "window_started_at": datetime.fromtimestamp(snapshot["window_started_at"], tz=UTC).isoformat()
            if snapshot.get("window_started_at")
            else None,
            "last_updated_at": datetime.fromtimestamp(snapshot["last_updated_at"], tz=UTC).isoformat()
            if snapshot.get("last_updated_at")
            else None,
        },
    }
    try:
        await client.set(
            settings.api_heartbeat_key,
            json.dumps(payload),
            ex=settings.api_heartbeat_ttl_seconds,
        )
    except RedisError as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="api.heartbeat.error",
            message="failed to publish api heartbeat",
            error=str(exc),
        )
    else:
        log_event(
            logger,
            logging.DEBUG,
            event="api.heartbeat.published",
            message="published api heartbeat snapshot",
            requests_total=snapshot.get("total_requests"),
            cache_hit_rate=snapshot.get("cache_hit_rate"),
            avg_latency_ms=snapshot.get("avg_latency_ms"),
        )


async def metrics_publisher_loop() -> None:
    """Periodically emit API heartbeat metrics into Redis."""

    interval = max(10, settings.performance_heartbeat_interval_seconds)
    try:
        while True:
            await publish_api_heartbeat()
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        log_event(
            logger,
            logging.INFO,
            event="api.heartbeat.stop",
            message="api heartbeat publisher stopping",
        )
        raise


async def cache_refresh_loop() -> None:
    """Continuously hydrate the hottest markets into Redis with jittered delays."""

    if not settings.cache_refresh_enabled:
        return
    interval = max(1, settings.cache_refresh_interval_seconds)
    try:
        while True:
            try:
                await hydrate_markets_cache(
                    source="refresh", limit=settings.cache_refresh_limit, order_by=settings.cache_hydrate_order_by
                )
            except (
                RedisError,
                SQLAlchemyError,
                RuntimeError,
                ValueError,
            ) as exc:  # pragma: no cover - defensive
                log_event(
                    logger,
                    logging.WARNING,
                    event="markets.cache.refresh.error",
                    message="failed to refresh markets cache",
                    error=str(exc),
                )
            jitter = min(interval * 0.2, 30)
            # Add small jitter so parallel workers do not all refresh at once.
            wait_seconds = interval + _RNG.uniform(-jitter, jitter)
            await asyncio.sleep(max(1, wait_seconds))
    except asyncio.CancelledError:
        log_event(
            logger,
            logging.INFO,
            event="markets.cache.refresh.stop",
            message="stopping markets cache refresher",
        )
        raise


async def quote_sweeper_loop(*, run_once: bool = False) -> None:
    """Expire stale quotes from Postgres on an interval or a single run for tests."""

    interval = max(15, settings.quote_expiry_sweep_interval_seconds)
    try:
        while True:
            try:
                async with session_scope() as session:
                    expired = await repository_async.expire_stale_quotes(session)
                    await session.flush()
                    if expired:
                        PRICING_COUNTER.labels(event="sweep", result="expired").inc(expired)
                        log_event(
                            logger,
                            logging.INFO,
                            event="pricing.quote.sweep",
                            message="expired stale quotes",
                            expired=expired,
                            ttl_seconds=settings.quote_store_ttl_seconds,
                        )
            except (SQLAlchemyError, RedisError, RuntimeError, ValueError) as exc:  # pragma: no cover - defensive
                log_event(
                    logger,
                    logging.WARNING,
                    event="pricing.quote.sweep_error",
                    message="quote expiry sweep failed",
                    error=str(exc),
                )
            if run_once:
                break
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        log_event(
            logger,
            logging.INFO,
            event="pricing.quote.sweep.stop",
            message="stopping quote sweeper",
        )
        raise


async def start_background_tasks() -> None:
    """Start all background loops; safe to call multiple times."""

    from app import runtime  # local import to avoid cycle

    runtime.heartbeat_stop_event = start_heartbeat_logger(
        logger,
        settings.app_name,
        interval_seconds=settings.container_heartbeat_seconds,
        message=f"{settings.app_name} container heartbeat",
    )
    if runtime.metrics_task is None:
        runtime.metrics_task = asyncio.create_task(metrics_publisher_loop(), name="api-metrics-publisher")
    if settings.cache_refresh_enabled and runtime.cache_refresh_task is None:
        runtime.cache_refresh_task = asyncio.create_task(cache_refresh_loop(), name="markets-cache-refresh")
    if runtime.quote_sweeper_task is None:
        runtime.quote_sweeper_task = asyncio.create_task(quote_sweeper_loop(), name="pricing-quote-sweeper")


async def stop_background_tasks() -> None:
    """Stop and cancel all background loops, swallowing cancellation errors."""

    from app import runtime  # local import to avoid cycle

    if runtime.heartbeat_stop_event is not None:
        runtime.heartbeat_stop_event.set()
        runtime.heartbeat_stop_event = None
    for task in (runtime.metrics_task, runtime.cache_refresh_task, runtime.quote_sweeper_task):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    runtime.metrics_task = None
    runtime.cache_refresh_task = None
    runtime.quote_sweeper_task = None


async def run_startup_tasks() -> None:
    """Run migrations, record schema tags, and kick off background loops."""

    run_migrations()
    await record_schema_revision_tag()
    await start_background_tasks()
    if settings.cache_hydrate_on_startup:
        await hydrate_markets_cache(
            source="startup", limit=settings.cache_hydrate_limit, order_by=settings.cache_hydrate_order_by
        )
