"""Async worker orchestration: fetch, persist, cache, and heartbeat publishing."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from redis.asyncio import Redis
from shared import cache_async as shared_cache
from shared import models as shared_models
from shared import repository_async
from shared.logging import log_event, start_heartbeat_logger
from sqlalchemy import func, select

from . import runtime
from .backfill import backfill_market_addresses
from .cache_ops import invalidate_cache_tags, persist_resolution_cache_updates
from .database import session_scope
from .market_sync import (
    SyncSummary,
    apply_retention_cleanup_async,
    backfill_missing_resolutions_async,
    collect_market_changes_with_summary,
    log_resolution_gaps_async,
)
from .metrics import LEASE_SKIP_COUNTER, POLYMARKET_FETCH_COUNTER
from .polymarket import build_filters_from_settings
from .prime import prime_featured_views, prime_markets_cache
from .proofs import enqueue_proof_jobs, run_proof_queue_worker, run_prover_jobs, run_settlement_queue_worker
from .schema import SchemaSyncResult, ensure_schema, propagate_schema_revision
from .settlement import run_settlement_jobs

logger = runtime.logger


def _calculate_sleep(start_time: float) -> float:
    """Determine how long the worker should sleep to honour the poll interval."""
    elapsed = time.monotonic() - start_time
    # Aim for a start-to-start cadence so we do not run back-to-back when a tick
    # finishes quickly. Negative means the tick exceeded the interval.
    sleep_for = runtime.settings.poll_interval_seconds - elapsed
    sleep_for = max(sleep_for, 0)
    jitter = max(runtime.settings.poll_interval_jitter_seconds, 0)
    if jitter > 0:
        sleep_for += random.uniform(0, jitter)  # noqa: S311 - non-crypto jitter
    return sleep_for


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


async def _acquire_sync_lease(redis_client: Redis | None) -> bool:
    """Best-effort lease so only one worker paginates Gamma at a time."""

    if redis_client is None:
        return True
    jitter = max(runtime.settings.polymarket_sync_lease_jitter_seconds, 0)
    ttl = max(runtime.settings.polymarket_sync_lease_ttl_seconds, 5)
    ttl_with_jitter = ttl + (random.uniform(0, jitter) if jitter else 0)  # noqa: S311 - non-crypto jitter
    try:
        acquired = await redis_client.set(
            runtime.settings.polymarket_sync_lease_key,
            str(time.time()),
            nx=True,
            ex=int(ttl_with_jitter),
        )
        return bool(acquired)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="worker.sync.lease_error",
            message="failed to acquire polymarket sync lease",
            error=str(exc),
        )
        return True


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
    lease_acquired = await _acquire_sync_lease(redis_client)
    if not lease_acquired:
        LEASE_SKIP_COUNTER.labels(outcome="skipped").inc()
        log_event(
            logger,
            logging.INFO,
            event="worker.fetch.skipped_lease",
            message="skipping polymarket fetch because another worker holds the lease",
            lease_key=runtime.settings.polymarket_sync_lease_key,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        return summary, total_fetched, gap_count, latency_ms
    log_event(
        logger,
        logging.INFO,
        event="worker.fetch.begin",
        message="starting polymarket fetch",
        page_size=runtime.settings.polymarket_page_size,
        max_pages=runtime.settings.polymarket_max_pages,
    )
    attempts = max(1, runtime.settings.polymarket_sync_max_attempts)
    backoff = max(runtime.settings.polymarket_sync_retry_backoff_seconds, 0.0)
    backoff_max = max(runtime.settings.polymarket_sync_retry_backoff_max_seconds, 0.0)
    attempt = 0
    last_exc: Exception | None = None
    while attempt < attempts:
        attempt += 1
        last_exc = None
        page_no = 0
        summary = SyncSummary()
        total_fetched = 0
        gap_count = 0
        try:
            async with session_scope() as session:
                only_open = runtime.settings.polymarket_only_open_markets is True
                closed_param = False if only_open else None
                async for page in runtime.polymarket_client.fetch_events_paginated(
                    page_size=runtime.settings.polymarket_page_size,
                    max_pages=runtime.settings.polymarket_max_pages,
                    order=runtime.settings.polymarket_order,
                    ascending=runtime.settings.polymarket_sort_ascending,
                    closed=closed_param,
                    extra_params=build_filters_from_settings(runtime.settings),
                ):
                    page_start = time.perf_counter()
                    page_no += 1
                    raw_count = len(page)
                    if only_open:
                        page = [market for market in page if getattr(market, "closed", None) is not True]
                    filtered_count = len(page)
                    page_from = total_fetched + 1 if filtered_count else total_fetched
                    total_fetched += filtered_count
                    page_to = total_fetched
                    log_event(
                        logger,
                        logging.DEBUG,
                        event="worker.fetch.page",
                        message="fetched polymarket page",
                        page=page_no,
                        count=filtered_count,
                        raw_count=raw_count,
                        filtered=raw_count - filtered_count if raw_count != filtered_count else None,
                        total=total_fetched,
                        from_index=page_from,
                        to_index=page_to,
                    )
                    if filtered_count == 0:
                        continue
                    process_start = time.perf_counter()
                    timing_before = (
                        summary.timing_match_ms,
                        summary.timing_upsert_ms,
                        summary.timing_normalized_ms,
                        summary.timing_resolution_ms,
                    )
                    summary = await collect_market_changes_with_summary(session, page, redis_client, summary=summary)
                    process_ms = (time.perf_counter() - process_start) * 1000
                    timing_after = (
                        summary.timing_match_ms,
                        summary.timing_upsert_ms,
                        summary.timing_normalized_ms,
                        summary.timing_resolution_ms,
                    )
                    delta_match = timing_after[0] - timing_before[0]
                    delta_upsert = timing_after[1] - timing_before[1]
                    delta_normalized = timing_after[2] - timing_before[2]
                    delta_resolution = timing_after[3] - timing_before[3]
                    flush_start = time.perf_counter()
                    await session.flush()
                    flush_ms = (time.perf_counter() - flush_start) * 1000
                    commit_start = time.perf_counter()
                    await session.commit()
                    commit_ms = (time.perf_counter() - commit_start) * 1000
                    expunge_start = time.perf_counter()
                    session.expunge_all()  # keep identity map small between pages
                    expunge_ms = (time.perf_counter() - expunge_start) * 1000
                    page_duration_ms = (time.perf_counter() - page_start) * 1000
                    log_event(
                        logger,
                        logging.INFO,
                        event="worker.sync.page",
                        message="processed polymarket page",
                        page=page_no,
                        count=len(page),
                        total=total_fetched,
                        duration_ms=round(page_duration_ms, 2),
                        process_ms=round(process_ms, 2),
                        flush_ms=round(flush_ms, 2),
                        commit_ms=round(commit_ms, 2),
                        expunge_ms=round(expunge_ms, 2),
                        match_ms=round(delta_match, 2),
                        upsert_ms=round(delta_upsert, 2),
                        normalized_ms=round(delta_normalized, 2),
                        resolution_ms=round(delta_resolution, 2),
                    )
                await apply_retention_cleanup_async(session, summary)
                log_event(
                    logger,
                    logging.INFO,
                    event="worker.sync.retention_complete",
                    message="retention cleanup finished",
                )
                backfilled = await backfill_missing_resolutions_async(session, summary)
                log_event(
                    logger,
                    logging.INFO,
                    event="worker.sync.backfill_complete",
                    message="resolution backfill finished",
                    backfilled=backfilled,
                )
                if runtime.settings.factory_address and runtime.settings.rpc_url:
                    updated = await backfill_market_addresses(
                        session,
                        rpc_url=str(runtime.settings.rpc_url),
                        factory_address=str(runtime.settings.factory_address),
                        get_markets_missing_address=repository_async.list_markets_missing_address,
                    )
                    if updated:
                        log_event(
                            logger,
                            logging.INFO,
                            event="worker.resolution.backfill_addresses",
                            message="backfilled market addresses",
                            count=updated,
                        )
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
            break
        except (httpx.HTTPError, httpx.RequestError, RuntimeError, ValueError) as exc:
            last_exc = exc
            if attempt >= attempts:
                POLYMARKET_FETCH_COUNTER.labels(outcome="error").inc()
                log_event(
                    logger,
                    logging.ERROR,
                    event="worker.fetch.error",
                    message="failed to fetch markets from polymarket after retries",
                    attempt=attempt,
                    max_attempts=attempts,
                    error=str(exc),
                )
                raise
            delay = backoff * (2 ** (attempt - 1))
            if backoff_max > 0:
                delay = min(delay, backoff_max)
            log_event(
                logger,
                logging.WARNING,
                event="worker.fetch.retry",
                message="retrying polymarket fetch",
                attempt=attempt,
                max_attempts=attempts,
                delay_seconds=delay,
                error=str(exc),
            )
            if delay > 0:
                await asyncio.sleep(delay)
            continue
    if total_fetched > 0:
        POLYMARKET_FETCH_COUNTER.labels(outcome="success").inc()
    else:
        outcome = "empty" if last_exc is None else "error"
        POLYMARKET_FETCH_COUNTER.labels(outcome=outcome).inc()
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

    async def _run_proofs_and_settlements(summary_obj: SyncSummary) -> None:
        try:
            proofs_generated = await run_prover_jobs(summary_obj, redis_client)
            settlements_submitted = await run_settlement_jobs(summary_obj, redis_client)
            log_event(
                logger,
                logging.INFO,
                event="worker.proof.jobs_complete",
                message="processed settlement proof jobs",
                proofs_generated=proofs_generated,
                settlements_submitted=settlements_submitted,
            )
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                logger,
                logging.WARNING,
                event="worker.proof.jobs_failed",
                message="proof/settlement jobs failed",
                error=str(exc),
            )

    if redis_client is not None:
        enqueued = await enqueue_proof_jobs(redis_client, summary)
        log_event(
            logger,
            logging.DEBUG,
            event="worker.proof.jobs_enqueued",
            message="enqueued proof jobs to background queue",
            enqueued=enqueued,
        )
    else:
        asyncio.create_task(_run_proofs_and_settlements(summary))
    summary.proofs_generated = 0
    summary.settlement_txs = 0
    cache_report = await invalidate_cache_tags(redis_client, summary)
    summary.cache_invalidations = cache_report.total
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
        gamma_metadata_updates=summary.gamma_metadata_updates,
        gamma_events_written=summary.gamma_events_written,
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
    proof_worker_task: asyncio.Task | None = None
    settlement_worker_task: asyncio.Task | None = None
    if redis_client is not None:
        proof_worker_task = asyncio.create_task(run_proof_queue_worker(redis_client))
        settlement_worker_task = asyncio.create_task(run_settlement_queue_worker(redis_client))
    try:
        while True:
            loop_start = time.monotonic()
            try:
                await _run_worker_tick(redis_client)
                sleep_for = _calculate_sleep(loop_start)
            except Exception as exc:  # pragma: no cover - defensive
                log_event(
                    logger,
                    logging.ERROR,
                    event="worker.tick.failed",
                    message="worker tick failed; backing off before retry",
                    error=str(exc),
                )
                failure_stats = _empty_sync_stats()
                failure_stats["redis_available"] = redis_client is not None
                await publish_heartbeat(redis_client, failure_stats)
                sleep_for = runtime.settings.poll_interval_seconds
            log_event(
                logger,
                logging.INFO,
                event="worker.sleep",
                message="sleeping before next sync tick",
                sleep_seconds=round(sleep_for, 2),
                elapsed_seconds=round(time.monotonic() - loop_start, 2),
                poll_interval_seconds=runtime.settings.poll_interval_seconds,
            )
            await asyncio.sleep(sleep_for)
    finally:
        heartbeat_stop.set()
        if proof_worker_task is not None:
            proof_worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await proof_worker_task
        if settlement_worker_task is not None:
            settlement_worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await settlement_worker_task
