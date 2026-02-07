"""Background tasks for the API process (metrics, cache refreshers, quote sweeps).

All loops are async and cancellable so uvicorn shutdowns and tests can stop
them cleanly without leaving dangling threads.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Any, cast

from redis.exceptions import RedisError
from shared.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from shared.logging import log_event, start_heartbeat_logger
from shared.migrations import get_current_revision
from sqlalchemy.exc import SQLAlchemyError

from app import repository_async
from app.database import run_migrations, session_scope
from app.metrics_registry import PRICING_COUNTER
from app.onchain import validate_verifier_circuit_hash
from app.routes.trade import _call_relayer
from app.runtime import logger, request_metrics
from app.runtime import settings as runtime_settings
from app.services.alerting import alert_background_failure
from app.services.cache_client import get_cache_client
from app.services.markets import hydrate_markets_cache

_RNG = random.SystemRandom()
settings: Any = cast(Any, runtime_settings)


async def record_schema_revision_tag() -> None:
    """Persist the current Alembic revision to DB and Redis for cache tagging/health."""

    cache = await get_cache_client()
    persisted = True
    cache_written = False
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
        persisted = False
    if cache is not None:
        try:
            await cache.set(settings.schema_version_key, revision)
            cache_written = True
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                logger,
                logging.WARNING,
                event="schema.revision.cache_failed",
                message="failed to write schema revision cache tag",
                revision=revision,
                error=str(exc),
            )
    log_event(
        logger,
        logging.INFO,
        event="schema.revision.recorded",
        message="schema revision tagging completed",
        revision=revision,
        persisted=persisted,
        cached=cache_written,
    )


async def publish_api_heartbeat() -> None:
    """Publish an API heartbeat payload to Redis for dashboards/health checks."""

    client = await get_cache_client()
    if client is None:
        log_event(
            logger,
            logging.DEBUG,
            event="api.heartbeat.skip",
            message="skipping api heartbeat; redis unavailable",
        )
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
        log_event(
            logger,
            logging.INFO,
            event="markets.cache.refresh.disabled",
            message="cache refresh loop disabled by settings",
        )
        return
    interval = max(1, settings.cache_refresh_interval_seconds)
    failure_count = 0
    cache = await get_cache_client()
    lock_key = "reveal_market:markets_cache_refresh:lock"
    try:
        while True:
            acquired = True
            if cache is not None:
                try:
                    acquired = bool(
                        await cache.set(
                            lock_key,
                            str(time.time()),
                            nx=True,
                            ex=max(int(interval), 5),
                        )
                    )
                except RedisError as exc:
                    acquired = False
                    log_event(
                        logger,
                        logging.WARNING,
                        event="markets.cache.refresh.lock_error",
                        message="failed to acquire cache refresh lock",
                        error=str(exc),
                    )
            if not acquired:
                jitter = min(interval * 0.2, 30)
                wait_seconds = interval + _RNG.uniform(-jitter, jitter)
                await asyncio.sleep(max(1, wait_seconds))
                continue
            try:
                await hydrate_markets_cache(
                    source="refresh", limit=settings.cache_refresh_limit, order_by=settings.cache_hydrate_order_by
                )
                failure_count = 0
            except (
                RedisError,
                SQLAlchemyError,
                RuntimeError,
                ValueError,
            ) as exc:  # pragma: no cover - defensive
                failure_count += 1
                log_event(
                    logger,
                    logging.WARNING,
                    event="markets.cache.refresh.error",
                    message="failed to refresh markets cache",
                    error=str(exc),
                    failures=failure_count,
                )
                await alert_background_failure(
                    "cache_refresh_loop",
                    exc,
                    {"failures": failure_count, "interval_seconds": settings.cache_refresh_interval_seconds},
                )
            jitter = min(interval * 0.2, 30)
            base_wait = interval + _RNG.uniform(-jitter, jitter)
            if failure_count > 0:
                backoff = min(interval * (2 ** (failure_count - 1)), interval * 10)
                wait_seconds = base_wait + backoff
            else:
                wait_seconds = base_wait
            await asyncio.sleep(max(1, wait_seconds))
    except asyncio.CancelledError:
        log_event(
            logger,
            logging.INFO,
            event="markets.cache.refresh.stop",
            message="stopping markets cache refresher",
        )
        raise


async def relayer_queue_loop() -> None:
    """Drain relayer job queue from Redis and replay calls to the relayer."""

    if not settings.relayer_queue_enabled:
        return
    client = await get_cache_client()
    if client is None:
        log_event(
            logger,
            logging.WARNING,
            event="relayer.queue.disabled",
            message="relayer queue disabled (redis unavailable)",
        )
        return
    queue_key = settings.relayer_queue_key
    failure_count = 0
    circuit = CircuitBreaker(
        client,
        CircuitBreakerConfig(
            key_prefix="reveal_market:relayer_circuit",
            failure_threshold=settings.relayer_circuit_failure_threshold,
            window_seconds=settings.relayer_circuit_window_seconds,
            cooldown_seconds=settings.relayer_circuit_cooldown_seconds,
        ),
        logger,
    )
    try:
        while True:
            try:
                if await circuit.is_open("relayer_queue"):
                    await asyncio.sleep(settings.relayer_circuit_cooldown_seconds)
                    continue
                item = await cast(Awaitable[Any], client.brpop([queue_key], timeout=5))
                if item is None:
                    continue
                _, raw = item
                payload = None
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as exc:
                    log_event(
                        logger,
                        logging.WARNING,
                        event="relayer.queue.payload_parse_error",
                        message="failed to parse relayer queue payload",
                        error=str(exc),
                    )
                if payload is None:
                    continue
                job_id = payload.get("job_id")
                endpoint = payload.get("endpoint")
                body = payload.get("payload") or {}
                attempts = int(payload.get("attempts") or 0)
                try:
                    result = await _call_relayer(endpoint, body)
                    await client.set(
                        f"{queue_key}:result:{job_id}",
                        json.dumps(result),
                        ex=settings.relayer_queue_result_ttl_seconds,
                    )
                    failure_count = 0
                    await circuit.record_success("relayer_queue")
                except Exception as exc:  # pragma: no cover - network retry guard
                    attempts += 1
                    failure_count += 1
                    opened = await circuit.record_failure("relayer_queue")
                    if attempts >= settings.relayer_queue_max_attempts:
                        await client.set(
                            f"{queue_key}:result:{job_id}",
                            json.dumps({"status": "failed", "error": str(exc)}),
                            ex=settings.relayer_queue_result_ttl_seconds,
                        )
                    else:
                        payload["attempts"] = attempts
                        await cast(Awaitable[Any], client.lpush(queue_key, json.dumps(payload)))
                    await alert_background_failure(
                        "relayer_queue_loop",
                        exc,
                        {"job_id": job_id, "attempts": attempts, "failures": failure_count},
                    )
                    backoff = min(settings.relayer_retry_backoff_seconds * (2 ** max(failure_count - 1, 0)), 60)
                    await asyncio.sleep(backoff if not opened else settings.relayer_circuit_cooldown_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive loop guard
                log_event(
                    logger,
                    logging.WARNING,
                    event="relayer.queue.error",
                    message="relayer queue loop error; continuing",
                    error=str(exc),
                )
                failure_count += 1
                await alert_background_failure(
                    "relayer_queue_loop",
                    exc,
                    {"failures": failure_count, "interval_seconds": settings.relayer_retry_backoff_seconds},
                )
                backoff = min(settings.relayer_retry_backoff_seconds * (2 ** max(failure_count - 1, 0)), 60)
                opened = await circuit.record_failure("relayer_queue")
                await asyncio.sleep(backoff if not opened else settings.relayer_circuit_cooldown_seconds)
    except asyncio.CancelledError:
        log_event(
            logger,
            logging.INFO,
            event="relayer.queue.stop",
            message="relayer queue loop stopping",
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
                await alert_background_failure(
                    "quote_sweeper_loop",
                    exc,
                    {"interval_seconds": settings.quote_expiry_sweep_interval_seconds},
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

    metrics_interval = max(10, settings.performance_heartbeat_interval_seconds)
    cache_refresh_interval = max(1, settings.cache_refresh_interval_seconds)
    quote_sweep_interval = max(15, settings.quote_expiry_sweep_interval_seconds)
    log_event(
        logger,
        logging.INFO,
        event="service.background.start",
        message="starting background tasks",
        cache_refresh_enabled=settings.cache_refresh_enabled,
        cache_refresh_interval_seconds=cache_refresh_interval,
        quote_sweep_interval_seconds=quote_sweep_interval,
        heartbeat_interval_seconds=settings.container_heartbeat_seconds,
        metrics_interval_seconds=metrics_interval,
    )
    runtime.heartbeat_stop_event = start_heartbeat_logger(
        logger,
        settings.app_name,
        interval_seconds=settings.container_heartbeat_seconds,
        message=f"{settings.app_name} container heartbeat",
    )
    log_event(
        logger,
        logging.DEBUG,
        event="service.background.task_started",
        message="started container heartbeat logger",
        task="container_heartbeat",
        interval_seconds=settings.container_heartbeat_seconds,
    )
    if runtime.metrics_task is None:
        runtime.metrics_task = asyncio.create_task(metrics_publisher_loop(), name="api-metrics-publisher")
        log_event(
            logger,
            logging.INFO,
            event="service.background.task_started",
            message="started background task",
            task="metrics_publisher",
            interval_seconds=metrics_interval,
        )
    if settings.cache_refresh_enabled and runtime.cache_refresh_task is None:
        runtime.cache_refresh_task = asyncio.create_task(cache_refresh_loop(), name="markets-cache-refresh")
        log_event(
            logger,
            logging.INFO,
            event="service.background.task_started",
            message="started background task",
            task="cache_refresh",
            interval_seconds=cache_refresh_interval,
            limit=settings.cache_refresh_limit,
            order_by=settings.cache_hydrate_order_by,
        )
    elif not settings.cache_refresh_enabled:
        log_event(
            logger,
            logging.DEBUG,
            event="service.background.task_skipped",
            message="cache refresh loop disabled",
            task="cache_refresh",
        )
    if runtime.quote_sweeper_task is None:
        runtime.quote_sweeper_task = asyncio.create_task(quote_sweeper_loop(), name="pricing-quote-sweeper")
        log_event(
            logger,
            logging.INFO,
            event="service.background.task_started",
            message="started background task",
            task="quote_sweeper",
            interval_seconds=quote_sweep_interval,
        )
    if settings.relayer_queue_enabled and runtime.relayer_queue_task is None:
        runtime.relayer_queue_task = asyncio.create_task(relayer_queue_loop(), name="relayer-queue")
        log_event(
            logger,
            logging.INFO,
            event="service.background.task_started",
            message="started background task",
            task="relayer_queue",
            queue_key=settings.relayer_queue_key,
        )


async def stop_background_tasks() -> None:
    """Stop and cancel all background loops, swallowing cancellation errors."""

    from app import runtime  # local import to avoid cycle

    log_event(
        logger,
        logging.INFO,
        event="service.background.stop",
        message="stopping background tasks",
    )
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
    for task in (runtime.relayer_queue_task,):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    runtime.metrics_task = None
    runtime.cache_refresh_task = None
    runtime.quote_sweeper_task = None
    runtime.relayer_queue_task = None
    log_event(
        logger,
        logging.DEBUG,
        event="service.background.stopped",
        message="background tasks cleared",
    )


async def run_startup_tasks() -> None:
    """Run migrations, record schema tags, and kick off background loops."""

    start_time = time.perf_counter()
    log_event(
        logger,
        logging.INFO,
        event="service.startup.begin",
        message="running api startup tasks",
        cache_hydrate_on_startup=settings.cache_hydrate_on_startup,
        cache_refresh_enabled=settings.cache_refresh_enabled,
    )
    try:
        run_migrations()
    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            event="service.startup.migrations_failed",
            message="startup failed during migrations",
            error=str(exc),
        )
        raise
    try:
        await validate_verifier_circuit_hash(settings)
    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            event="service.startup.circuit_hash_mismatch",
            message="verifier circuit hash mismatch detected; aborting startup",
            error=str(exc),
        )
        raise
    await record_schema_revision_tag()
    await start_background_tasks()
    hydrate_summary: dict[str, object] | None = None
    if settings.cache_hydrate_on_startup:
        try:
            hydrate_summary = await hydrate_markets_cache(
                source="startup", limit=settings.cache_hydrate_limit, order_by=settings.cache_hydrate_order_by
            )
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                logger,
                logging.WARNING,
                event="service.startup.cache_hydrate_failed",
                message="startup cache hydration failed",
                error=str(exc),
            )
        else:
            if hydrate_summary.get("status") != "hydrated":
                log_event(
                    logger,
                    logging.INFO,
                    event="service.startup.cache_hydrate.skipped",
                    message="startup cache hydration skipped",
                    status=hydrate_summary.get("status"),
                    reason=hydrate_summary.get("reason"),
                    limit=hydrate_summary.get("limit"),
                    order_by=hydrate_summary.get("order_by"),
                )
    else:
        hydrate_summary = {"status": "disabled", "reason": "cache_hydrate_on_startup_disabled"}
    total_duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    log_event(
        logger,
        logging.INFO,
        event="service.startup.complete",
        message="api startup tasks completed",
        duration_ms=total_duration_ms,
        cache_hydrate_status=hydrate_summary.get("status") if hydrate_summary else None,
    )
