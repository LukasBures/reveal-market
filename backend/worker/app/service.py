"""Async worker orchestration: fetch, persist, cache, and heartbeat publishing."""

from __future__ import annotations

import asyncio
import contextlib
import gc
import json
import logging
import random
import time
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

import httpx
from redis.asyncio import Redis
from shared import cache_async as shared_cache
from shared import models as shared_models
from shared import repository_async
from shared.cache_keys import market_stats_cache_key
from shared.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from shared.logging import log_event, start_heartbeat_logger
from sqlalchemy import and_, func, or_, select
from sqlalchemy.sql.elements import ColumnElement

from . import runtime
from .backfill import backfill_market_addresses, backfill_market_params
from .cache_ops import invalidate_cache_tags, persist_resolution_cache_updates
from .database import session_scope
from .market_sync import (
    SyncSummary,
    apply_retention_cleanup_async,
    backfill_missing_resolutions_async,
    collect_market_changes_with_summary,
    log_resolution_gaps_async,
    market_record_to_payload,
    snapshot_market_record,
)
from .metrics import LEASE_SKIP_COUNTER, POLYMARKET_FETCH_COUNTER
from .polymarket import MarketPayload, build_filters_from_settings
from .prime import prime_featured_views, prime_markets_cache
from .proofs import (
    enqueue_proof_jobs,
    enqueue_settlement_job,
    run_proof_queue_worker,
    run_prover_jobs,
    run_settlement_queue_worker,
)
from .retry import clear_failure, failure_key, record_failure, should_attempt
from .schema import SchemaSyncResult, ensure_schema, propagate_schema_revision
from .settlement import (
    _upsert_settlement_from_chain,
    run_lock_batches_jobs,
    run_settlement_jobs,
    settlement_needs_refresh,
)

logger = runtime.logger

_LAST_CLOSED_RECONCILE_TS: float | None = None
_LAST_POLYMARKET_UPDATED_AT_TS: float | None = None
_LAST_MEMORY_PRESSURE_SCAN_TS: float | None = None
_LAST_SYNC_LEASE_FAILURE_TS: float | None = None


class MemoryStats(TypedDict, total=False):
    mem_rss_mb: float
    mem_hwm_mb: float
    mem_vms_mb: float
    mem_data_mb: float
    mem_cgroup_current_mb: float
    mem_cgroup_limit_mb: float
    mem_trimmed: bool
    mem_rss_mb_post_trim: float | None
    mem_hwm_mb_post_trim: float | None
    gc_gen0: int
    gc_gen1: int
    gc_gen2: int


class MemoryPressureStats(TypedDict):
    market_payload_objects: int
    market_orm_objects: int


def _build_market_stats_payload(market: MarketPayload) -> dict[str, Any]:
    return {
        "best_bid": market.best_bid,
        "best_ask": market.best_ask,
        "spread": market.spread,
        "volume": market.volume,
        "open_interest": market.open_interest,
        "liquidity_usd": market.liquidity_usd,
        "volume_24h_usd": market.volume_24h_usd,
        "orderbook_volume_usd": market.orderbook_volume_usd,
        "trades_quantity": market.trades_quantity,
    }


async def _persist_market_stats(redis_client: Redis | None, markets: list[MarketPayload]) -> int:
    if redis_client is None:
        return 0
    ttl_seconds = runtime.settings.market_stats_ttl_seconds
    if ttl_seconds <= 0:
        return 0
    payloads: dict[str, dict[str, Any]] = {}
    for market in markets:
        event_id = getattr(market, "event_id", None)
        if not event_id:
            continue
        payloads[market_stats_cache_key(str(event_id))] = _build_market_stats_payload(market)
    if not payloads:
        return 0
    return await shared_cache.set_json_many(redis_client, payloads, ttl_seconds=ttl_seconds)


def _log_db_metrics(context: str) -> None:
    from shared.db_metrics import snapshot as snapshot_db_metrics

    metrics = snapshot_db_metrics()
    threshold = runtime.settings.db_query_warn_threshold
    max_ms = runtime.settings.db_query_time_warn_ms
    if metrics.query_count >= threshold or metrics.total_time_ms >= max_ms:
        log_event(
            logger,
            logging.WARNING,
            event="worker.db.query_budget.exceeded",
            message="database query budget exceeded",
            context=context,
            query_count=metrics.query_count,
            db_time_ms=round(metrics.total_time_ms, 2),
        )


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


async def _enqueue_backfill_proof_jobs(redis_client: Redis | None) -> int:
    """
    Enqueue proof jobs for finalized markets already in the database that may be
    skipped by the open-only Polymarket fetch.
    """

    if redis_client is None:
        return 0
    cursor_key = "reveal_market_worker:proof_backfill:last_market_id"
    last_id: int | None = None
    if redis_client is not None:
        try:
            raw = await redis_client.get(cursor_key)
            last_id = int(raw) if raw is not None else None
        except Exception as exc:  # pragma: no cover - best effort
            log_event(
                logger,
                logging.DEBUG,
                event="worker.proof.backfill_cursor_read_failed",
                message="failed to read backfill cursor",
                error=str(exc),
            )
            last_id = None
    try:
        async with session_scope() as session:
            stmt = (
                select(shared_models.Market, shared_models.Settlement)
                .where(
                    shared_models.Market.resolution_status == shared_models.ResolutionStatusEnum.FINAL.value,
                    shared_models.Settlement.market_id == shared_models.Market.id,
                    shared_models.Settlement.proof_status != shared_models.SettlementProofStatus.GENERATED.value,
                )
                .order_by(shared_models.Market.id.asc())
            )
            if last_id is not None:
                stmt = stmt.where(shared_models.Market.id > last_id)
            stmt = stmt.limit(max(runtime.settings.proof_backfill_page_size, 1))
            rows = list((await session.execute(stmt)).all())
            if not rows and last_id is not None:
                # Wrap around to the start when we reach the end of the table.
                stmt = (
                    select(shared_models.Market, shared_models.Settlement)
                    .where(
                        shared_models.Market.resolution_status == shared_models.ResolutionStatusEnum.FINAL.value,
                        shared_models.Settlement.market_id == shared_models.Market.id,
                        shared_models.Settlement.proof_status != shared_models.SettlementProofStatus.GENERATED.value,
                    )
                    .order_by(shared_models.Market.id.asc())
                    .limit(max(runtime.settings.proof_backfill_page_size, 1))
                )
                rows = list((await session.execute(stmt)).all())
    except Exception as exc:
        log_event(
            logger,
            logging.WARNING,
            event="worker.proof.backfill_query_failed",
            message="failed to query backfill candidates",
            error=str(exc),
        )
        return 0

    if not rows:
        return 0

    summary = SyncSummary()
    for market, settlement in rows:
        if settlement_needs_refresh(settlement):
            continue
        if (settlement.commitments_count or 0) <= 0:
            continue
        try:
            payload = market_record_to_payload(market)
            snapshot = snapshot_market_record(market)
        except Exception as exc:
            log_event(
                logger,
                logging.INFO,
                event="worker.proof.backfill_payload_failed",
                message="skipping backfill proof job due to snapshot/payload failure",
                market_id=getattr(market, "event_id", None),
                error=str(exc),
            )
            continue
        summary.proof_jobs.append((snapshot, payload, market.condition_id))

    if not summary.proof_jobs:
        return 0
    enqueued = await enqueue_proof_jobs(redis_client, summary)
    if enqueued and redis_client is not None:
        last_market_id = getattr(rows[-1][0], "id", None)
        if last_market_id is not None:
            try:
                await redis_client.set(cursor_key, str(last_market_id))
            except Exception as exc:  # pragma: no cover - best effort
                log_event(
                    logger,
                    logging.DEBUG,
                    event="worker.proof.backfill_cursor_write_failed",
                    message="failed to persist backfill cursor",
                    error=str(exc),
                )
    return enqueued


async def _recover_settlement_state(redis_client: Redis | None) -> int:
    """Recover settlement snapshots missing roots or winners after interruptions."""

    if redis_client is None:
        return 0
    recovery_gate_key = "reveal_market_worker:settlement_recovery:cooldown"
    try:
        gate = await redis_client.get(recovery_gate_key)
        if gate:
            return 0
    except Exception as exc:  # pragma: no cover - best effort
        log_event(
            logger,
            logging.DEBUG,
            event="worker.settlement.recovery_gate_read_failed",
            message="failed to read settlement recovery gate",
            error=str(exc),
        )
    min_interval = max(runtime.settings.settlement_recovery_min_interval_seconds, 0)
    if min_interval > 0:
        key = "reveal_market_worker:settlement_recovery:last"
        try:
            last_raw = await redis_client.get(key)
            last_ts = float(last_raw) if last_raw is not None else None
        except Exception:
            last_ts = None
        now = time.monotonic()
        if last_ts is not None and (now - last_ts) < min_interval:
            return 0
        try:
            await redis_client.set(key, str(now), ex=max(min_interval * 2, 60))
        except Exception as exc:
            log_event(
                logger,
                logging.DEBUG,
                event="worker.settlement.recovery_cache_failed",
                message="failed to cache settlement recovery timestamp",
                error=str(exc),
            )
    limit = max(runtime.settings.settlement_recovery_limit, 1)
    recovered = 0
    retry_prefix = "reveal_market_worker:settlement_recover:fail"
    try:
        async with session_scope() as session:
            stmt = (
                select(shared_models.Market, shared_models.Settlement)
                .join(shared_models.Settlement, shared_models.Settlement.market_id == shared_models.Market.id)
                .where(shared_models.Market.resolution_status == shared_models.ResolutionStatusEnum.FINAL.value)
                .where(
                    or_(
                        shared_models.Settlement.winning_outcome_id.is_(None),
                        shared_models.Settlement.merkle_root.is_(None),
                        shared_models.Settlement.merkle_root
                        == "0x0000000000000000000000000000000000000000000000000000000000000000",
                    )
                )
                .order_by(shared_models.Market.resolved_at.asc().nulls_last(), shared_models.Market.id.asc())
                .limit(limit)
            )
            rows = list((await session.execute(stmt)).all())
            if not rows:
                return 0
            for market, settlement in rows:
                retry_key = failure_key(retry_prefix, market.id)
                if not await should_attempt(redis_client, retry_key):
                    continue
                try:
                    if not market.market_address or not runtime.settings.rpc_url:
                        raise RuntimeError("missing_market_address_or_rpc")
                    refreshed = await _upsert_settlement_from_chain(session, market, force=True)
                    if refreshed is not None:
                        settlement = refreshed
                    if settlement.winning_outcome_id is None and market.condition_id:
                        resolution = await repository_async.get_resolution_by_condition_id(session, market.condition_id)
                        if resolution and resolution.winning_outcome_id is not None:
                            settlement.winning_outcome_id = int(resolution.winning_outcome_id)
                            session.add(settlement)
                    await session.flush()
                    if not settlement_needs_refresh(settlement):
                        await clear_failure(redis_client, retry_key)
                        recovered += 1
                except Exception as exc:
                    await record_failure(
                        redis_client,
                        retry_key,
                        base_seconds=runtime.settings.settlement_recovery_failure_base_seconds,
                        max_seconds=runtime.settings.settlement_recovery_failure_max_seconds,
                        max_attempts=runtime.settings.settlement_recovery_failure_max_attempts,
                        logger=logger,
                        event="worker.settlement.recover_retry",
                        message="settlement recovery retry scheduled after failure",
                        reason=str(exc),
                    )
                    try:
                        await redis_client.set(
                            recovery_gate_key,
                            "1",
                            ex=max(runtime.settings.settlement_recovery_failure_base_seconds, 30),
                        )
                    except Exception as gate_exc:  # pragma: no cover - best effort
                        log_event(
                            logger,
                            logging.DEBUG,
                            event="worker.settlement.recovery_gate_write_failed",
                            message="failed to set settlement recovery gate",
                            error=str(gate_exc),
                        )
            if recovered:
                summary = SyncSummary()
                for market, _settlement in rows:
                    if getattr(market, "event_id", None):
                        summary.changed_events.add(market.event_id)
                    if getattr(market, "condition_id", None):
                        summary.changed_conditions.add(market.condition_id.lower())
                await invalidate_cache_tags(redis_client, summary)
        if recovered:
            await enqueue_settlement_job(redis_client)
    except Exception as exc:
        try:
            await redis_client.set(
                recovery_gate_key,
                "1",
                ex=max(runtime.settings.settlement_recovery_failure_base_seconds, 30),
            )
        except Exception as gate_exc:  # pragma: no cover - best effort
            log_event(
                logger,
                logging.DEBUG,
                event="worker.settlement.recovery_gate_write_failed",
                message="failed to set settlement recovery gate",
                error=str(gate_exc),
            )
        log_event(
            logger,
            logging.WARNING,
            event="worker.settlement.recover_failed",
            message="settlement recovery failed",
            error=str(exc),
        )
        return 0
    return recovered


def _read_cgroup_value(path: str) -> int | None:
    try:
        with open(path) as handle:
            raw = handle.read().strip()
    except OSError:
        return None
    if not raw or raw == "max":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _memory_snapshot() -> MemoryStats:
    stats: MemoryStats = {}
    rss_kb = hwm_kb = vms_kb = data_kb = None
    cgroup_current = None
    cgroup_limit = None

    try:
        with open("/proc/self/status") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    rss_kb = _parse_kb_value(line)
                elif line.startswith("VmHWM:"):
                    hwm_kb = _parse_kb_value(line)
                elif line.startswith("VmSize:"):
                    vms_kb = _parse_kb_value(line)
                elif line.startswith("VmData:"):
                    data_kb = _parse_kb_value(line)
    except OSError:
        pass

    if rss_kb is not None:
        stats["mem_rss_mb"] = round(rss_kb / 1024, 2)
    if hwm_kb is not None:
        stats["mem_hwm_mb"] = round(hwm_kb / 1024, 2)
    if vms_kb is not None:
        stats["mem_vms_mb"] = round(vms_kb / 1024, 2)
    if data_kb is not None:
        stats["mem_data_mb"] = round(data_kb / 1024, 2)

    cgroup_current = _read_cgroup_value("/sys/fs/cgroup/memory.current")
    if cgroup_current is None:
        cgroup_current = _read_cgroup_value("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    cgroup_limit = _read_cgroup_value("/sys/fs/cgroup/memory.max")
    if cgroup_limit is None:
        cgroup_limit = _read_cgroup_value("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    if cgroup_current is not None:
        stats["mem_cgroup_current_mb"] = round(cgroup_current / 1024 / 1024, 2)
    if cgroup_limit is not None and cgroup_limit < (1 << 60):
        stats["mem_cgroup_limit_mb"] = round(cgroup_limit / 1024 / 1024, 2)

    gc_counts = gc.get_count()
    stats["gc_gen0"] = gc_counts[0]
    stats["gc_gen1"] = gc_counts[1]
    stats["gc_gen2"] = gc_counts[2]
    return stats


def _trim_worker_memory() -> bool:
    """Attempt to return freed memory back to the OS."""

    gc.collect()
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6")
        if hasattr(libc, "malloc_trim"):
            libc.malloc_trim(0)
            return True
    except Exception:
        return False
    return False


def _count_memory_pressure_objects() -> MemoryPressureStats:
    global _LAST_MEMORY_PRESSURE_SCAN_TS
    interval = max(runtime.settings.worker_memory_pressure_scan_interval_seconds, 0)
    if interval <= 0:
        return {
            "market_payload_objects": 0,
            "market_orm_objects": 0,
        }
    now = time.monotonic()
    if _LAST_MEMORY_PRESSURE_SCAN_TS is not None and (now - _LAST_MEMORY_PRESSURE_SCAN_TS) < interval:
        return {
            "market_payload_objects": 0,
            "market_orm_objects": 0,
        }
    _LAST_MEMORY_PRESSURE_SCAN_TS = now
    counts: MemoryPressureStats = {
        "market_payload_objects": 0,
        "market_orm_objects": 0,
    }
    for obj in gc.get_objects():
        if isinstance(obj, MarketPayload):
            counts["market_payload_objects"] += 1
        elif isinstance(obj, shared_models.Market):
            counts["market_orm_objects"] += 1
    return counts


def _parse_kb_value(line: str) -> int | None:
    parts = line.split()
    if len(parts) >= 2 and parts[1].isdigit():
        return int(parts[1])
    return None


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
        "proofs_generated": 0,
        "lock_batches_submitted": 0,
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

    global _LAST_SYNC_LEASE_FAILURE_TS
    cooldown = max(runtime.settings.polymarket_sync_lease_failure_cooldown_seconds, 0)
    cooldown_jitter = max(runtime.settings.polymarket_sync_lease_failure_jitter_seconds, 0)
    now = time.monotonic()
    if cooldown > 0 and _LAST_SYNC_LEASE_FAILURE_TS is not None:
        if (now - _LAST_SYNC_LEASE_FAILURE_TS) < cooldown:
            return False
    if redis_client is None:
        if cooldown > 0:
            _LAST_SYNC_LEASE_FAILURE_TS = now
        wait_for = cooldown + (random.uniform(0, cooldown_jitter) if cooldown_jitter else 0)  # noqa: S311
        if wait_for > 0:
            await asyncio.sleep(wait_for)
        return False
    lease_jitter = max(runtime.settings.polymarket_sync_lease_jitter_seconds, 0)
    ttl = max(runtime.settings.polymarket_sync_lease_ttl_seconds, 5)
    ttl_with_jitter = ttl + (random.uniform(0, lease_jitter) if lease_jitter else 0)  # noqa: S311
    try:
        acquired = await redis_client.set(
            runtime.settings.polymarket_sync_lease_key,
            str(time.time()),
            nx=True,
            ex=int(ttl_with_jitter),
        )
        if acquired:
            _LAST_SYNC_LEASE_FAILURE_TS = None
        else:
            _LAST_SYNC_LEASE_FAILURE_TS = now
        return bool(acquired)
    except Exception as exc:  # pragma: no cover - defensive
        _LAST_SYNC_LEASE_FAILURE_TS = now
        log_event(
            logger,
            logging.WARNING,
            event="worker.sync.lease_error",
            message="failed to acquire polymarket sync lease",
            error=str(exc),
        )
        return False


async def _release_sync_lease(redis_client: Redis | None) -> None:
    if redis_client is None:
        return
    try:
        await redis_client.delete(runtime.settings.polymarket_sync_lease_key)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="worker.sync.lease_release_failed",
            message="failed to release polymarket sync lease",
            error=str(exc),
        )


async def _acquire_maintenance_lease(redis_client: Redis | None) -> bool:
    """Best-effort lease so only one worker runs maintenance at a time."""

    if redis_client is None:
        return False
    ttl = max(int(runtime.settings.maintenance_poll_seconds), 5)
    try:
        acquired = await redis_client.set(
            runtime.settings.maintenance_lease_key,
            str(time.time()),
            nx=True,
            ex=ttl,
        )
        return bool(acquired)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="worker.maintenance.lease_error",
            message="failed to acquire maintenance lease",
            error=str(exc),
        )
        return False


async def _release_maintenance_lease(redis_client: Redis | None) -> None:
    if redis_client is None:
        return
    try:
        await redis_client.delete(runtime.settings.maintenance_lease_key)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="worker.maintenance.lease_release_failed",
            message="failed to release maintenance lease",
            error=str(exc),
        )


def _chunked(items: list[str], size: int) -> list[list[str]]:
    if size <= 0:
        return [items]
    return [items[i : i + size] for i in range(0, len(items), size)]


def _parse_timestamp(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_timestamp(value: datetime | None) -> float | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def _order_supports_updated_at_cutoff() -> bool:
    if not runtime.settings.polymarket_updated_at_cutoff_enabled:
        return False
    if runtime.settings.polymarket_sort_ascending:
        return False
    order = runtime.settings.polymarket_order or ""
    return str(order).lower() in {"updatedat", "updated_at"}


async def _get_polymarket_updated_at_cutoff(redis_client: Redis | None) -> float | None:
    if not _order_supports_updated_at_cutoff():
        return None
    last_ts: float | None = None
    if redis_client is not None:
        try:
            raw = await redis_client.get(runtime.settings.polymarket_updated_at_cutoff_key)
            last_ts = _parse_timestamp(raw)
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                logger,
                logging.DEBUG,
                event="worker.fetch.cutoff_read_failed",
                message="failed to read polymarket updatedAt cutoff timestamp",
                error=str(exc),
            )
            last_ts = None
    else:
        global _LAST_POLYMARKET_UPDATED_AT_TS
        last_ts = _LAST_POLYMARKET_UPDATED_AT_TS
    if last_ts is None:
        return None
    grace = max(runtime.settings.polymarket_updated_at_cutoff_grace_seconds, 0)
    return last_ts - grace if grace else last_ts


async def _record_polymarket_updated_at(redis_client: Redis | None, last_seen_ts: float | None) -> None:
    if last_seen_ts is None or not _order_supports_updated_at_cutoff():
        return
    if redis_client is not None:
        try:
            await redis_client.set(runtime.settings.polymarket_updated_at_cutoff_key, str(last_seen_ts))
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                logger,
                logging.DEBUG,
                event="worker.fetch.cutoff_write_failed",
                message="failed to write polymarket updatedAt cutoff timestamp",
                error=str(exc),
            )
            return
    else:
        global _LAST_POLYMARKET_UPDATED_AT_TS
        _LAST_POLYMARKET_UPDATED_AT_TS = last_seen_ts


def _page_updated_at_bounds(markets: list[MarketPayload]) -> tuple[float | None, float | None]:
    timestamps: list[float] = []
    for market in markets:
        ts = _to_timestamp(getattr(market, "source_updated_at", None))
        if ts is not None:
            timestamps.append(ts)
    if not timestamps:
        return None, None
    return min(timestamps), max(timestamps)


async def _should_run_closed_reconcile(redis_client: Redis | None) -> bool:
    if not runtime.settings.closed_markets_reconcile_enabled:
        return False
    interval = runtime.settings.closed_markets_reconcile_interval_seconds
    if interval <= 0:
        return False
    now = time.time()
    last_ts: float | None = None
    if redis_client is not None:
        try:
            last_raw = await redis_client.get(runtime.settings.closed_markets_reconcile_last_key)
            last_ts = _parse_timestamp(last_raw)
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                logger,
                logging.DEBUG,
                event="worker.maintenance.closed_reconcile.last_read_failed",
                message="failed to read closed reconcile timestamp",
                error=str(exc),
            )
    else:
        global _LAST_CLOSED_RECONCILE_TS
        last_ts = _LAST_CLOSED_RECONCILE_TS
    if last_ts is not None and now - last_ts < interval:
        return False
    return True


async def _mark_closed_reconcile_run(redis_client: Redis | None) -> None:
    now = str(time.time())
    if redis_client is not None:
        try:
            await redis_client.set(runtime.settings.closed_markets_reconcile_last_key, now)
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                logger,
                logging.DEBUG,
                event="worker.maintenance.closed_reconcile.last_write_failed",
                message="failed to write closed reconcile timestamp",
                error=str(exc),
            )
    else:
        global _LAST_CLOSED_RECONCILE_TS
        _LAST_CLOSED_RECONCILE_TS = float(now)


async def _list_closed_reconcile_event_ids(
    session, *, now: datetime, stale_cutoff: datetime | None, limit: int
) -> list[str]:
    commitment_subq = select(shared_models.Commitment.market_id).distinct().subquery()
    status_filter = or_(
        shared_models.Market.resolution_status.is_(None),
        shared_models.Market.resolution_status != shared_models.ResolutionStatusEnum.FINAL.value,
    )
    stale_clauses: list[ColumnElement[bool]] = [shared_models.Market.source_updated_at.is_(None)]
    if stale_cutoff is not None:
        stale_clauses.append(shared_models.Market.source_updated_at <= stale_cutoff)
    stale_filter = or_(
        and_(
            or_(shared_models.Market.closed.is_(False), shared_models.Market.closed.is_(None)),
            shared_models.Market.closes_at.is_not(None),
            shared_models.Market.closes_at <= now,
        ),
        *stale_clauses,
    )
    stmt = (
        select(shared_models.Market.event_id)
        .join(commitment_subq, commitment_subq.c.market_id == shared_models.Market.id)
        .where(status_filter)
        .where(stale_filter)
        .order_by(
            shared_models.Market.closes_at.asc().nulls_last(),
            shared_models.Market.source_updated_at.asc().nulls_last(),
        )
        .limit(limit)
    )
    result = await session.scalars(stmt)
    return [event_id for event_id in result if isinstance(event_id, str)]


async def _fetch_closed_reconcile_markets(
    event_ids: list[str],
    *,
    concurrency: int,
) -> tuple[list[MarketPayload], int, int]:
    if not event_ids:
        return [], 0, 0
    bounded_concurrency = max(1, min(concurrency, len(event_ids)))
    semaphore = asyncio.Semaphore(bounded_concurrency)

    async def _fetch_one(event_id: str) -> tuple[MarketPayload | None, bool]:
        async with semaphore:
            try:
                payload = await runtime.polymarket_client.fetch_market_by_id(event_id)
                return payload, False
            except Exception as exc:  # pragma: no cover - defensive
                log_event(
                    logger,
                    logging.WARNING,
                    event="worker.maintenance.closed_reconcile.fetch_failed",
                    message="failed to fetch market from Gamma",
                    event_id=event_id,
                    error=str(exc),
                )
                return None, True

    results = await asyncio.gather(*(_fetch_one(event_id) for event_id in event_ids))
    payloads = [payload for payload, _failed in results if payload is not None]
    failed = sum(1 for _payload, was_failed in results if was_failed)
    missing = sum(1 for payload, was_failed in results if payload is None and not was_failed)
    return payloads, failed, missing


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
        "proofs_generated": stats.get("proofs_generated"),
        "lock_batches_submitted": stats.get("lock_batches_submitted"),
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
    """Ingest paginated Polymarket data."""
    start = time.perf_counter()
    heartbeat_interval = max(runtime.settings.container_heartbeat_seconds, 10)
    last_heartbeat = time.monotonic()
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
    try:
        log_event(
            logger,
            logging.INFO,
            event="worker.fetch.begin",
            message="starting polymarket fetch",
            page_size=runtime.settings.polymarket_page_size,
        )
        attempts = max(1, runtime.settings.polymarket_sync_max_attempts)
        backoff = max(runtime.settings.polymarket_sync_retry_backoff_seconds, 0.0)
        backoff_max = max(runtime.settings.polymarket_sync_retry_backoff_max_seconds, 0.0)
        attempt = 0
        last_exc: Exception | None = None
        cutoff_ts = await _get_polymarket_updated_at_cutoff(redis_client)
        while attempt < attempts:
            attempt += 1
            last_exc = None
            page_no = 0
            summary = SyncSummary()
            total_fetched = 0
            gap_count = 0
            stop_reason: str | None = None
            last_seen_ts: float | None = None
            try:
                only_open = runtime.settings.polymarket_only_open_markets is True
                closed_param = False if only_open else None
                commit_batch_size = max(runtime.settings.polymarket_commit_batch_size, 0)
                commit_pending = 0

                async def _flush_sync_batch(summary: SyncSummary) -> None:
                    if not (
                        summary.changed_events
                        or summary.changed_conditions
                        or summary.changed_categories
                        or summary.changed_group_slugs
                        or summary.resolution_cache_updates
                        or summary.proof_jobs
                    ):
                        return

                    summary.changed_events_total += len(summary.changed_events)
                    summary.changed_conditions_total += len(summary.changed_conditions)
                    summary.changed_categories_total += len(summary.changed_categories)
                    summary.changed_group_slugs_total += len(summary.changed_group_slugs)

                    if redis_client is not None:
                        cache_report = await invalidate_cache_tags(redis_client, summary)
                        summary.cache_invalidations += cache_report.total
                        await persist_resolution_cache_updates(redis_client, summary)
                        await enqueue_proof_jobs(redis_client, summary)
                        summary.proof_jobs = []
                    else:
                        await persist_resolution_cache_updates(redis_client, summary)

                    summary.changed_events = set()
                    summary.changed_conditions = set()
                    summary.changed_categories = set()
                    summary.changed_group_slugs = set()
                    summary.resolution_cache_updates = []

                stop_due_to_memory = False
                fetcher = (
                    runtime.polymarket_client.fetch_events_paginated
                    if runtime.settings.polymarket_use_events_endpoint
                    else runtime.polymarket_client.fetch_markets_paginated
                )
                async with session_scope() as session:
                    async for page in fetcher(
                        page_size=runtime.settings.polymarket_page_size,
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
                        page_min_ts, page_max_ts = _page_updated_at_bounds(page)
                        if page_max_ts is not None:
                            last_seen_ts = max(last_seen_ts or page_max_ts, page_max_ts)
                        cutoff_hit = cutoff_ts is not None and page_min_ts is not None and page_min_ts < cutoff_ts
                        stats_written = 0
                        if redis_client is not None:
                            stats_written = await _persist_market_stats(redis_client, page)
                        process_start = time.perf_counter()
                        timing_before = (
                            summary.timing_match_ms,
                            summary.timing_upsert_ms,
                            summary.timing_normalized_ms,
                            summary.timing_resolution_ms,
                        )
                        summary = await collect_market_changes_with_summary(
                            session, page, redis_client, summary=summary
                        )
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
                        commit_pending += filtered_count
                        commit_ms = 0.0
                        committed = False
                        pending_markets = commit_pending
                        if commit_batch_size == 0 or commit_pending >= commit_batch_size:
                            commit_start = time.perf_counter()
                            await session.commit()
                            commit_ms = (time.perf_counter() - commit_start) * 1000
                            committed = True
                            commit_pending = 0
                            await _flush_sync_batch(summary)
                        expunge_start = time.perf_counter()
                        session.expunge_all()  # keep identity map small between pages
                        expunge_ms = (time.perf_counter() - expunge_start) * 1000
                        page_duration_ms = (time.perf_counter() - page_start) * 1000
                        memory_stats: MemoryStats = {}
                        trim_threshold = runtime.settings.worker_memory_trim_threshold_mb
                        abort_threshold = runtime.settings.worker_memory_abort_threshold_mb
                        if runtime.settings.worker_memory_log_enabled or trim_threshold > 0 or abort_threshold > 0:
                            log_every = runtime.settings.worker_memory_log_every_n_pages
                            if committed or page_no % log_every == 0 or trim_threshold > 0 or abort_threshold > 0:
                                memory_stats = _memory_snapshot()
                                rss = memory_stats.get("mem_rss_mb")
                                if trim_threshold > 0 and isinstance(rss, (int, float)) and rss >= trim_threshold:
                                    trimmed = _trim_worker_memory()
                                    memory_stats["mem_trimmed"] = trimmed
                                    if trimmed:
                                        post_trim = _memory_snapshot()
                                        memory_stats["mem_rss_mb_post_trim"] = post_trim.get("mem_rss_mb", rss)
                                        memory_stats["mem_hwm_mb_post_trim"] = post_trim.get("mem_hwm_mb")
                                if abort_threshold > 0:
                                    rss_now = memory_stats.get("mem_rss_mb_post_trim", memory_stats.get("mem_rss_mb"))
                                    cgroup_now = memory_stats.get("mem_cgroup_current_mb")
                                    mem_now = cgroup_now if isinstance(cgroup_now, (int, float)) else rss_now
                                    if isinstance(mem_now, (int, float)) and mem_now >= abort_threshold:
                                        log_event(
                                            logger,
                                            logging.WARNING,
                                            event="worker.sync.memory_pressure",
                                            message="ending sync tick early due to memory pressure",
                                            page=page_no,
                                            total=total_fetched,
                                            mem_rss_mb=rss_now,
                                            mem_cgroup_mb=cgroup_now,
                                            mem_threshold_mb=abort_threshold,
                                            changed_events=len(summary.changed_events),
                                            changed_conditions=len(summary.changed_conditions),
                                            proof_jobs=len(summary.proof_jobs),
                                            **_count_memory_pressure_objects(),
                                        )
                                        stop_due_to_memory = True
                                        stop_reason = "memory"
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
                            commit_pending=pending_markets,
                            commit_batch_size=commit_batch_size,
                            committed=committed,
                            market_stats_written=stats_written or None,
                            **memory_stats,
                        )
                        if cutoff_hit and stop_reason is None:
                            stop_reason = "updated_at_cutoff"
                            log_event(
                                logger,
                                logging.INFO,
                                event="worker.fetch.cutoff_hit",
                                message="stopping pagination at updatedAt cutoff",
                                page=page_no,
                                total=total_fetched,
                                cutoff_ts=cutoff_ts,
                                page_min_ts=page_min_ts,
                                page_max_ts=page_max_ts,
                            )
                        if stop_due_to_memory:
                            break
                        if stop_reason == "updated_at_cutoff":
                            break
                        if redis_client is not None:
                            now = time.monotonic()
                            if now - last_heartbeat >= heartbeat_interval:
                                interim_latency_ms = (time.perf_counter() - start) * 1000
                                interim_stats = summary.to_stats(total_fetched, interim_latency_ms, 0)
                                interim_stats["polymarket_ok"] = True
                                await publish_heartbeat(redis_client, interim_stats)
                                last_heartbeat = now
                    if commit_pending > 0:
                        commit_start = time.perf_counter()
                        await session.commit()
                        commit_ms = (time.perf_counter() - commit_start) * 1000
                        commit_memory_stats: MemoryStats = {}
                        trim_threshold = runtime.settings.worker_memory_trim_threshold_mb
                        if runtime.settings.worker_memory_log_enabled or trim_threshold > 0:
                            commit_memory_stats = _memory_snapshot()
                            rss = commit_memory_stats.get("mem_rss_mb")
                            if trim_threshold > 0 and isinstance(rss, (int, float)) and rss >= trim_threshold:
                                trimmed = _trim_worker_memory()
                                commit_memory_stats["mem_trimmed"] = trimmed
                                if trimmed:
                                    post_trim = _memory_snapshot()
                                    commit_memory_stats["mem_rss_mb_post_trim"] = post_trim.get("mem_rss_mb", rss)
                                    commit_memory_stats["mem_hwm_mb_post_trim"] = post_trim.get("mem_hwm_mb")
                        log_event(
                            logger,
                            logging.INFO,
                            event="worker.sync.commit",
                            message="committed remaining polymarket batch",
                            commit_pending=commit_pending,
                            commit_ms=round(commit_ms, 2),
                            commit_batch_size=commit_batch_size,
                            **commit_memory_stats,
                        )
                        commit_pending = 0
                    await _flush_sync_batch(summary)
                    if stop_due_to_memory:
                        break
                if stop_reason != "memory":
                    await _record_polymarket_updated_at(redis_client, last_seen_ts)
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
    finally:
        await _release_sync_lease(redis_client)


async def process_once(redis_client: Redis | None = None) -> dict[str, float | int | str | bool]:
    """Fetch markets, persist them, and emit a heartbeat once."""

    from shared.db_metrics import reset_metrics as reset_db_metrics

    reset_db_metrics()
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
    if runtime.circuit_breaker is None or getattr(runtime.circuit_breaker, "_redis", None) is None:
        runtime.circuit_breaker = CircuitBreaker(
            redis_client,
            CircuitBreakerConfig(
                key_prefix="reveal_market_worker:circuit",
                failure_threshold=runtime.settings.circuit_failure_threshold,
                window_seconds=runtime.settings.circuit_window_seconds,
                cooldown_seconds=runtime.settings.circuit_cooldown_seconds,
            ),
            logger,
        )
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
        # Backfill proof jobs for finalized markets that are no longer fetched (e.g., when only-open filter is on).
        try:
            backfill_enqueued = await _enqueue_backfill_proof_jobs(redis_client)
            if backfill_enqueued:
                log_event(
                    logger,
                    logging.INFO,
                    event="worker.proof.jobs_backfilled",
                    message="enqueued backfill proof jobs for finalized markets",
                    enqueued=backfill_enqueued,
                )
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                logger,
                logging.WARNING,
                event="worker.proof.backfill_failed",
                message="failed to enqueue backfill proof jobs",
                error=str(exc),
            )
    else:
        asyncio.create_task(_run_proofs_and_settlements(summary))
    summary.proofs_generated = 0
    summary.settlement_txs = 0
    cache_report = await invalidate_cache_tags(redis_client, summary)
    summary.cache_invalidations += cache_report.total
    stats = summary.to_stats(total_fetched, latency_ms, summary.cache_invalidations)
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
        resolutions=summary.changed_conditions_total + len(summary.changed_conditions),
        resolutions_backfilled=summary.resolutions_backfilled,
        proofs=summary.proofs_generated,
        lock_batches=summary.lock_batches_submitted,
        gamma_metadata_updates=summary.gamma_metadata_updates,
        latency_ms=round(latency_ms, 2),
        cache_invalidations=summary.cache_invalidations,
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
    _log_db_metrics("process_once")
    await propagate_schema_revision(redis_client, schema_state)
    await persist_resolution_cache_updates(redis_client, summary)
    return stats


async def _reconcile_closed_markets(session, redis_client: Redis | None) -> dict[str, int | str]:
    if not await _should_run_closed_reconcile(redis_client):
        return {
            "status": "skipped",
            "candidates": 0,
            "processed": 0,
            "missing": 0,
            "failed": 0,
        }

    max_markets = max(runtime.settings.closed_markets_reconcile_max_markets, 0)
    if max_markets <= 0:
        return {
            "status": "disabled",
            "candidates": 0,
            "processed": 0,
            "missing": 0,
            "failed": 0,
        }

    now = datetime.now(UTC)
    stale_seconds = max(runtime.settings.closed_markets_reconcile_stale_seconds, 0)
    stale_cutoff = now - timedelta(seconds=stale_seconds) if stale_seconds > 0 else None

    candidates = await _list_closed_reconcile_event_ids(
        session,
        now=now,
        stale_cutoff=stale_cutoff,
        limit=max_markets,
    )
    if not candidates:
        await _mark_closed_reconcile_run(redis_client)
        log_event(
            logger,
            logging.DEBUG,
            event="worker.maintenance.closed_reconcile.empty",
            message="no closed-market reconcile candidates",
            max_markets=max_markets,
        )
        return {
            "status": "empty",
            "candidates": 0,
            "processed": 0,
            "missing": 0,
            "failed": 0,
        }

    log_event(
        logger,
        logging.INFO,
        event="worker.maintenance.closed_reconcile.start",
        message="starting closed-market reconcile",
        candidates=len(candidates),
        max_markets=max_markets,
        batch_size=runtime.settings.closed_markets_reconcile_batch_size,
        fetch_concurrency=runtime.settings.closed_markets_reconcile_fetch_concurrency,
        stale_seconds=stale_seconds,
    )

    summary = SyncSummary()
    processed = 0
    failed = 0
    missing = 0
    proofs_enqueued = 0
    batch_size = max(runtime.settings.closed_markets_reconcile_batch_size, 1)
    concurrency = max(runtime.settings.closed_markets_reconcile_fetch_concurrency, 1)

    async def _flush_reconcile_summary(summary_obj: SyncSummary) -> None:
        nonlocal proofs_enqueued
        if not (
            summary_obj.changed_events
            or summary_obj.changed_conditions
            or summary_obj.changed_categories
            or summary_obj.changed_group_slugs
            or summary_obj.resolution_cache_updates
            or summary_obj.proof_jobs
        ):
            return

        summary_obj.changed_events_total += len(summary_obj.changed_events)
        summary_obj.changed_conditions_total += len(summary_obj.changed_conditions)
        summary_obj.changed_categories_total += len(summary_obj.changed_categories)
        summary_obj.changed_group_slugs_total += len(summary_obj.changed_group_slugs)

        if redis_client is not None:
            cache_report = await invalidate_cache_tags(redis_client, summary_obj)
            summary_obj.cache_invalidations += cache_report.total
            await persist_resolution_cache_updates(redis_client, summary_obj)
            proofs_enqueued += len(summary_obj.proof_jobs)
            await enqueue_proof_jobs(redis_client, summary_obj)
            summary_obj.proof_jobs = []
        else:
            await persist_resolution_cache_updates(redis_client, summary_obj)
            summary_obj.proof_jobs = []

        summary_obj.changed_events = set()
        summary_obj.changed_conditions = set()
        summary_obj.changed_categories = set()
        summary_obj.changed_group_slugs = set()
        summary_obj.resolution_cache_updates = []

    for batch_index, batch in enumerate(_chunked(candidates, batch_size), start=1):
        fetch_start = time.perf_counter()
        payloads, batch_failed, batch_missing = await _fetch_closed_reconcile_markets(
            batch,
            concurrency=concurrency,
        )
        fetch_ms = (time.perf_counter() - fetch_start) * 1000
        failed += batch_failed
        missing += batch_missing
        if not payloads:
            log_event(
                logger,
                logging.DEBUG,
                event="worker.maintenance.closed_reconcile.batch_empty",
                message="closed-market reconcile batch contained no payloads",
                batch=batch_index,
                requested=len(batch),
                fetch_ms=round(fetch_ms, 2),
                failed=batch_failed,
                missing=batch_missing,
            )
            continue
        process_start = time.perf_counter()
        summary = await collect_market_changes_with_summary(session, payloads, redis_client, summary=summary)
        await session.flush()
        commit_start = time.perf_counter()
        await session.commit()
        commit_ms = (time.perf_counter() - commit_start) * 1000
        processed += len(payloads)
        await _flush_reconcile_summary(summary)
        session.expunge_all()
        batch_ms = (time.perf_counter() - process_start) * 1000
        log_event(
            logger,
            logging.DEBUG,
            event="worker.maintenance.closed_reconcile.batch_complete",
            message="closed-market reconcile batch complete",
            batch=batch_index,
            requested=len(batch),
            fetched=len(payloads),
            fetch_ms=round(fetch_ms, 2),
            batch_ms=round(batch_ms, 2),
            commit_ms=round(commit_ms, 2),
            failed=batch_failed,
            missing=batch_missing,
        )

    await _flush_reconcile_summary(summary)
    await _mark_closed_reconcile_run(redis_client)
    log_event(
        logger,
        logging.INFO,
        event="worker.maintenance.closed_reconcile.complete",
        message="closed-market reconcile complete",
        candidates=len(candidates),
        processed=processed,
        missing=missing,
        failed=failed,
        cache_invalidations=summary.cache_invalidations,
        proofs_enqueued=proofs_enqueued,
    )
    return {
        "status": "complete",
        "candidates": len(candidates),
        "processed": processed,
        "missing": missing,
        "failed": failed,
    }


async def run_maintenance_loop(redis_client: Redis | None) -> None:
    """Run retention/backfill maintenance on a fixed cadence."""

    interval = runtime.settings.maintenance_poll_seconds
    if interval <= 0:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.maintenance.loop_disabled",
            message="maintenance loop disabled (poll interval <= 0)",
        )
        return

    log_event(
        logger,
        logging.INFO,
        event="worker.maintenance.loop_start",
        message="starting maintenance loop",
        poll_seconds=interval,
        lease_key=runtime.settings.maintenance_lease_key,
    )
    try:
        while True:
            loop_start = time.monotonic()
            lease_acquired = await _acquire_maintenance_lease(redis_client)
            if not lease_acquired:
                log_event(
                    logger,
                    logging.INFO,
                    event="worker.maintenance.skipped_lease",
                    message="skipping maintenance tick because another worker holds the lease",
                    lease_key=runtime.settings.maintenance_lease_key,
                )
            else:
                summary = SyncSummary()
                gap_count = 0
                address_updates = 0
                params_updates = 0
                backfilled = 0
                reconcile_report: dict[str, int | str] = {
                    "status": "skipped",
                    "candidates": 0,
                    "processed": 0,
                    "missing": 0,
                    "failed": 0,
                }
                try:
                    async with session_scope() as session:
                        await apply_retention_cleanup_async(session, summary)
                        if summary.markets_deleted:
                            log_event(
                                logger,
                                logging.INFO,
                                event="worker.maintenance.retention_complete",
                                message="retention cleanup finished",
                                retention_deleted=summary.markets_deleted,
                            )
                        try:
                            reconcile_report = await _reconcile_closed_markets(session, redis_client)
                        except Exception as exc:  # pragma: no cover - defensive
                            log_event(
                                logger,
                                logging.WARNING,
                                event="worker.maintenance.closed_reconcile.failed",
                                message="closed-market reconcile failed",
                                error=str(exc),
                            )
                        backfilled = await backfill_missing_resolutions_async(session, summary)
                        if backfilled:
                            log_event(
                                logger,
                                logging.INFO,
                                event="worker.resolution.backfill_complete",
                                message="backfilled missing resolution snapshots",
                                count=backfilled,
                            )
                        if runtime.settings.factory_address and runtime.settings.rpc_url:
                            factory_limit = max(runtime.settings.factory_backfill_limit, 0)
                            if factory_limit > 0:
                                address_updates = await backfill_market_addresses(
                                    session,
                                    rpc_url=str(runtime.settings.rpc_url),
                                    factory_address=str(runtime.settings.factory_address),
                                    get_markets_missing_address=repository_async.list_markets_missing_address,
                                    limit=factory_limit,
                                )
                                if address_updates:
                                    log_event(
                                        logger,
                                        logging.INFO,
                                        event="worker.resolution.backfill_addresses",
                                        message="backfilled market addresses",
                                        count=address_updates,
                                    )
                                params_updates = await backfill_market_params(
                                    session,
                                    rpc_url=str(runtime.settings.rpc_url),
                                    factory_address=str(runtime.settings.factory_address),
                                    get_markets_for_sync=repository_async.list_markets_for_factory_sync,
                                    limit=factory_limit,
                                )
                                if params_updates:
                                    log_event(
                                        logger,
                                        logging.INFO,
                                        event="worker.market_params.backfill",
                                        message="backfilled market factory params",
                                        count=params_updates,
                                    )
                        gap_count = await log_resolution_gaps_async(session)
                    cache_report = await invalidate_cache_tags(redis_client, summary)
                    summary.cache_invalidations = cache_report.total
                    await persist_resolution_cache_updates(redis_client, summary)
                    log_event(
                        logger,
                        logging.INFO,
                        event="worker.maintenance.complete",
                        message="maintenance tick complete",
                        retention_deleted=summary.markets_deleted,
                        resolutions_backfilled=backfilled,
                        resolution_gaps=gap_count,
                        address_updates=address_updates,
                        params_updates=params_updates,
                        closed_reconcile_status=reconcile_report.get("status"),
                        closed_reconcile_candidates=reconcile_report.get("candidates"),
                        closed_reconcile_processed=reconcile_report.get("processed"),
                        closed_reconcile_missing=reconcile_report.get("missing"),
                        closed_reconcile_failed=reconcile_report.get("failed"),
                        cache_invalidations=cache_report.total,
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    log_event(
                        logger,
                        logging.WARNING,
                        event="worker.maintenance.failed",
                        message="maintenance tick failed",
                        error=str(exc),
                    )
                finally:
                    await _release_maintenance_lease(redis_client)
            if redis_client is not None:
                try:
                    recovered = await _recover_settlement_state(redis_client)
                    if recovered:
                        log_event(
                            logger,
                            logging.INFO,
                            event="worker.settlement.recovered",
                            message="recovered settlement snapshots",
                            recovered=recovered,
                        )
                except Exception as exc:  # pragma: no cover - defensive
                    log_event(
                        logger,
                        logging.WARNING,
                        event="worker.settlement.recover_failed",
                        message="settlement recovery run failed",
                        error=str(exc),
                    )
            elapsed = time.monotonic() - loop_start
            sleep_for = max(interval - elapsed, 0)
            await asyncio.sleep(sleep_for)
    except asyncio.CancelledError:  # pragma: no cover - shutdown path
        return


async def run_lock_batches_loop(redis_client: Redis | None) -> None:
    """Continuously attempt lock-batches on a fixed cadence independent of Gamma sync."""

    interval = runtime.settings.lock_batches_poll_seconds
    if interval <= 0:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.lock_batches.loop_disabled",
            message="lock-batches loop disabled (poll interval <= 0)",
        )
        return

    log_event(
        logger,
        logging.INFO,
        event="worker.lock_batches.loop_start",
        message="starting lock-batches loop",
        poll_seconds=interval,
    )
    try:
        while True:
            loop_start = time.monotonic()
            summary = SyncSummary()
            try:
                submitted = await run_lock_batches_jobs(summary, redis_client)
                cache_invalidations = 0
                if submitted and redis_client is not None:
                    cache_report = await invalidate_cache_tags(redis_client, summary)
                    cache_invalidations = cache_report.total
                if submitted:
                    log_event(
                        logger,
                        logging.INFO,
                        event="worker.lock_batches.loop_complete",
                        message="lock-batches loop processed candidates",
                        submitted=submitted,
                        cache_invalidations=cache_invalidations,
                    )
            except Exception as exc:  # pragma: no cover - defensive
                log_event(
                    logger,
                    logging.WARNING,
                    event="worker.lock_batches.loop_failed",
                    message="lock-batches loop failed",
                    error=str(exc),
                )
            elapsed = time.monotonic() - loop_start
            sleep_for = max(interval - elapsed, 0)
            await asyncio.sleep(sleep_for)
    except asyncio.CancelledError:  # pragma: no cover - shutdown path
        return


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
    lock_batches_task: asyncio.Task | None = None
    maintenance_task: asyncio.Task | None = None
    if redis_client is not None:
        proof_worker_task = asyncio.create_task(run_proof_queue_worker(redis_client))
        settlement_worker_task = asyncio.create_task(run_settlement_queue_worker(redis_client))
    maintenance_task = asyncio.create_task(run_maintenance_loop(redis_client))
    lock_batches_task = asyncio.create_task(run_lock_batches_loop(redis_client))
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
        if maintenance_task is not None:
            maintenance_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await maintenance_task
        if lock_batches_task is not None:
            lock_batches_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await lock_batches_task
        if proof_worker_task is not None:
            proof_worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await proof_worker_task
        if settlement_worker_task is not None:
            settlement_worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await settlement_worker_task
