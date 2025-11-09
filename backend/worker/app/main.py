"""Worker entrypoint that periodically syncs markets from Polymarket into the local database."""

from __future__ import annotations

import json
import logging
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Iterator, List, Optional
from urllib.parse import quote_plus

import httpx
from redis import Redis
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from shared import cache as shared_cache
from shared import repository as shared_repository
from shared import models as shared_models
from shared.logging import log_event
from shared.migrations import get_current_revision, run_migrations as apply_migrations
from shared.cache_keys import category_cache_key, markets_list_cache_key, resolution_cache_key, suggest_cache_key, tag_cache_key

try:
    from prometheus_client import Counter
except ImportError:  # pragma: no cover - optional dependency
    class Counter:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def labels(self, **kwargs):
            return self

        def inc(self, amount: float = 1.0) -> None:
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

from .config import get_settings
from .logging_config import setup_logging
from .onchain import maybe_create_onchain_market
from .polymarket import MarketPayload, PolymarketClient
from shared.onchain import ConditionalTokensClient

setup_logging("reveal_market.worker")
logger = logging.getLogger("reveal_market.worker")

settings = get_settings()

_schema_checked = False


@dataclass
class SchemaSyncResult:
    changed: bool = False
    previous_revision: Optional[str] = None
    current_revision: Optional[str] = None


@dataclass
class SyncOutcome:
    market_changed: bool
    resolution_changed: bool
    category_slug: Optional[str]
    tag_slugs: list[str]
    condition_id: Optional[str]
    resolution_cache_payload: Optional[dict[str, Any]]


@dataclass
class ResolutionOutcome:
    changed: bool = False
    condition_id: Optional[str] = None
    cache_payload: Optional[dict[str, Any]] = None


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


polymarket_client = PolymarketClient(
    settings.polymarket_api_base,
    timeout=settings.polymarket_timeout_seconds,
)


def _build_conditional_tokens_client() -> Optional[ConditionalTokensClient]:
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


conditional_tokens_client = _build_conditional_tokens_client()


def fetch_markets_from_polymarket() -> tuple[List[MarketPayload], float]:
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

    markets = polymarket_client.fetch_markets(
        page_size=settings.polymarket_page_size,
        max_pages=settings.polymarket_max_pages,
        order=settings.polymarket_order,
        ascending=settings.polymarket_sort_ascending,
        closed=settings.polymarket_closed_filter,
    )
    latency_ms = (time.perf_counter() - start) * 1000
    if markets:
        log_event(
            logger,
            logging.INFO,
            event="worker.fetch.success",
            message="retrieved markets from polymarket",
            count=len(markets),
            latency_ms=round(latency_ms, 2),
        )
    else:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.fetch.empty",
            message="no markets returned from polymarket feed",
            latency_ms=round(latency_ms, 2),
        )
    return markets, latency_ms


def _merge_extra_data(existing: Optional[dict], update: dict) -> dict:
    merged = dict(existing) if isinstance(existing, dict) else {}
    merged.update(update)
    return merged


def _slugify_token(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or None


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _record_retention_metrics(category_counts: dict[str, int], dry_run: bool) -> None:
    counter = RETENTION_SKIPPED_COUNTER if dry_run else RETENTION_DELETED_COUNTER
    for category, count in category_counts.items():
        label = category or "uncategorized"
        counter.labels(category=label).inc(count)


def _apply_resolution(session: Session, db_market, market: MarketPayload) -> ResolutionOutcome:
    client = conditional_tokens_client
    condition_id = market.condition_id
    if client is None or not isinstance(condition_id, str) or not condition_id.startswith("0x"):
        return ResolutionOutcome()

    normalized_condition_id = condition_id.lower()
    outcome_count_hint = len(market.outcome_prices) if market.outcome_prices else None
    existing = shared_repository.get_resolution_by_condition_id(session, normalized_condition_id)
    now = datetime.now(timezone.utc)
    refresh_due = existing is None

    if existing is not None:
        if not existing.resolved:
            refresh_due = True
        elif existing.checked_at is None:
            refresh_due = True
        else:
            refresh_due = (now - existing.checked_at).total_seconds() >= settings.resolution_refresh_interval_seconds

    if not refresh_due:
        return ResolutionOutcome()

    try:
        summary = client.resolution_summary(normalized_condition_id, market.outcomes or [], outcome_count_hint)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="worker.resolution.fetch_failed",
            message="failed to read conditional tokens resolution",
            condition_id=normalized_condition_id,
            error=str(exc),
        )
        return ResolutionOutcome()

    checked_at = summary.get("checkedAt")
    if isinstance(checked_at, datetime):
        checked_at_dt = checked_at
    elif isinstance(checked_at, str):
        try:
            checked_at_dt = datetime.fromisoformat(checked_at)
        except ValueError:
            checked_at_dt = now
    else:
        checked_at_dt = now

    record_payload = {
        "condition_id": normalized_condition_id,
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
        "checked_at": checked_at_dt,
    }

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
    incoming_updated_at = getattr(market, "source_updated_at", None)
    incoming_hash = getattr(market, "content_hash", None)

    if existing is None:
        db_market = shared_repository.upsert_market(session, payload)
        market_changed = True
    else:
        if _markets_match(existing, incoming_updated_at, incoming_hash):
            log_event(
                logger,
                logging.DEBUG,
                event="worker.market.skip_update",
                message="skipping market update (no changes detected)",
                event_id=market.event_id,
            )
        else:
            db_market = shared_repository.upsert_market(session, payload)
            market_changed = True

    if market.rake_bps is not None and db_market is not None:
        setattr(db_market, "rake_bps", market.rake_bps)
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
    )


def _markets_match(existing, source_updated_at: Optional[datetime], content_hash: Optional[str]) -> bool:
    if source_updated_at and getattr(existing, "source_updated_at", None) == source_updated_at:
        return True
    existing_hash = getattr(existing, "content_hash", None)
    if content_hash and existing_hash and existing_hash == content_hash:
        return True
    return False


def cleanup_resolved_markets(
    session: Session,
    *,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> CleanupOutcome:
    """Remove markets that have been resolved for longer than the configured retention."""

    reference_time = _as_utc(now) or datetime.now(timezone.utc)
    cutoff = reference_time - timedelta(seconds=settings.resolved_retention_seconds)
    stmt = select(
        shared_models.Market.id,
        shared_models.Market.event_id,
        shared_models.Market.condition_id,
        shared_models.Market.category,
        shared_models.Market.tags,
        shared_models.Market.resolved_at,
    ).where(shared_models.Market.resolved_at.isnot(None))
    records = session.execute(stmt).all()

    if not records:
        return CleanupOutcome(set(), set(), set(), set(), deleted_rows=0, eligible_rows=0, dry_run=dry_run, category_counts={})

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
        return CleanupOutcome(event_ids, condition_ids, categories, tags, deleted_rows=0, eligible_rows=0, dry_run=dry_run, category_counts=category_counts)

    if not dry_run:
        session.query(shared_models.Market).where(shared_models.Market.id.in_(ids_to_delete)).delete(synchronize_session=False)
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
    return max(settings.poll_interval_seconds - elapsed, 5)


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
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "markets_processed": stats.get("markets_processed", 0),
        "markets_changed": stats.get("markets_changed", 0),
        "resolutions_changed": stats.get("resolutions_changed", 0),
        "latency_ms": stats.get("latency_ms"),
    }
    try:
        redis_client.set(
            settings.heartbeat_key,
            json.dumps(payload),
            ex=settings.heartbeat_ttl_seconds,
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
    while True:
        loop_start = time.time()
        sync_stats = process_once(redis_client)
        prime_stats = prime_markets_cache(redis_client)
        featured_stats = prime_featured_views(redis_client)
        prime_stats.update(featured_stats)
        record_batch_stats(redis_client, sync_stats, prime_stats)
        time.sleep(_calculate_sleep(loop_start))


def process_once(redis_client: Redis | None = None) -> dict[str, float | int]:
    """Fetch markets, persist them, and emit a heartbeat once."""

    schema_state = _ensure_schema()
    markets, latency_ms = fetch_markets_from_polymarket()
    changed_events: set[str] = set()
    changed_conditions: set[str] = set()
    changed_categories: set[str] = set()
    changed_tags: set[str] = set()
    resolution_cache_updates: list[tuple[str, dict[str, Any]]] = []
    stats_dirty = False
    try:
        with session_scope() as session:
            if markets:
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
                        changed_events.add(db_market.event_id)
                        stats_dirty = True
                    if outcome.resolution_changed and outcome.condition_id:
                        changed_conditions.add(outcome.condition_id.lower())
                    if outcome.category_slug:
                        changed_categories.add(outcome.category_slug)
                    if outcome.tag_slugs:
                        changed_tags.update(outcome.tag_slugs)
                    if outcome.resolution_cache_payload and outcome.condition_id:
                        resolution_cache_updates.append((outcome.condition_id, outcome.resolution_cache_payload))
                    maybe_create_onchain_market(settings, db_market, session)
            cleanup_outcome = cleanup_resolved_markets(
                session,
                dry_run=settings.resolved_retention_dry_run,
            )
            if cleanup_outcome.events:
                changed_events.update(cleanup_outcome.events)
                stats_dirty = True
            changed_conditions.update(cleanup_outcome.conditions)
            changed_categories.update(cleanup_outcome.categories)
            changed_tags.update(cleanup_outcome.tags)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception(
            "failed to synchronise markets",
            extra={"event": "worker.persist.error", "error": str(exc)},
        )
    stats = {
        "markets_processed": len(markets),
        "markets_changed": len(changed_events),
        "resolutions_changed": len(changed_conditions),
        "categories_changed": len(changed_categories),
        "tags_changed": len(changed_tags),
        "latency_ms": round(latency_ms, 2),
    }
    publish_heartbeat(redis_client, stats)
    _propagate_schema_revision(redis_client, schema_state)
    if redis_client is not None and resolution_cache_updates:
        for condition_id, payload in resolution_cache_updates:
            shared_cache.set_json(
                redis_client,
                resolution_cache_key(condition_id),
                payload,
                settings.markets_cache_ttl_seconds,
            )
    if redis_client is not None:
        for event_id in changed_events:
            shared_cache.invalidate_tag(redis_client, f"market:{event_id}")
        if stats_dirty and changed_events:
            shared_cache.invalidate_tag(redis_client, "markets:stats")
        for condition_id in changed_conditions:
            shared_cache.invalidate_tag(redis_client, f"resolution:{condition_id}")
        if changed_events:
            shared_cache.invalidate_tag(redis_client, "markets:suggest")
        for category_slug in changed_categories:
            shared_cache.invalidate_tag(redis_client, f"category:{category_slug}")
        for tag_slug in changed_tags:
            shared_cache.invalidate_tag(redis_client, f"tag:{tag_slug}")
    log_event(
        logger,
        logging.DEBUG,
        event="worker.cache.invalidate",
        message="invalidated markets cache",
        markets_processed=len(markets),
        markets_changed=len(changed_events),
        resolutions_changed=len(changed_conditions),
        categories_changed=len(changed_categories),
        tags_changed=len(changed_tags),
        duration_ms=round(latency_ms, 2),
    )
    return stats


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
        event_tags = [f"market:{item.get('event_id')}" for item in payload if isinstance(item, dict) and item.get("event_id")]
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
    if (
        not settings.featured_categories
        and not settings.featured_tags
        and not settings.featured_suggest_queries
    ):
        return summary
    base_url = settings.api_base_url.rstrip("/")
    try:
        with httpx.Client(timeout=settings.cache_prime_timeout_seconds, transport=transport) as client:
            for category in settings.featured_categories:
                slug = quote_plus(category)
                params = {"limit": settings.category_cache_limit}
                response = client.get(f"{base_url}/categories/{slug}", params=params)
                if response.ok:
                    summary["categories_primed"] += 1
            for tag in settings.featured_tags:
                slug = quote_plus(tag)
                params = {"limit": settings.tag_cache_limit}
                response = client.get(f"{base_url}/tags/{slug}", params=params)
                if response.ok:
                    summary["tags_primed"] += 1
            for query in settings.featured_suggest_queries:
                params = {"q": query, "limit": settings.suggest_cache_limit}
                response = client.get(f"{base_url}/markets/suggest", params=params)
                if response.ok:
                    summary["suggestions_primed"] += 1
                    key = suggest_cache_key(query, settings.suggest_cache_limit)
                    ttl = redis_client.ttl(key)
                    if ttl is None or ttl < 0:
                        ttl = settings.markets_cache_ttl_seconds
                    summary["suggestion_ttls"][query] = ttl
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="worker.cache.featured_failed",
            message="failed to prime featured caches",
            error=str(exc),
        )
        return summary

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
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "markets_processed": sync_stats.get("markets_processed", 0),
        "markets_changed": sync_stats.get("markets_changed", 0),
        "resolutions_changed": sync_stats.get("resolutions_changed", 0),
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
