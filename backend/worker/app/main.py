"""Worker entrypoint that periodically syncs markets from Polymarket into the local database."""

from __future__ import annotations

import json
import logging
import re
import signal
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote_plus

import httpx
from py_clob_client.client import ClobClient
from redis import Redis
from shared import cache as shared_cache
from shared import models as shared_models
from shared import repository as shared_repository
from shared.cache_keys import (
    markets_list_cache_key,
    proof_receipt_cache_key,
    resolution_cache_key,
    suggest_cache_key,
)
from shared.indexers import GoldskyClient
from shared.logging import log_event, start_heartbeat_logger
from shared.migrations import get_current_revision
from shared.migrations import run_migrations as apply_migrations
from shared.models import MarketStatusEnum
from shared.onchain import ConditionalTokensClient
from shared.onchain.conditional_tokens import _derive_winners
from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings, reload_settings
from .logging_config import setup_logging
from .polymarket import MarketPayload, PolymarketClient, merge_clob_markets
from .proof_builder import SettlementDataMissingError, build_prover_payload
from .prover_client import ProverClient, ProverError
from .summary_jobs import maybe_enqueue_summary_job

try:
    from prometheus_client import REGISTRY, CollectorRegistry, Counter
except ImportError:  # pragma: no cover - optional dependency

    class Counter:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def labels(self, **kwargs):
            return self

        @staticmethod
        def inc(amount: float = 1.0) -> None:
            return None

    class CollectorRegistry:  # type: ignore[override]
        pass

    REGISTRY = None  # type: ignore[assignment]


def _safe_counter(name: str, documentation: str, labelnames: list[str]) -> Counter:
    """Register a Counter while tolerating duplicate registrations in test processes."""

    registry = REGISTRY
    try:
        return Counter(name, documentation, labelnames, registry=registry)
    except ValueError:
        existing = getattr(registry, "_names_to_collectors", {}).get(name) if registry else None
        if isinstance(existing, Counter):
            return existing
        return Counter(name, documentation, labelnames, registry=CollectorRegistry())


RETENTION_METRIC = _safe_counter(
    "worker_retention_candidates_total",
    "Markets considered by the retention reporter",
    ["category"],
)

CACHE_INVALIDATION_COUNTER = _safe_counter(
    "worker_cache_invalidations_total",
    "Number of cache invalidations triggered by the worker",
    ["type"],
)

POLYMARKET_FETCH_COUNTER = _safe_counter(
    "worker_polymarket_fetch_total",
    "Outcome of Polymarket fetch attempts",
    ["outcome"],
)

POLYMARKET_RETRY_COUNTER = _safe_counter(
    "worker_polymarket_retry_total",
    "Retry outcomes for individual Polymarket HTTP requests",
    ["outcome"],
)

POLYMARKET_RATE_LIMIT_COUNTER = _safe_counter(
    "worker_polymarket_rate_limit_total",
    "Rate limit encounters when fetching Polymarket markets",
    ["outcome"],
)

POLYMARKET_EMPTY_PAGE_COUNTER = _safe_counter(
    "worker_polymarket_empty_pages_total",
    "Empty page responses during Polymarket pagination",
    ["outcome"],
)

setup_logging("reveal_market.worker")
logger = logging.getLogger("reveal_market.worker")

settings = get_settings()
_sanitized_config = {
    k: v
    for k, v in settings.model_dump().items()
    if not any(secret in k for secret in ["key", "private", "secret", "password"])
}
logger.info("service configuration", extra={"event": "service.config", "config": _sanitized_config})
PROVER_CLIENT: ProverClient | None = None


_schema_checked = False


@dataclass
class SchemaSyncResult:
    changed: bool = False
    previous_revision: str | None = None
    current_revision: str | None = None


@dataclass
class SyncOutcome:
    market_changed: bool
    resolution_changed: bool
    category_slug: str | None
    condition_id: str | None
    resolution_cache_payload: dict[str, Any] | None
    market_created: bool = False
    market_updated: bool = False


@dataclass
class ResolutionOutcome:
    changed: bool = False
    condition_id: str | None = None
    cache_payload: dict[str, Any] | None = None


@dataclass
class CleanupOutcome:
    events: set[str]
    conditions: set[str]
    categories: set[str]
    deleted_rows: int = 0
    eligible_rows: int = 0
    dry_run: bool = False
    category_counts: dict[str, int] | None = None


@dataclass
class SyncSummary:
    changed_events: set[str] = field(default_factory=set)
    changed_conditions: set[str] = field(default_factory=set)
    changed_categories: set[str] = field(default_factory=set)
    resolution_cache_updates: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    proof_jobs: list[tuple[dict[str, Any], MarketPayload, str | None]] = field(default_factory=list)
    stats_dirty: bool = False
    markets_created: int = 0
    markets_updated: int = 0
    markets_deleted: int = 0
    summaries_enqueued: int = 0
    proofs_generated: int = 0
    resolutions_backfilled: int = 0

    def to_stats(self, markets_processed: int, latency_ms: float, cache_invalidations: int) -> dict[str, Any]:
        return {
            "markets_processed": markets_processed,
            "markets_changed": len(self.changed_events),
            "resolutions_changed": len(self.changed_conditions),
            "categories_changed": len(self.changed_categories),
            "latency_ms": round(latency_ms, 2),
            "markets_created": self.markets_created,
            "markets_updated": self.markets_updated,
            "markets_deleted": self.markets_deleted,
            "summaries_enqueued": self.summaries_enqueued,
            "proofs_generated": self.proofs_generated,
            "cache_invalidations": cache_invalidations,
            "resolutions_backfilled": self.resolutions_backfilled,
        }


@dataclass
class CacheInvalidationReport:
    tag_counts: dict[str, int] = field(default_factory=dict)

    def record(self, tag: str, removed: int) -> None:
        if removed <= 0:
            return
        self.tag_counts[tag] = self.tag_counts.get(tag, 0) + removed

    @property
    def total(self) -> int:
        return sum(self.tag_counts.values())

    def log(self) -> None:
        if not self.tag_counts:
            return
        log_event(
            logger,
            logging.DEBUG,
            event="worker.cache.invalidate",
            message="invalidated worker cache tags",
            tags=list(self.tag_counts.keys()),
            total_removed=self.total,
        )


# Engine/session are module-level singletons so the worker loop can reuse
# connections without recreating pools on every tick.
engine = create_engine(
    settings.database_url,
    future=True,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of DB operations."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:  # pragma: no cover - defensive
        session.rollback()
        raise
    finally:
        session.close()


def _snapshot_market_record(record) -> dict[str, Any]:
    return {
        "event_id": getattr(record, "event_id", None),
        "market_address": getattr(record, "market_address", None),
        "condition_id": getattr(record, "condition_id", None),
    }


def _persist_settlement_snapshot(session: Session, market_id: int, snapshot: dict[str, Any]) -> None:
    """Write settlement + commitment data to the ledger tables for durability."""

    def _as_int(value: Any) -> int | None:
        try:
            return int(value)
        except Exception:
            return None

    settlement_fields = {
        "merkle_root": snapshot.get("merkleRoot") or snapshot.get("commitments_root"),
        "commitments_count": _as_int(snapshot.get("commitmentsCount") or snapshot.get("commitments_count")),
        "pool_total_yes": _as_int(snapshot.get("poolTotalYes") or (snapshot.get("poolTotals") or [None, None])[0]),
        "pool_total_no": _as_int(snapshot.get("poolTotalNo") or (snapshot.get("poolTotals") or [None, None])[-1]),
        "total_escrow": _as_int(snapshot.get("totalEscrow") or snapshot.get("total_escrow")),
        "total_liability": _as_int(snapshot.get("totalLiability") or snapshot.get("total_liability")),
        "rake_bps": _as_int(snapshot.get("rakeBps") or snapshot.get("rake_bps")),
        "winning_outcome_id": _as_int(snapshot.get("winningOutcomeId") or snapshot.get("winning_outcome_id")),
        "circuit_hash": snapshot.get("circuitHash") or snapshot.get("circuit_hash"),
    }
    settlement_payload = {k: v for k, v in settlement_fields.items() if v not in (None, "")}
    if settlement_payload:
        shared_repository.upsert_settlement_snapshot(session, market_id, settlement_payload)

    tickets = snapshot.get("tickets") or []
    if tickets:
        try:
            shared_repository.record_commitments(session, market_id, tickets)
        except Exception as exc:  # pragma: no cover - durability best-effort
            log_event(
                logger,
                logging.WARNING,
                event="worker.commitment.persist_failed",
                message="failed to persist commitments snapshot",
                market_id=market_id,
                error=str(exc),
            )


def _record_factory_state(session: Session, market: shared_models.Market | None, payload: MarketPayload) -> None:
    """Mirror factory/rake events into the ledger so address drift is auditable."""

    factory_address = payload.factory or getattr(market, "factory", None) or settings.factory_address
    if not factory_address:
        return
    market_address = payload.market_address or getattr(market, "market_address", None)
    event_payload = {
        "rake_bps": payload.rake_bps if hasattr(payload, "rake_bps") else None,
        "oracle": payload.oracle,
        "event_id": payload.event_id,
    }
    shared_repository.record_factory_event(
        session,
        factory_address=str(factory_address),
        market_address=str(market_address) if market_address else None,
        event="sync",
        tx_hash=None,
        block_number=None,
        block_timestamp=None,
        payload=event_payload,
    )


def _run_with_retries[T](
    action: Callable[[], T],
    max_attempts: int,
    base_backoff: float,
    max_backoff: float | None = None,
    on_retry: Callable[[int, BaseException | None], None] | None = None,
) -> T:
    """Execute an action with optional retry semantics using tenacity."""

    if max_attempts <= 1:
        return action()

    try:
        from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential
    except ModuleNotFoundError:  # pragma: no cover - tenacity optional
        return action()

    base_delay = base_backoff if base_backoff > 0 else 0.1
    wait_kwargs = {"multiplier": base_delay, "min": base_delay}
    if max_backoff is not None and max_backoff > 0:
        wait_kwargs["max"] = max_backoff

    def _before_sleep(retry_state):
        if on_retry is None:
            return
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        try:
            on_retry(retry_state.attempt_number, exc)
        except Exception:  # pragma: no cover - logging must not break retries
            logger.debug(
                "retry callback raised",
                extra={"attempt": retry_state.attempt_number, "error": str(exc) if exc else None},
            )

    retryer = Retrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(**wait_kwargs),
        retry=retry_if_exception_type(Exception),
        before_sleep=_before_sleep,
        reraise=True,
    )
    return retryer(action)


def _ensure_schema() -> SchemaSyncResult:
    """Apply database migrations once per worker lifecycle if configured."""

    global _schema_checked
    result = SchemaSyncResult()
    if _schema_checked:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.schema.already_checked",
            message="schema state already verified earlier in lifecycle",
            run_migrations=settings.run_migrations_on_startup,
        )
        return result
    if not settings.run_migrations_on_startup:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.schema.migrations_disabled",
            message="skipping schema migrations due to configuration",
        )
        return result
    try:
        apply_migrations(settings.database_url)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.ERROR,
            event="worker.schema.migration_failed",
            message="alembic migrations failed to apply",
            error=str(exc),
        )
        raise
    revision = get_current_revision(settings.database_url)
    if revision is None:
        log_event(
            logger,
            logging.WARNING,
            event="worker.schema.untracked",
            message="applied migrations but could not resolve Alembic revision",
        )
    else:
        with session_scope() as session:
            previous_revision = shared_repository.record_schema_version(session, revision)
        result.current_revision = revision
        result.previous_revision = previous_revision
        result.changed = previous_revision != revision
        log_event(
            logger,
            logging.DEBUG,
            event="worker.schema.synced",
            message="applied migrations and recorded schema revision",
            revision=revision,
            previous_revision=previous_revision,
        )
    _schema_checked = True
    return result


def _build_polymarket_client() -> PolymarketClient:
    return PolymarketClient(
        str(settings.polymarket_api_base),
        timeout=settings.polymarket_timeout_seconds,
        request_max_attempts=settings.polymarket_max_retries,
        request_backoff_seconds=settings.polymarket_retry_backoff_seconds,
        request_backoff_max_seconds=settings.polymarket_retry_backoff_max_seconds,
        retry_counter=POLYMARKET_RETRY_COUNTER,
        rate_limit_requests=settings.polymarket_rate_limit_requests,
        rate_limit_window_seconds=settings.polymarket_rate_limit_window_seconds,
        empty_page_tolerance=settings.polymarket_empty_page_tolerance,
        rate_limit_counter=POLYMARKET_RATE_LIMIT_COUNTER,
        empty_page_counter=POLYMARKET_EMPTY_PAGE_COUNTER,
    )


def _build_clob_client() -> ClobClient | None:
    host = settings.clob_host
    if not host:
        return None
    try:
        return ClobClient(str(host))
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="worker.clob.error",
            message="failed to initialise clob client",
            error=str(exc),
        )
        return None


def _build_prover_client() -> ProverClient | None:
    if settings.prover_enabled and settings.prover_base_url:
        return ProverClient(
            base_url=settings.prover_base_url,
            timeout_seconds=settings.prover_timeout_seconds,
        )
    return None


polymarket_client = _build_polymarket_client()
clob_client = _build_clob_client()
PROVER_CLIENT = _build_prover_client()


def _reload_worker_settings(signum=None, frame=None) -> None:  # pragma: no cover - signal handler
    global settings, polymarket_client, clob_client, conditional_tokens_client, goldsky_client, PROVER_CLIENT
    settings = reload_settings()
    polymarket_client = _build_polymarket_client()
    clob_client = _build_clob_client()
    goldsky_client = _build_goldsky_client()
    conditional_tokens_client = _build_conditional_tokens_client()
    PROVER_CLIENT = _build_prover_client()
    log_event(
        logger,
        logging.DEBUG,
        event="worker.config.reloaded",
        message="worker configuration reloaded",
        signal=signum,
        cache_namespace=settings.cache_namespace or "",
    )


def _build_conditional_tokens_client() -> ConditionalTokensClient | None:
    rpc_url = settings.polygon_rpc_url or settings.rpc_url
    contract_address = settings.conditional_tokens_address
    if not (rpc_url and contract_address):
        log_event(
            logger,
            logging.DEBUG,
            event="worker.resolution.disabled",
            message="conditional tokens client disabled (missing configuration)",
        )
        return None
    try:
        client = ConditionalTokensClient(str(rpc_url), contract_address)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="worker.resolution.error",
            message="failed to initialise conditional tokens client",
            error=str(exc),
        )
        return None
    log_event(
        logger,
        logging.DEBUG,
        event="worker.resolution.enabled",
        message="conditional tokens client initialised",
        contract_address=contract_address,
    )
    return client


def _build_goldsky_client() -> GoldskyClient | None:
    endpoint = settings.goldsky_subgraph_url
    if not endpoint:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.goldsky.disabled",
            message="goldsky subgraph client disabled (missing endpoint)",
        )
        return None
    api_key = settings.goldsky_api_key.get_secret_value() if settings.goldsky_api_key else None
    try:
        client = GoldskyClient(
            str(endpoint),
            api_key=api_key,
            timeout_seconds=settings.goldsky_timeout_seconds,
        )
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="worker.goldsky.error",
            message="failed to initialise goldsky client",
            error=str(exc),
        )
        return None
    log_event(
        logger,
        logging.DEBUG,
        event="worker.goldsky.enabled",
        message="goldsky subgraph client initialised",
    )
    return client


conditional_tokens_client = _build_conditional_tokens_client()
goldsky_client = _build_goldsky_client()

try:  # pragma: no cover - signal availability depends on platform
    signal.signal(signal.SIGHUP, _reload_worker_settings)
except (AttributeError, ValueError):
    pass


def _fetch_resolution_snapshot(
    condition_id: str,
    market: MarketPayload,
    outcome_count_hint: int | None,
) -> dict[str, Any] | None:
    """Return the best-effort resolution summary from Goldsky or fallback RPC."""
    outcomes = market.outcomes or []
    if goldsky_client is not None:
        try:
            summary = goldsky_client.resolution_summary(condition_id, outcomes, outcome_count_hint)
            if summary:
                return summary
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                logger,
                logging.WARNING,
                event="worker.resolution.goldsky_failed",
                message="failed to load resolution from goldsky",
                condition_id=condition_id,
                error=str(exc),
            )
    if conditional_tokens_client is None:
        return None
    try:
        return conditional_tokens_client.resolution_summary(condition_id, outcomes, outcome_count_hint)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="worker.resolution.fetch_failed",
            message="failed to read conditional tokens resolution",
            condition_id=condition_id,
            error=str(exc),
        )
        return None


def fetch_markets_from_polymarket() -> tuple[list[MarketPayload], float]:
    """Pull the latest markets from Polymarket using the shared client."""
    start = time.perf_counter()
    log_event(
        logger,
        logging.DEBUG,
        event="worker.fetch.start",
        message="fetching markets from polymarket",
        page_size=settings.polymarket_page_size,
        max_pages=settings.polymarket_max_pages,
        order=settings.polymarket_order,
        ascending=settings.polymarket_sort_ascending,
        closed=settings.polymarket_closed_filter,
        active=settings.polymarket_active_filter,
        archived=settings.polymarket_archived_filter,
    )

    def _log_fetch_retry(attempt: int, exc: BaseException | None) -> None:
        log_event(
            logger,
            logging.WARNING,
            event="worker.fetch.retry",
            message="retrying polymarket fetch",
            attempt=attempt,
            max_attempts=settings.polymarket_sync_max_attempts,
            error=str(exc) if exc else None,
        )

    def _build_filters() -> dict[str, Any]:
        params: dict[str, Any] = {}
        if settings.polymarket_active_filter is not None:
            params["active"] = str(settings.polymarket_active_filter).lower()
        if settings.polymarket_archived_filter is not None:
            params["archived"] = str(settings.polymarket_archived_filter).lower()
        return params

    extra_params = _build_filters()

    def _fetch() -> list[MarketPayload]:
        return polymarket_client.fetch_markets(
            page_size=settings.polymarket_page_size,
            max_pages=settings.polymarket_max_pages,
            order=settings.polymarket_order,
            ascending=settings.polymarket_sort_ascending,
            closed=settings.polymarket_closed_filter,
            extra_params=extra_params,
        )

    try:
        markets = _run_with_retries(
            _fetch,
            settings.polymarket_sync_max_attempts,
            settings.polymarket_sync_retry_backoff_seconds,
            settings.polymarket_sync_retry_backoff_max_seconds,
            on_retry=_log_fetch_retry if settings.polymarket_sync_max_attempts > 1 else None,
        )
    except Exception as exc:
        POLYMARKET_FETCH_COUNTER.labels(outcome="error").inc()
        log_event(
            logger,
            logging.ERROR,
            event="worker.fetch.error",
            message="failed to fetch markets from polymarket after retries",
            error=str(exc),
        )
        raise
    if clob_client is not None:
        try:
            merge_clob_markets(
                markets,
                clob_client,
                max_pages=settings.polymarket_max_pages,
                logger=logger,
            )
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                logger,
                logging.WARNING,
                event="worker.clob.enrichment_failed",
                message="failed to enrich markets with clob data",
                error=str(exc),
            )
    latency_ms = (time.perf_counter() - start) * 1000
    if markets:
        POLYMARKET_FETCH_COUNTER.labels(outcome="success").inc()
        log_event(
            logger,
            logging.DEBUG,
            event="worker.fetch.success",
            message="retrieved markets from polymarket",
            count=len(markets),
            latency_ms=round(latency_ms, 2),
        )
    else:
        POLYMARKET_FETCH_COUNTER.labels(outcome="empty").inc()
        log_event(
            logger,
            logging.DEBUG,
            event="worker.fetch.empty",
            message="no markets returned from polymarket feed",
            latency_ms=round(latency_ms, 2),
        )
    return markets, latency_ms


def _merge_extra_data(existing: dict | None, update: dict) -> dict:
    merged = dict(existing) if isinstance(existing, dict) else {}
    merged.update(update)
    return merged


def _slugify_token(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _record_retention_metrics(category_counts: dict[str, int]) -> None:
    for category, count in category_counts.items():
        label = category or "uncategorized"
        RETENTION_METRIC.labels(category=label).inc(count)


def _should_refresh_resolution(existing, now: datetime) -> bool:
    if existing is None:
        return True
    if not existing.resolved:
        return True
    if existing.checked_at is None:
        return True
    return (now - existing.checked_at).total_seconds() >= settings.resolution_refresh_interval_seconds


def _parse_checked_at(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return fallback
    return fallback


def _build_resolution_record(
    summary: dict[str, Any],
    market: MarketPayload,
    checked_at: datetime,
    db_market: shared_models.Market | None = None,
) -> dict[str, Any]:
    outcomes = summary.get("outcomes") or (market.outcomes or [])
    payouts = summary.get("payouts") or []
    winners = summary.get("winners") or []
    if not winners:
        winners = summary.get("winners") or _derive_winners(payouts, outcomes)
    winning_outcome = summary.get("winningOutcomeId") or summary.get("winning_outcome_id")
    if winning_outcome is None and winners:
        try:
            winning_outcome = winners[0].get("index")
        except Exception:
            winning_outcome = None
    return {
        "condition_id": summary.get("condition_id") or summary.get("conditionId"),
        "source": summary.get("source", "conditional_tokens"),
        "resolved": bool(summary.get("resolved")),
        "payouts": payouts,
        "winners": winners,
        "outcomes": outcomes,
        "oracle": summary.get("oracle"),
        "question_id": summary.get("questionId"),
        "transaction_hash": summary.get("transactionHash"),
        "block_number": summary.get("blockNumber"),
        "block_timestamp": summary.get("blockTimestamp"),
        "winning_outcome_id": winning_outcome,
        "rake_bps": summary.get("rakeBps") or getattr(market, "rake_bps", None),
        "request_id": summary.get("request_id") or summary.get("requestId"),
        "market_id": getattr(db_market, "id", None),
        "event_id": getattr(db_market, "event_id", None) or market.event_id,
        "checked_at": checked_at,
    }


def _load_existing_markets(
    session: Session,
    markets: Sequence[MarketPayload],
) -> dict[str, shared_models.Market]:
    event_ids = [market.event_id for market in markets if isinstance(market.event_id, str)]
    if not event_ids:
        return {}
    existing: dict[str, shared_models.Market] = {}
    chunk_size = 500
    for start in range(0, len(event_ids), chunk_size):
        chunk = event_ids[start : start + chunk_size]
        stmt = select(shared_models.Market).where(shared_models.Market.event_id.in_(chunk))
        for record in session.scalars(stmt):
            if record.event_id:
                existing[record.event_id] = record
    return existing


def _collect_market_changes(session: Session, markets: list[MarketPayload], redis_client: Redis | None) -> SyncSummary:
    summary = SyncSummary()
    if not markets:
        return summary
    existing_records = _load_existing_markets(session, markets)
    total_markets = len(markets)
    log_event(
        logger,
        logging.DEBUG,
        event="worker.persist.batch",
        message="synchronising markets into database",
        markets_processed=total_markets,
    )
    progress_log_step = max(total_markets // max(settings.market_progress_log_intervals, 1), 1)
    for index, market in enumerate(markets, start=1):
        if index % progress_log_step == 0 or index == 1 or index == total_markets:
            log_event(
                logger,
                logging.DEBUG,
                event="worker.persist.progress",
                message="market sync progress",
                processed=index,
                total=total_markets,
            )
        prefetched = existing_records.get(market.event_id)
        db_market, outcome = sync_market(session, market, existing_market=prefetched)
        if db_market and isinstance(db_market.event_id, str):
            existing_records[db_market.event_id] = db_market
        if outcome.market_changed and db_market and db_market.event_id:
            summary.changed_events.add(db_market.event_id)
            summary.stats_dirty = True
        if outcome.market_created:
            summary.markets_created += 1
        if outcome.market_updated:
            summary.markets_updated += 1
        if outcome.resolution_changed and outcome.condition_id:
            summary.changed_conditions.add(outcome.condition_id.lower())
        if outcome.category_slug:
            summary.changed_categories.add(outcome.category_slug)
        if outcome.resolution_cache_payload and outcome.condition_id:
            summary.resolution_cache_updates.append((outcome.condition_id, outcome.resolution_cache_payload))
        if maybe_enqueue_summary_job(redis_client, market_record=db_market, market_payload=market):
            summary.summaries_enqueued += 1
        if settings.prover_enabled and PROVER_CLIENT is not None and db_market is not None:
            summary.proof_jobs.append(
                (
                    _snapshot_market_record(db_market),
                    market,
                    outcome.condition_id,
                )
            )
    return summary


def _market_record_to_payload(record: shared_models.Market) -> MarketPayload:
    return MarketPayload(
        event_id=record.event_id,
        title=record.title or record.event_id or "Market",
        slug=record.slug,
        category=record.category,
        metadata_uri=record.metadata_uri,
        oracle=record.oracle or "polymarket",
        factory=record.factory,
        market_address=record.market_address,
        status=record.status or MarketStatusEnum.COMMIT.value,
        outcomes=record.outcomes,
        outcome_prices=record.outcome_prices,
        tags=record.tags,
        extra_data=record.extra_data,
        rake_bps=record.rake_bps,
        condition_id=record.condition_id,
        question_id=record.question_id,
        image_url=record.image_url,
        closed=record.closed,
        uma_resolution_status=record.uma_resolution_status,
        source_updated_at=record.source_updated_at,
        content_hash=record.content_hash,
        starts_at=record.starts_at,
        orders_opened_at=record.orders_opened_at,
        resolution_source=record.resolution_source,
        market_maker=record.market_maker,
        order_min_size=record.order_min_size,
        price_tick_size=record.price_tick_size,
        enable_order_book=record.enable_order_book,
        clob_token_ids=record.clob_token_ids,
        image_variants=record.image_variants,
        closes_at=record.closes_at,
    )


def _backfill_missing_resolutions(session: Session, summary: SyncSummary) -> int:
    """Hydrate historical resolutions for markets missing ledger entries."""

    limit = max(0, getattr(settings, "resolution_backfill_limit", 0))
    if limit <= 0:
        return 0

    stmt = (
        select(shared_models.Market)
        .where(
            shared_models.Market.condition_id.isnot(None),
            ~shared_models.Market.condition_id.in_(select(shared_models.Resolution.condition_id)),
        )
        .limit(limit)
    )
    backfilled = 0
    for record in session.scalars(stmt):
        if not record.condition_id or not record.event_id:
            continue
        try:
            payload = _market_record_to_payload(record)
        except Exception as exc:  # pragma: no cover - defensive guard
            log_event(
                logger,
                logging.WARNING,
                event="worker.resolution.backfill_payload_failed",
                message="failed to convert market record to payload for backfill",
                event_id=getattr(record, "event_id", None),
                error=str(exc),
            )
            continue
        outcome = _apply_resolution(session, record, payload)
        if outcome.changed and outcome.condition_id:
            summary.changed_conditions.add(outcome.condition_id)
            if outcome.cache_payload:
                summary.resolution_cache_updates.append((outcome.condition_id, outcome.cache_payload))
            backfilled += 1
    summary.resolutions_backfilled += backfilled
    return backfilled


def _count_resolution_gaps(session: Session) -> tuple[int, list[str]]:
    cutoff_seconds = getattr(settings, "resolution_gap_warn_seconds", 0)
    if cutoff_seconds <= 0:
        return 0, []
    cutoff = datetime.now(UTC) - timedelta(seconds=cutoff_seconds)
    stmt = select(
        shared_models.Market.event_id,
        shared_models.Market.condition_id,
        shared_models.Market.resolved_at,
    ).where(
        shared_models.Market.condition_id.isnot(None),
        shared_models.Market.resolved_at.isnot(None),
        shared_models.Market.resolved_at < cutoff,
        ~shared_models.Market.condition_id.in_(select(shared_models.Resolution.condition_id)),
    )
    events: list[str] = []
    for event_id, _condition_id, _resolved_at in session.execute(stmt):
        if isinstance(event_id, str):
            events.append(event_id)
    return len(events), events


def _log_resolution_gaps(session: Session) -> int:
    threshold = getattr(settings, "resolution_gap_warn_threshold", 0)
    if threshold <= 0:
        return 0
    count, events = _count_resolution_gaps(session)
    if count >= threshold:
        log_event(
            logger,
            logging.WARNING,
            event="worker.resolution.gaps",
            message="markets missing resolution ledger entries",
            gaps=count,
            sample_events=events[: min(len(events), 5)],
        )
    return count


def _apply_retention_cleanup(session: Session, summary: SyncSummary) -> None:
    cleanup_outcome = cleanup_resolved_markets(session, dry_run=settings.resolved_retention_dry_run)
    if cleanup_outcome.events:
        summary.changed_events.update(cleanup_outcome.events)
        summary.stats_dirty = True
    summary.changed_conditions.update(cleanup_outcome.conditions)
    summary.changed_categories.update(cleanup_outcome.categories)
    summary.markets_deleted = cleanup_outcome.deleted_rows
    if cleanup_outcome.category_counts:
        _record_retention_metrics(cleanup_outcome.category_counts)


def _invalidate_cache_tags(redis_client: Redis | None, summary: SyncSummary) -> CacheInvalidationReport:
    report = CacheInvalidationReport()
    if redis_client is None:
        return report

    def _invalidate(tag: str) -> None:
        removed = shared_cache.invalidate_tag(redis_client, tag)
        report.record(tag, removed)

    if summary.changed_events or summary.changed_categories:
        _invalidate("markets:list")
        _invalidate("category:trending")
        _invalidate("markets:suggest")
    if summary.stats_dirty and summary.changed_events:
        _invalidate("markets:stats")
    for event_id in summary.changed_events:
        _invalidate(f"market:{event_id}")
    for condition_id in summary.changed_conditions:
        _invalidate(f"resolution:{condition_id}")
    for category_slug in summary.changed_categories:
        _invalidate(f"category:{category_slug}")
    if summary.changed_categories:
        CACHE_INVALIDATION_COUNTER.labels(type="category").inc(len(summary.changed_categories))
    report.log()
    return report


def _persist_resolution_cache_updates(redis_client: Redis | None, summary: SyncSummary) -> None:
    if redis_client is None or not summary.resolution_cache_updates:
        return
    for condition_id, payload in summary.resolution_cache_updates:
        shared_cache.set_json(
            redis_client,
            resolution_cache_key(condition_id),
            payload,
            settings.markets_cache_ttl_seconds,
        )


def _run_prover_jobs(summary: SyncSummary, redis_client: Redis | None) -> int:
    if not settings.auto_settlement_enabled:
        return 0
    proofs_generated = 0
    for snapshot, payload, condition in summary.proof_jobs:
        if maybe_generate_settlement_proof(
            redis_client,
            market_snapshot=snapshot,
            market_payload=payload,
            condition_id=condition,
        ):
            proofs_generated += 1
    return proofs_generated


def _apply_resolution(session: Session, db_market, market: MarketPayload) -> ResolutionOutcome:
    condition_id = market.condition_id
    if (
        (goldsky_client is None and conditional_tokens_client is None)
        or not isinstance(condition_id, str)
        or not condition_id.startswith("0x")
    ):
        if logger.isEnabledFor(logging.DEBUG):
            log_event(
                logger,
                logging.DEBUG,
                event="worker.resolution.skipped_unavailable",
                message="skipping resolution sync because prerequisites not met",
                condition_id=condition_id,
                goldsky_enabled=goldsky_client is not None,
                conditional_tokens_enabled=conditional_tokens_client is not None,
            )
        return ResolutionOutcome()

    normalized_condition_id = condition_id.lower()
    outcome_count_hint = len(market.outcome_prices) if market.outcome_prices else None
    existing = shared_repository.get_resolution_by_condition_id(session, normalized_condition_id)
    now = datetime.now(UTC)

    if not _should_refresh_resolution(existing, now):
        if logger.isEnabledFor(logging.DEBUG):
            log_event(
                logger,
                logging.DEBUG,
                event="worker.resolution.skip_refresh",
                message="existing resolution snapshot still within freshness window",
                condition_id=normalized_condition_id,
                last_checked=getattr(existing, "checked_at", None).isoformat()
                if getattr(existing, "checked_at", None)
                else None,
                resolved=getattr(existing, "resolved", None),
            )
        return ResolutionOutcome()

    summary = _fetch_resolution_snapshot(normalized_condition_id, market, outcome_count_hint)
    if summary is None:
        if logger.isEnabledFor(logging.DEBUG):
            log_event(
                logger,
                logging.DEBUG,
                event="worker.resolution.snapshot_missing",
                message="resolution snapshot could not be loaded",
                condition_id=normalized_condition_id,
            )
        return ResolutionOutcome()

    checked_at_dt = _parse_checked_at(summary.get("checkedAt"), now)
    record_payload = _build_resolution_record(summary, market, checked_at_dt, db_market=db_market)
    record_payload["condition_id"] = normalized_condition_id

    if record_payload["resolved"] and (
        record_payload.get("transaction_hash") is None or record_payload.get("block_number") is None
    ):
        log_event(
            logger,
            logging.WARNING,
            event="worker.resolution.partial_payload",
            message="resolution payload missing block metadata",
            condition_id=normalized_condition_id,
            tx_hash=record_payload.get("transaction_hash"),
            block_number=record_payload.get("block_number"),
        )

    shared_repository.upsert_resolution(session, record_payload)
    cache_payload = {
        **record_payload,
        "checkedAt": checked_at_dt.isoformat(),
    }
    block_ts = cache_payload.get("block_timestamp")
    if isinstance(block_ts, datetime):
        cache_payload["block_timestamp"] = block_ts.isoformat()

    log_event(
        logger,
        logging.DEBUG,
        event="worker.resolution.persisted",
        message="persisted conditional tokens resolution snapshot",
        condition_id=normalized_condition_id,
        resolved=record_payload["resolved"],
        block_number=record_payload["block_number"],
    )

    db_market.extra_data = _merge_extra_data(
        db_market.extra_data,
        {
            "resolution": {
                "source": record_payload["source"],
                "checkedAt": checked_at_dt.isoformat(),
                "resolved": record_payload["resolved"],
            }
        },
    )

    if record_payload["resolved"]:
        db_market.status = "settled"
        if getattr(db_market, "closed", None) is not True:
            db_market.closed = True
        db_market.resolved_at = checked_at_dt
        log_event(
            logger,
            logging.DEBUG,
            event="worker.resolution.detected",
            message="polymarket resolution detected",
            condition_id=normalized_condition_id,
            winners=record_payload["winners"],
            block_number=record_payload["block_number"],
        )
    else:
        db_market.resolved_at = None
    return ResolutionOutcome(
        changed=True,
        condition_id=normalized_condition_id,
        cache_payload=cache_payload,
    )


def sync_market(
    session: Session,
    market: MarketPayload,
    existing_market: shared_models.Market | None = None,
):
    """Upsert a market row using `event_id` as the natural key, reusing prefetched state when available."""
    now = datetime.now(UTC)
    existing = existing_market or shared_repository.get_market_by_event_id(session, market.event_id)
    payload = market.model_dump()
    if payload.get("closed") is None:
        payload["closed"] = False
    condition_id = payload.get("condition_id")
    if isinstance(condition_id, str):
        payload["condition_id"] = condition_id.lower()
    close_deadline = payload.get("closes_at")
    if close_deadline is None and existing is not None:
        close_deadline = getattr(existing, "closes_at", None)
        if close_deadline is not None:
            payload["closes_at"] = close_deadline
    should_close = _should_close_market(close_deadline, market.closed, now)
    payload["closed"] = should_close
    status_value = payload.get("status") or MarketStatusEnum.COMMIT.value
    if should_close and status_value not in {MarketStatusEnum.SETTLED.value, MarketStatusEnum.CANCELLED.value}:
        status_value = MarketStatusEnum.LOCKED.value
    payload["status"] = status_value

    if logger.isEnabledFor(logging.DEBUG):
        log_event(
            logger,
            logging.DEBUG,
            event="worker.market.payload_ready",
            message="prepared market payload for persistence",
            event_id=market.event_id,
            existing=existing is not None,
            should_close=should_close,
            status=status_value,
        )
    db_market = existing
    market_changed = False
    market_created = False
    market_updated = False
    incoming_updated_at = getattr(market, "source_updated_at", None)
    incoming_hash = getattr(market, "content_hash", None)

    if existing is None:
        db_market = shared_repository.upsert_market(session, payload, existing)
        market_changed = True
        market_created = True
        if logger.isEnabledFor(logging.DEBUG):
            log_event(
                logger,
                logging.DEBUG,
                event="worker.market.created",
                message="market created from polymarket feed",
                event_id=market.event_id,
                status=payload.get("status"),
                category=payload.get("category"),
            )
    else:
        match, match_reason = _markets_match(existing, incoming_updated_at, incoming_hash)
        if match:
            if logger.isEnabledFor(logging.DEBUG):
                log_event(
                    logger,
                    logging.DEBUG,
                    event="worker.market.skip_update",
                    message="skipping market update (no changes detected)",
                    event_id=market.event_id,
                    reason=match_reason,
                )
        else:
            db_market = shared_repository.upsert_market(session, payload, existing)
            market_changed = True
            market_updated = True
            if logger.isEnabledFor(logging.DEBUG):
                log_event(
                    logger,
                    logging.DEBUG,
                    event="worker.market.updated",
                    message="market updated from polymarket feed",
                    event_id=market.event_id,
                    status=payload.get("status"),
                    category=payload.get("category"),
                    match_reason=match_reason,
                )

    if market.rake_bps is not None and db_market is not None:
        db_market.rake_bps = market.rake_bps
    _record_factory_state(session, db_market, market)
    resolution_outcome = _apply_resolution(session, db_market, market)
    session.flush()
    category_slug = _slugify_token(getattr(db_market, "category", None))
    return db_market, SyncOutcome(
        market_changed=market_changed,
        resolution_changed=resolution_outcome.changed,
        category_slug=category_slug,
        condition_id=resolution_outcome.condition_id,
        resolution_cache_payload=resolution_outcome.cache_payload,
        market_created=market_created,
        market_updated=market_updated,
    )


def _markets_match(existing, source_updated_at: datetime | None, content_hash: str | None) -> tuple[bool, str]:
    if source_updated_at and getattr(existing, "source_updated_at", None) == source_updated_at:
        return True, "source_timestamp"
    existing_hash = getattr(existing, "content_hash", None)
    if content_hash and existing_hash and existing_hash == content_hash:
        return True, "content_hash"
    return False, "diff_detected"


def _should_close_market(close_deadline: datetime | None, explicit_closed: bool | None, now: datetime) -> bool:
    if isinstance(explicit_closed, bool) and explicit_closed:
        return True
    if isinstance(close_deadline, datetime):
        deadline = close_deadline if close_deadline.tzinfo else close_deadline.replace(tzinfo=UTC)
        return deadline <= now
    return False


def cleanup_resolved_markets(  # noqa: C901
    session: Session,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> CleanupOutcome:
    """Remove markets that have been resolved for longer than the configured retention."""

    reference_time = _as_utc(now) or datetime.now(UTC)
    cutoff = reference_time - timedelta(seconds=settings.resolved_retention_seconds)
    stmt = select(
        shared_models.Market.id,
        shared_models.Market.event_id,
        shared_models.Market.condition_id,
        shared_models.Market.category,
        shared_models.Market.resolved_at,
        shared_models.Market.closes_at,
        shared_models.Market.closed,
    ).where(
        or_(
            shared_models.Market.resolved_at.isnot(None) & (shared_models.Market.resolved_at < cutoff),
            shared_models.Market.closed.is_(True)
            & shared_models.Market.closes_at.isnot(None)
            & (shared_models.Market.closes_at < cutoff),
        )
    )
    records = session.execute(stmt).all()

    if not records:
        return CleanupOutcome(
            set(),
            set(),
            set(),
            deleted_rows=0,
            eligible_rows=0,
            dry_run=dry_run,
            category_counts={},
        )

    ids_to_delete: list[int] = []
    event_ids: set[str] = set()
    condition_ids: set[str] = set()
    categories: set[str] = set()
    category_counts: dict[str, int] = {}

    for row in records:
        resolved_at = _as_utc(row.resolved_at)
        closes_at = _as_utc(getattr(row, "closes_at", None))
        is_closed = bool(getattr(row, "closed", False))
        resolved_expired = resolved_at is not None and resolved_at <= cutoff
        closed_expired = is_closed and closes_at is not None and closes_at <= cutoff
        if not resolved_expired and not closed_expired:
            continue
        if row.id is not None:
            ids_to_delete.append(row.id)
        if row.event_id:
            event_ids.add(row.event_id)
        if isinstance(row.condition_id, str):
            condition_ids.add(row.condition_id.lower())
        cat_slug = _slugify_token(row.category)
        if cat_slug:
            categories.add(cat_slug)
        normalized_category = cat_slug or "uncategorized"
        category_counts[normalized_category] = category_counts.get(normalized_category, 0) + 1

    eligible = len(ids_to_delete)
    if eligible == 0:
        return CleanupOutcome(
            event_ids,
            condition_ids,
            categories,
            deleted_rows=0,
            eligible_rows=0,
            dry_run=dry_run,
            category_counts=category_counts,
        )

    # We no longer delete historical markets; retention now only reports metrics.
    _record_retention_metrics(category_counts)
    log_event(
        logger,
        logging.DEBUG,
        event="worker.retention.cleanup",
        message="evaluated resolved markets for retention (historical retention disabled)",
        eligible=eligible,
        deleted=0,
        dry_run=True,
        cutoff=cutoff.isoformat(),
    )
    return CleanupOutcome(
        event_ids,
        condition_ids,
        categories,
        deleted_rows=0,
        eligible_rows=eligible,
        dry_run=True,
        category_counts=category_counts,
    )


def _calculate_sleep(start_time: float) -> float:
    """Determine how long the worker should sleep to honour the poll interval."""
    elapsed = time.time() - start_time
    return max(settings.poll_interval_seconds - elapsed, 0)


def _propagate_schema_revision(redis_client: Redis | None, state: SchemaSyncResult) -> None:
    """Publish the current schema revision for cache tagging + invalidate stale tags."""

    if redis_client is None or state.current_revision is None:
        return
    try:
        redis_client.set(settings.schema_version_key, state.current_revision)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="worker.schema.version_cache_error",
            message="failed to write schema revision cache key",
            error=str(exc),
        )
        return

    log_event(
        logger,
        logging.DEBUG,
        event="worker.schema.version_cached",
        message="published schema revision for cache tagging",
        revision=state.current_revision,
    )

    if state.changed:
        previous_tag = f"schema:{state.previous_revision}" if state.previous_revision else None
        tags_to_invalidate = ["schema:unknown"]
        if previous_tag:
            tags_to_invalidate.append(previous_tag)
        for tag in tags_to_invalidate:
            invalidated = shared_cache.invalidate_tag(redis_client, tag)
            log_event(
                logger,
                logging.DEBUG,
                event="worker.schema.cache_reset",
                message="invalidated schema-tagged cache entries",
                tag=tag,
                keys=invalidated,
            )


def publish_heartbeat(redis_client: Redis | None, stats: dict[str, Any]) -> None:
    """Update a Redis key so external monitors can assert liveness."""

    if redis_client is None:
        return
    payload = {
        "service": settings.app_name,
        "component": "worker",
        "environment": settings.environment,
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
    }

    def _publish() -> bool:
        redis_client.set(
            settings.heartbeat_key,
            json.dumps(payload),
            ex=settings.heartbeat_ttl_seconds,
        )
        return True

    try:
        _run_with_retries(
            _publish,
            settings.heartbeat_max_retries,
            settings.heartbeat_retry_backoff_seconds,
            settings.heartbeat_retry_backoff_max_seconds,
        )
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="worker.heartbeat.error",
            message="failed to publish worker heartbeat",
            error=str(exc),
        )
    else:
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
            heartbeat_key=settings.heartbeat_key,
        )


def run_worker() -> None:
    """Main polling loop that downloads markets and writes them into the database."""
    try:
        redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
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
        poll_interval_seconds=settings.poll_interval_seconds,
        page_size=settings.polymarket_page_size,
    )
    heartbeat_stop = start_heartbeat_logger(
        logger,
        service_name="reveal_market.worker",
        interval_seconds=settings.container_heartbeat_seconds,
        message="Worker container heartbeat",
    )
    try:
        while True:
            loop_start = time.time()
            sync_stats = process_once(redis_client)
            prime_stats = prime_markets_cache(redis_client)
            featured_stats = prime_featured_views(redis_client)
            prime_stats.update(featured_stats)
            record_batch_stats(redis_client, sync_stats, prime_stats)
            time.sleep(_calculate_sleep(loop_start))
    finally:
        heartbeat_stop.set()


def _empty_sync_stats(latency_ms: float = 0.0) -> dict[str, float | int]:
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
    }


def process_once(redis_client: Redis | None = None) -> dict[str, float | int]:
    """Fetch markets, persist them, and emit a heartbeat once."""

    log_event(
        logger,
        logging.INFO,
        event="worker.sync.begin",
        message="starting worker sync tick",
        poll_interval_seconds=settings.poll_interval_seconds,
    )
    schema_state = _ensure_schema()
    log_event(
        logger,
        logging.DEBUG,
        event="worker.schema.state",
        message="schema check finished for sync tick",
        changed=schema_state.changed,
        current_revision=schema_state.current_revision,
        previous_revision=schema_state.previous_revision,
    )
    try:
        markets, latency_ms = fetch_markets_from_polymarket()
        log_event(
            logger,
            logging.DEBUG,
            event="worker.sync.fetch_complete",
            message="polymarket fetch returned payloads",
            markets_fetched=len(markets),
            latency_ms=round(latency_ms, 2),
        )
    except Exception as exc:
        stats = _empty_sync_stats()
        log_event(
            logger,
            logging.WARNING,
            event="worker.sync.skipped",
            message="skipping market sync due to upstream failure",
            error=str(exc),
        )
        publish_heartbeat(redis_client, stats)
        _propagate_schema_revision(redis_client, schema_state)
        return stats

    summary = SyncSummary()
    gap_count = 0
    try:
        with session_scope() as session:
            if markets:
                summary = _collect_market_changes(session, markets, redis_client)
            else:
                if logger.isEnabledFor(logging.DEBUG):
                    log_event(
                        logger,
                        logging.DEBUG,
                        event="worker.persist.no_markets",
                        message="skipping DB persistence because no markets were returned",
                    )
            _apply_retention_cleanup(session, summary)
            backfilled = _backfill_missing_resolutions(session, summary)
            if backfilled:
                log_event(
                    logger,
                    logging.INFO,
                    event="worker.resolution.backfill_complete",
                    message="backfilled missing resolution snapshots",
                    count=backfilled,
                )
            gap_count = _log_resolution_gaps(session)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception(
            "failed to synchronise markets",
            extra={"event": "worker.persist.error", "error": str(exc)},
        )
        stats = _empty_sync_stats(round(latency_ms, 2))
        publish_heartbeat(redis_client, stats)
        _propagate_schema_revision(redis_client, schema_state)
        return stats

    summary.proofs_generated = _run_prover_jobs(summary, redis_client)
    cache_report = _invalidate_cache_tags(redis_client, summary)
    stats = summary.to_stats(len(markets), latency_ms, cache_report.total)
    stats["resolution_gaps"] = gap_count

    log_event(
        logger,
        logging.INFO,
        event="worker.sync.summary",
        message="sync tick complete",
        processed=len(markets),
        created=summary.markets_created,
        updated=summary.markets_updated,
        deleted=summary.markets_deleted,
        resolutions=len(summary.changed_conditions),
        resolutions_backfilled=summary.resolutions_backfilled,
        summaries=summary.summaries_enqueued,
        proofs=summary.proofs_generated,
        latency_ms=round(latency_ms, 2),
        cache_invalidations=cache_report.total,
    )
    # INFO-level summary above mirrors the start-of-tick log so operators always see
    # a single before/after line even when DEBUG logs are disabled.

    publish_heartbeat(redis_client, stats)
    _propagate_schema_revision(redis_client, schema_state)
    _persist_resolution_cache_updates(redis_client, summary)
    return stats


def maybe_generate_settlement_proof(
    redis_client: Redis | None,
    *,
    market_snapshot: dict[str, Any],
    market_payload: MarketPayload,
    condition_id: str | None,
) -> bool:
    """Call the prover service when settlements change so downstream services can audit proofs."""

    if not settings.prover_enabled or PROVER_CLIENT is None:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.proof.disabled",
            message="settlement proof generation is disabled or client unavailable",
            prover_enabled=settings.prover_enabled,
        )
        return False
    market_id = market_snapshot.get("id") or market_snapshot.get("market_id")
    if not market_id:
        market_id = condition_id or market_snapshot.get("condition_id") or market_snapshot.get("event_id")
    if not market_id:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.proof.no_market_id",
            message="skipping proof generation due to missing market id",
            event_id=market_snapshot.get("event_id"),
        )
        return False
    payload: dict[str, Any]
    try:
        with session_scope() as session:
            payload = build_prover_payload(session, int(market_id))
            payload["metadata"] = _build_proof_metadata(market_payload)
    except ValueError:
        fallback = _build_snapshot_payload(market_snapshot, market_payload, market_id)
        if not fallback:
            log_event(
                logger,
                logging.DEBUG,
                event="worker.proof.incomplete",
                message="skipping proof generation due to missing settlement fields",
                error="non-numeric market id and no snapshot payload",
                event_id=market_snapshot.get("event_id"),
            )
            return False
        payload = fallback
    except SettlementDataMissingError as exc:
        fallback = _build_snapshot_payload(market_snapshot, market_payload, market_id)
        if not fallback:
            log_event(
                logger,
                logging.DEBUG,
                event="worker.proof.incomplete",
                message="skipping proof generation due to missing settlement fields",
                error=str(exc),
                event_id=market_snapshot.get("event_id"),
            )
            return False
        payload = fallback
    log_event(
        logger,
        logging.DEBUG,
        event="worker.proof.request_ready",
        message="constructed settlement proof request",
        market_id=payload.get("marketId"),
        merkle_root=payload.get("merkleRoot"),
    )
    try:
        with session_scope() as session:
            try:
                numeric_market_id = int(payload["marketId"])
            except Exception:
                numeric_market_id = None
            if numeric_market_id is not None:
                _persist_settlement_snapshot(session, numeric_market_id, payload)
        response = PROVER_CLIENT.generate_settlement_proof(payload)
    except ProverError as exc:
        log_event(
            logger,
            logging.WARNING,
            event="worker.proof.failed",
            message="prover rejected settlement request",
            error=str(exc),
            event_id=market_snapshot.get("event_id"),
        )
        return False
    cache_key = proof_receipt_cache_key(condition_id or "")
    if redis_client is not None:
        shared_cache.set_json(
            redis_client,
            cache_key,
            response.to_json(),
            settings.proof_cache_ttl_seconds,
        )

    proof_hash = None
    try:
        from eth_utils import keccak

        proof_hash = keccak((response.proof or "" + "".join(response.public_signals or [])).encode()).hex()
    except Exception:
        proof_hash = None

    try:
        with session_scope() as session:
            settlement = session.execute(
                select(shared_models.Settlement).where(shared_models.Settlement.market_id == int(market_id))
            ).scalar_one_or_none()
            if settlement:
                settlement.proof_status = shared_models.SettlementProofStatus.GENERATED.value
                settlement.proof_request_id = response.request_id
                settlement.proof_hash = f"0x{proof_hash}" if proof_hash else None
                session.add(settlement)
                shared_repository.record_settlement_receipt(
                    session,
                    market_id=settlement.market_id,
                    market_address=market_snapshot.get("market_address"),
                    request_id=response.request_id,
                    proof_hash=f"0x{proof_hash}" if proof_hash else None,
                    public_signals=response.public_signals,
                    prover_version=response.prover_version,
                    circuit_hash=response.circuit_hash,
                    generated_at=response.generated_at,
                )
                session.commit()
    except Exception as exc:  # pragma: no cover - best effort
        log_event(
            logger,
            logging.WARNING,
            event="worker.proof.persist_failed",
            message="failed to persist proof metadata",
            error=str(exc),
            market_id=market_id,
        )

    log_event(
        logger,
        logging.DEBUG,
        event="worker.proof.generated",
        message="cached settlement proof receipt",
        event_id=market_snapshot.get("event_id"),
        condition_id=condition_id or market_snapshot.get("condition_id"),
        prover_version=response.prover_version,
        nonce=getattr(response, "request_id", None),
    )
    return True


def _build_snapshot_payload(
    market_snapshot: dict[str, Any], market_payload: MarketPayload, market_id: str | int
) -> dict[str, Any] | None:
    """Build a prover payload directly from an in-memory market snapshot when DB state is incomplete.

    This is primarily used in tests or transitional flows where the worker has not yet persisted
    commitments/settlements. All required fields must be present in the snapshot.
    """

    required_fields = [
        "commitments_root",
        "tickets",
        "pool_totals",
        "total_escrow",
        "total_liability",
        "rake_bps",
        "winning_outcome_id",
        "circuit_hash",
    ]
    for key in required_fields:
        if key not in market_snapshot or market_snapshot[key] in (None, ""):
            return None

    return {
        "marketId": str(market_id),
        "merkleRoot": market_snapshot["commitments_root"],
        "winningOutcomeId": market_snapshot["winning_outcome_id"],
        "poolTotals": [str(x) for x in market_snapshot.get("pool_totals", [])],
        "totalEscrow": str(market_snapshot["total_escrow"]),
        "totalLiability": str(market_snapshot["total_liability"]),
        "rakeBps": str(market_snapshot.get("rake_bps", 0)),
        "circuitHash": market_snapshot["circuit_hash"],
        "tickets": market_snapshot.get("tickets", []),
        "metadata": _build_proof_metadata(market_payload),
    }


def _derive_total_pool_value(market_payload: MarketPayload) -> str:
    prices = market_payload.outcome_prices or []
    numeric_prices = [price for price in prices if isinstance(price, (int, float))]
    if numeric_prices:
        total = sum(numeric_prices)
        scaled = max(int(total * 1_000_000), 1)
        return str(scaled)
    outcomes = market_payload.outcomes or []
    return str(max(len(outcomes), 1))


def _derive_winning_pool_value(market_payload: MarketPayload) -> str:
    prices = market_payload.outcome_prices or []
    numeric_prices = [price for price in prices if isinstance(price, (int, float))]
    if numeric_prices:
        winning = max(numeric_prices)
        scaled = max(int(winning * 1_000_000), 1)
        return str(scaled)
    return "1"


def _normalize_market_address(address: str | None) -> str:
    if not address:
        return "0x" + "0" * 40
    normalized = address.lower().replace("0x", "")
    padded = normalized.rjust(40, "0")
    return f"0x{padded}"


def _build_proof_metadata(market_payload: MarketPayload) -> dict[str, str]:
    metadata: dict[str, str] = {}
    if market_payload.status:
        metadata["status"] = str(market_payload.status)
    if market_payload.oracle:
        metadata["oracle"] = str(market_payload.oracle)
    if market_payload.category:
        metadata["category"] = str(market_payload.category)
    if market_payload.source_updated_at:
        metadata["source_updated_at"] = market_payload.source_updated_at.isoformat()
    return metadata


def prime_markets_cache(
    redis_client: Redis | None,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Fetch and cache the homepage markets list so the API responds instantly."""

    limit = settings.markets_cache_limit
    offset = settings.markets_cache_offset
    cache_key = markets_list_cache_key(None, None, None, None, limit, offset)
    summary: dict[str, Any] = {
        "status": "skipped",
        "limit": limit,
        "offset": offset,
        "cache_key": cache_key,
    }

    if redis_client is None:
        summary["reason"] = "redis_unavailable"
        return summary
    if not settings.prime_markets_cache_enabled:
        summary["reason"] = "disabled"
        return summary
    if not settings.api_base_url:
        summary["reason"] = "api_base_url_missing"
        return summary

    url = f"{settings.api_base_url.rstrip('/')}/markets"
    params = {"limit": limit, "offset": offset}
    start = time.perf_counter()
    try:
        with httpx.Client(timeout=settings.cache_prime_timeout_seconds, transport=transport) as client:
            response = client.get(url, params=params)  # type: ignore[arg-type]
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # pragma: no cover - defensive
        duration_ms = (time.perf_counter() - start) * 1000
        log_event(
            logger,
            logging.WARNING,
            event="worker.cache.prime_failed",
            message="failed to prime homepage markets cache",
            limit=limit,
            offset=offset,
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
    result_count = len(payload) if isinstance(payload, list) else 0
    log_event(
        logger,
        logging.DEBUG,
        event="worker.cache.primed",
        message="prefetched homepage markets via API",
        limit=limit,
        offset=offset,
        cache_key=cache_key,
        result_count=result_count,
        duration_ms=round(duration_ms, 2),
    )
    summary.update(
        {
            "status": "primed",
            "duration_ms": round(duration_ms, 2),
            "result_count": result_count,
        }
    )
    return summary


def prime_featured_views(
    redis_client: Redis | None,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {"categories_primed": 0, "suggestions_primed": 0, "suggestion_ttls": {}}
    if redis_client is None or not settings.api_base_url:
        return summary
    if not settings.featured_categories and not settings.featured_suggest_queries:
        return summary
    base_url = settings.api_base_url.rstrip("/")
    with httpx.Client(timeout=settings.cache_prime_timeout_seconds, transport=transport) as client:
        for category in settings.featured_categories:
            slug = quote_plus(category)
            params = {"limit": settings.category_cache_limit}
            try:
                response = client.get(f"{base_url}/categories/{slug}", params=params)
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
        for query in settings.featured_suggest_queries:
            params = {"q": query, "limit": settings.suggest_cache_limit}
            try:
                response = client.get(f"{base_url}/markets/suggest", params=params)
                if response.is_success:
                    summary["suggestions_primed"] += 1
                    key = suggest_cache_key(query, settings.suggest_cache_limit)
                    ttl = redis_client.ttl(key)
                    if ttl is None or ttl < 0:
                        ttl = settings.markets_cache_ttl_seconds
                    summary["suggestion_ttls"][query] = ttl
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
        categories=settings.featured_categories,
        suggest_queries=settings.featured_suggest_queries,
        categories_primed=summary["categories_primed"],
        suggestions_primed=summary["suggestions_primed"],
        suggestion_ttls=summary["suggestion_ttls"],
    )
    return summary


def record_batch_stats(
    redis_client: Redis | None,
    sync_stats: dict[str, float | int],
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
    shared_cache.set_json(redis_client, settings.batch_stats_key, payload, settings.batch_stats_ttl_seconds)
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


def main() -> None:  # pragma: no cover - CLI bootstrap
    """CLI entrypoint used by Docker/Procfile executions."""
    try:
        run_worker()
    except KeyboardInterrupt:  # pragma: no cover - graceful shutdown
        logger.info("worker interrupted, shutting down")


if __name__ == "__main__":
    main()
