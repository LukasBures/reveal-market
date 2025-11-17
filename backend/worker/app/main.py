"""Worker entrypoint that periodically syncs markets from Polymarket into the local database."""

from __future__ import annotations

import json
import logging
import re
import signal
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote_plus

import httpx
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
from shared.onchain import ConditionalTokensClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings, reload_settings
from .logging_config import setup_logging
from .polymarket import MarketPayload, PolymarketClient
from .prover_client import ProverClient, ProverError, SettlementProofRequest, compute_outcome_hash
from .summary_jobs import maybe_enqueue_summary_job

try:
    from prometheus_client import Counter
except ImportError:  # pragma: no cover - optional dependency

    class Counter:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def labels(self, **kwargs):
            return self

        @staticmethod
        def inc(amount: float = 1.0) -> None:
            return None


RETENTION_DELETED_COUNTER = Counter(
    "worker_retention_deleted_total",
    "Markets deleted by the retention task",
    ["category"],
)
RETENTION_SKIPPED_COUNTER = Counter(
    "worker_retention_skipped_total",
    "Markets eligible for retention but skipped (dry run)",
    ["category"],
)

CACHE_INVALIDATION_COUNTER = Counter(
    "worker_cache_invalidations_total",
    "Number of cache invalidations triggered by the worker",
    ["type"],
)

POLYMARKET_FETCH_COUNTER = Counter(
    "worker_polymarket_fetch_total",
    "Outcome of Polymarket fetch attempts",
    ["outcome"],
)

POLYMARKET_RETRY_COUNTER = Counter(
    "worker_polymarket_retry_total",
    "Retry outcomes for individual Polymarket HTTP requests",
    ["outcome"],
)

setup_logging("reveal_market.worker")
logger = logging.getLogger("reveal_market.worker")

settings = get_settings()
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
    tag_slugs: list[str]
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
    tags: set[str]
    deleted_rows: int = 0
    eligible_rows: int = 0
    dry_run: bool = False
    category_counts: dict[str, int] | None = None


@dataclass
class SyncSummary:
    changed_events: set[str] = field(default_factory=set)
    changed_conditions: set[str] = field(default_factory=set)
    changed_categories: set[str] = field(default_factory=set)
    changed_tags: set[str] = field(default_factory=set)
    resolution_cache_updates: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    proof_jobs: list[tuple[dict[str, Any], MarketPayload, str | None]] = field(default_factory=list)
    stats_dirty: bool = False
    markets_created: int = 0
    markets_updated: int = 0
    markets_deleted: int = 0
    summaries_enqueued: int = 0
    proofs_generated: int = 0

    def to_stats(self, markets_processed: int, latency_ms: float, cache_invalidations: int) -> dict[str, Any]:
        return {
            "markets_processed": markets_processed,
            "markets_changed": len(self.changed_events),
            "resolutions_changed": len(self.changed_conditions),
            "categories_changed": len(self.changed_categories),
            "tags_changed": len(self.changed_tags),
            "latency_ms": round(latency_ms, 2),
            "markets_created": self.markets_created,
            "markets_updated": self.markets_updated,
            "markets_deleted": self.markets_deleted,
            "summaries_enqueued": self.summaries_enqueued,
            "proofs_generated": self.proofs_generated,
            "cache_invalidations": cache_invalidations,
        }


@dataclass
class CacheInvalidationReport:
    tag_counts: dict[str, int] = field(default_factory=dict)

    def record(self, tag: str, removed: int) -> None:
        self.tag_counts[tag] = self.tag_counts.get(tag, 0) + max(removed, 0)

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


def _run_with_retries[T](
    action: Callable[[], T],
    max_attempts: int,
    base_backoff: float,
    max_backoff: float | None = None,
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

    retryer = Retrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(**wait_kwargs),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    return retryer(action)


def _ensure_schema() -> SchemaSyncResult:
    """Apply database migrations once per worker lifecycle if configured."""

    global _schema_checked
    result = SchemaSyncResult()
    if _schema_checked or not settings.run_migrations_on_startup:
        return result
    apply_migrations(settings.database_url)
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
            logging.INFO,
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
    )


def _build_prover_client() -> ProverClient | None:
    if settings.prover_enabled and settings.prover_base_url:
        return ProverClient(
            base_url=settings.prover_base_url,
            timeout_seconds=settings.prover_timeout_seconds,
        )
    return None


polymarket_client = _build_polymarket_client()
PROVER_CLIENT = _build_prover_client()


def _reload_worker_settings(signum=None, frame=None) -> None:  # pragma: no cover - signal handler
    global settings, polymarket_client, conditional_tokens_client, goldsky_client, PROVER_CLIENT
    settings = reload_settings()
    polymarket_client = _build_polymarket_client()
    goldsky_client = _build_goldsky_client()
    conditional_tokens_client = _build_conditional_tokens_client()
    PROVER_CLIENT = _build_prover_client()
    log_event(
        logger,
        logging.INFO,
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
        logging.INFO,
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
        logging.INFO,
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
    )

    try:
        markets = polymarket_client.fetch_markets(
            page_size=settings.polymarket_page_size,
            max_pages=settings.polymarket_max_pages,
            order=settings.polymarket_order,
            ascending=settings.polymarket_sort_ascending,
            closed=settings.polymarket_closed_filter,
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
    latency_ms = (time.perf_counter() - start) * 1000
    if markets:
        POLYMARKET_FETCH_COUNTER.labels(outcome="success").inc()
        log_event(
            logger,
            logging.INFO,
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


def _record_retention_metrics(category_counts: dict[str, int], dry_run: bool) -> None:
    counter = RETENTION_SKIPPED_COUNTER if dry_run else RETENTION_DELETED_COUNTER
    for category, count in category_counts.items():
        label = category or "uncategorized"
        counter.labels(category=label).inc(count)


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


def _build_resolution_record(summary: dict[str, Any], market: MarketPayload, checked_at: datetime) -> dict[str, Any]:
    return {
        "condition_id": summary.get("condition_id") or summary.get("conditionId"),
        "source": summary.get("source", "conditional_tokens"),
        "resolved": bool(summary.get("resolved")),
        "payouts": summary.get("payouts") or [],
        "winners": summary.get("winners") or [],
        "outcomes": summary.get("outcomes") or (market.outcomes or []),
        "oracle": summary.get("oracle"),
        "question_id": summary.get("questionId"),
        "transaction_hash": summary.get("transactionHash"),
        "block_number": summary.get("blockNumber"),
        "block_timestamp": summary.get("blockTimestamp"),
        "checked_at": checked_at,
    }


def _collect_market_changes(session: Session, markets: list[MarketPayload], redis_client: Redis | None) -> SyncSummary:
    summary = SyncSummary()
    if not markets:
        return summary
    log_event(
        logger,
        logging.INFO,
        event="worker.persist.batch",
        message="synchronising markets into database",
        markets_processed=len(markets),
    )
    for market in markets:
        db_market, outcome = sync_market(session, market)
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
        if outcome.tag_slugs:
            summary.changed_tags.update(slug for slug in outcome.tag_slugs if slug)
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


def _apply_retention_cleanup(session: Session, summary: SyncSummary) -> None:
    cleanup_outcome = cleanup_resolved_markets(session, dry_run=settings.resolved_retention_dry_run)
    if cleanup_outcome.events:
        summary.changed_events.update(cleanup_outcome.events)
        summary.stats_dirty = True
    summary.changed_conditions.update(cleanup_outcome.conditions)
    summary.changed_categories.update(cleanup_outcome.categories)
    summary.changed_tags.update(cleanup_outcome.tags)
    summary.markets_deleted = cleanup_outcome.deleted_rows
    if cleanup_outcome.category_counts:
        _record_retention_metrics(cleanup_outcome.category_counts, cleanup_outcome.dry_run)


def _invalidate_cache_tags(redis_client: Redis | None, summary: SyncSummary) -> CacheInvalidationReport:
    report = CacheInvalidationReport()
    if redis_client is None:
        return report

    def _invalidate(tag: str) -> None:
        removed = shared_cache.invalidate_tag(redis_client, tag)
        report.record(tag, len(removed))

    if summary.changed_events or summary.changed_categories or summary.changed_tags:
        _invalidate("markets:list")
        _invalidate("category:trending")
        _invalidate("markets:suggest")
    if summary.stats_dirty and summary.changed_events:
        _invalidate("markets:stats")
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
    tagged = [slug for slug in summary.changed_tags if slug]
    for tag_slug in tagged:
        _invalidate(f"tag:{tag_slug}")
    if tagged:
        CACHE_INVALIDATION_COUNTER.labels(type="tag").inc(len(tagged))
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
        return ResolutionOutcome()

    normalized_condition_id = condition_id.lower()
    outcome_count_hint = len(market.outcome_prices) if market.outcome_prices else None
    existing = shared_repository.get_resolution_by_condition_id(session, normalized_condition_id)
    now = datetime.now(UTC)

    if not _should_refresh_resolution(existing, now):
        return ResolutionOutcome()

    summary = _fetch_resolution_snapshot(normalized_condition_id, market, outcome_count_hint)
    if summary is None:
        return ResolutionOutcome()

    checked_at_dt = _parse_checked_at(summary.get("checkedAt"), now)
    record_payload = _build_resolution_record(summary, market, checked_at_dt)
    record_payload["condition_id"] = normalized_condition_id

    shared_repository.upsert_resolution(session, record_payload)
    cache_payload = {
        **record_payload,
        "checkedAt": checked_at_dt.isoformat(),
    }
    block_ts = cache_payload.get("block_timestamp")
    if isinstance(block_ts, datetime):
        cache_payload["block_timestamp"] = block_ts.isoformat()
    changed = True

    log_event(
        logger,
        logging.INFO if record_payload["resolved"] else logging.DEBUG,
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
    changed = True

    if record_payload["resolved"]:
        db_market.status = "settled"
        if getattr(db_market, "closed", None) is not True:
            db_market.closed = True
        db_market.resolved_at = checked_at_dt
        log_event(
            logger,
            logging.INFO,
            event="worker.resolution.detected",
            message="polymarket resolution detected",
            condition_id=normalized_condition_id,
            winners=record_payload["winners"],
            block_number=record_payload["block_number"],
        )
    else:
        db_market.resolved_at = None
    return ResolutionOutcome(
        changed=changed,
        condition_id=normalized_condition_id,
        cache_payload=cache_payload if changed else None,
    )


def sync_market(session: Session, market: MarketPayload):
    """Upsert a market row using `event_id` as the natural key."""
    payload = market.model_dump()
    if payload.get("closed") is None:
        payload["closed"] = False
    condition_id = payload.get("condition_id")
    if isinstance(condition_id, str):
        payload["condition_id"] = condition_id.lower()

    existing = shared_repository.get_market_by_event_id(session, market.event_id)
    db_market = existing
    market_changed = False
    market_created = False
    market_updated = False
    incoming_updated_at = getattr(market, "source_updated_at", None)
    incoming_hash = getattr(market, "content_hash", None)

    if existing is None:
        db_market = shared_repository.upsert_market(session, payload)
        market_changed = True
        market_created = True
        log_event(
            logger,
            logging.INFO,
            event="worker.market.created",
            message="market created from polymarket feed",
            event_id=market.event_id,
            status=payload.get("status"),
            category=payload.get("category"),
        )
    else:
        match, match_reason = _markets_match(existing, incoming_updated_at, incoming_hash)
        if match:
            log_event(
                logger,
                logging.DEBUG,
                event="worker.market.skip_update",
                message="skipping market update (no changes detected)",
                event_id=market.event_id,
                reason=match_reason,
            )
        else:
            db_market = shared_repository.upsert_market(session, payload)
            market_changed = True
            market_updated = True
            log_event(
                logger,
                logging.INFO,
                event="worker.market.updated",
                message="market updated from polymarket feed",
                event_id=market.event_id,
                status=payload.get("status"),
                category=payload.get("category"),
                match_reason=match_reason,
            )

    if market.rake_bps is not None and db_market is not None:
        db_market.rake_bps = market.rake_bps
    resolution_outcome = _apply_resolution(session, db_market, market)
    session.flush()
    category_slug = _slugify_token(getattr(db_market, "category", None))
    tag_values = getattr(db_market, "tags", None) or []
    tag_slugs = [_slugify_token(tag) for tag in tag_values if isinstance(tag, str)]
    return db_market, SyncOutcome(
        market_changed=market_changed,
        resolution_changed=resolution_outcome.changed,
        category_slug=category_slug,
        tag_slugs=[slug for slug in tag_slugs if slug],
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
        shared_models.Market.tags,
        shared_models.Market.resolved_at,
    ).where(shared_models.Market.resolved_at.isnot(None), shared_models.Market.resolved_at < cutoff)
    records = session.execute(stmt).all()

    if not records:
        return CleanupOutcome(
            set(),
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
    tags: set[str] = set()
    category_counts: dict[str, int] = {}

    for row in records:
        resolved_at = _as_utc(row.resolved_at)
        if resolved_at is None or resolved_at > cutoff:
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
        if isinstance(row.tags, list):
            for tag in row.tags:
                slug = _slugify_token(tag)
                if slug:
                    tags.add(slug)

    eligible = len(ids_to_delete)
    if eligible == 0:
        return CleanupOutcome(
            event_ids,
            condition_ids,
            categories,
            tags,
            deleted_rows=0,
            eligible_rows=0,
            dry_run=dry_run,
            category_counts=category_counts,
        )

    if not dry_run:
        (
            session.query(shared_models.Market)
            .where(shared_models.Market.id.in_(ids_to_delete))
            .delete(synchronize_session=False)
        )
    _record_retention_metrics(category_counts, dry_run)
    log_event(
        logger,
        logging.INFO,
        event="worker.retention.cleanup",
        message="evaluated resolved markets for retention",
        eligible=eligible,
        deleted=0 if dry_run else eligible,
        dry_run=dry_run,
        cutoff=cutoff.isoformat(),
    )
    return CleanupOutcome(
        event_ids,
        condition_ids,
        categories,
        tags,
        deleted_rows=0 if dry_run else eligible,
        eligible_rows=eligible,
        dry_run=dry_run,
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
        logging.INFO,
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
                logging.INFO,
                event="worker.schema.cache_reset",
                message="invalidated schema-tagged cache entries",
                tag=tag,
                keys=len(invalidated),
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
            logging.INFO,
            event="worker.heartbeat.published",
            message="published worker heartbeat",
            markets_processed=payload["markets_processed"],
            markets_changed=payload["markets_changed"],
            resolutions_changed=payload["resolutions_changed"],
            latency_ms=payload["latency_ms"],
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
        "tags_changed": 0,
        "latency_ms": rounded_latency,
        "markets_created": 0,
        "markets_updated": 0,
        "markets_deleted": 0,
        "summaries_enqueued": 0,
        "proofs_generated": 0,
        "cache_invalidations": 0,
    }


def process_once(redis_client: Redis | None = None) -> dict[str, float | int]:
    """Fetch markets, persist them, and emit a heartbeat once."""

    schema_state = _ensure_schema()
    try:
        markets, latency_ms = fetch_markets_from_polymarket()
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
    try:
        with session_scope() as session:
            if markets:
                summary = _collect_market_changes(session, markets, redis_client)
            _apply_retention_cleanup(session, summary)
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

    log_event(
        logger,
        logging.INFO,
        event="worker.sync.summary",
        message="completed market sync",
        markets_processed=len(markets),
        markets_created=summary.markets_created,
        markets_updated=summary.markets_updated,
        markets_deleted=summary.markets_deleted,
        resolutions_changed=len(summary.changed_conditions),
        categories_changed=len(summary.changed_categories),
        tags_changed=len(summary.changed_tags),
        summaries_enqueued=summary.summaries_enqueued,
        proofs_generated=summary.proofs_generated,
        latency_ms=round(latency_ms, 2),
        cache_invalidations=cache_report.total,
    )

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
        return False
    normalized_condition = condition_id or market_snapshot.get("condition_id")
    if not normalized_condition:
        return False
    request = SettlementProofRequest(
        event_id=str(market_snapshot.get("event_id") or "unknown"),
        condition_id=str(normalized_condition).lower(),
        total_pool=_derive_total_pool_value(market_payload),
        winning_pool=_derive_winning_pool_value(market_payload),
        outcome_hash=compute_outcome_hash(
            str(market_snapshot.get("event_id") or "unknown"),
            normalized_condition,
            market_payload.outcomes or [],
        ),
        market_address=_normalize_market_address(market_snapshot.get("market_address")),
        circuit_version=1,
        metadata=_build_proof_metadata(market_payload),
    )
    try:
        response = PROVER_CLIENT.generate_settlement_proof(request)
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
    cache_key = proof_receipt_cache_key(normalized_condition)
    if redis_client is not None:
        shared_cache.set_json(
            redis_client,
            cache_key,
            response.to_json(),
            settings.proof_cache_ttl_seconds,
        )
    log_event(
        logger,
        logging.INFO,
        event="worker.proof.generated",
        message="cached settlement proof receipt",
        event_id=market_snapshot.get("event_id"),
        condition_id=normalized_condition,
        prover_version=response.prover_version,
        nonce=response.request_nonce,
    )
    return True


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
    shared_cache.set_json(redis_client, cache_key, payload, settings.markets_cache_ttl_seconds)
    schema_tag = shared_cache.get_schema_tag(redis_client, settings.schema_version_key)
    shared_cache.add_tag(redis_client, schema_tag, cache_key)
    shared_cache.add_tag(redis_client, "markets:list", cache_key)
    if isinstance(payload, list):
        event_tags = [
            f"market:{item.get('event_id')}" for item in payload if isinstance(item, dict) and item.get("event_id")
        ]
        shared_cache.add_tags(redis_client, event_tags, cache_key)
    log_event(
        logger,
        logging.INFO,
        event="worker.cache.primed",
        message="primed homepage markets cache",
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
    summary: dict[str, Any] = {"categories_primed": 0, "tags_primed": 0, "suggestions_primed": 0, "suggestion_ttls": {}}
    if redis_client is None or not settings.api_base_url:
        return summary
    if not settings.featured_categories and not settings.featured_tags and not settings.featured_suggest_queries:
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
        for tag in settings.featured_tags:
            slug = quote_plus(tag)
            params = {"limit": settings.tag_cache_limit}
            try:
                response = client.get(f"{base_url}/tags/{slug}", params=params)
                if response.is_success:
                    summary["tags_primed"] += 1
            except Exception as exc:
                log_event(
                    logger,
                    logging.WARNING,
                    event="worker.cache.featured_tag_failed",
                    message="failed to prime tag cache",
                    tag=tag,
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
        logging.INFO,
        event="worker.cache.featured",
        message="primed featured caches",
        categories=settings.featured_categories,
        tags=settings.featured_tags,
        suggest_queries=settings.featured_suggest_queries,
        categories_primed=summary["categories_primed"],
        tags_primed=summary["tags_primed"],
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
        "tags_changed": sync_stats.get("tags_changed", 0),
        "latency_ms": sync_stats.get("latency_ms"),
        "prime": prime_stats,
    }
    shared_cache.set_json(redis_client, settings.batch_stats_key, payload, settings.batch_stats_ttl_seconds)
    log_event(
        logger,
        logging.INFO,
        event="worker.batch_stats.published",
        message="recorded worker batch stats",
        markets_processed=payload["markets_processed"],
        markets_changed=payload["markets_changed"],
        categories_changed=payload["categories_changed"],
        tags_changed=payload["tags_changed"],
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
