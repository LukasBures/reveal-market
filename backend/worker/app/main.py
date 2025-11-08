"""Worker entrypoint that periodically syncs markets from Polymarket into the local database."""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, List, Optional

from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from shared import cache as shared_cache
from shared import repository as shared_repository
from shared.logging import log_event
from shared.migrations import run_migrations as apply_migrations

from .config import get_settings
from .logging_config import setup_logging
from .onchain import maybe_create_onchain_market
from .polymarket import MarketPayload, PolymarketClient
from shared.onchain import ConditionalTokensClient

setup_logging("reveal_market.worker")
logger = logging.getLogger("reveal_market.worker")

settings = get_settings()

_schema_checked = False

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


def _ensure_schema() -> None:
    """Apply database migrations once per worker lifecycle if configured."""

    global _schema_checked
    if _schema_checked or not settings.run_migrations_on_startup:
        return
    apply_migrations(settings.database_url)
    _schema_checked = True


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


def _apply_resolution(session: Session, db_market, market: MarketPayload) -> None:
    client = conditional_tokens_client
    condition_id = market.condition_id
    if client is None or not isinstance(condition_id, str) or not condition_id.startswith("0x"):
        return

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
        return

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
        return

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

    if record_payload["resolved"]:
        db_market.status = "settled"
        if getattr(db_market, "closed", None) is not True:
            db_market.closed = True
        log_event(
            logger,
            logging.INFO,
            event="worker.resolution.detected",
            message="polymarket resolution detected",
            condition_id=normalized_condition_id,
            winners=record_payload["winners"],
            block_number=record_payload["block_number"],
        )


def sync_market(session: Session, market: MarketPayload):
    """Upsert a market row using `event_id` as the natural key."""
    payload = market.model_dump()
    if payload.get("closed") is None:
        payload["closed"] = False
    condition_id = payload.get("condition_id")
    if isinstance(condition_id, str):
        payload["condition_id"] = condition_id.lower()
    db_market = shared_repository.upsert_market(session, payload)
    if market.rake_bps is not None:
        setattr(db_market, "rake_bps", market.rake_bps)
    _apply_resolution(session, db_market, market)
    session.flush()
    return db_market


def _calculate_sleep(start_time: float) -> float:
    """Determine how long the worker should sleep to honour the poll interval."""
    elapsed = time.time() - start_time
    return max(settings.poll_interval_seconds - elapsed, 5)


def publish_heartbeat(redis_client: Redis | None, markets_processed: int, latency_ms: float) -> None:
    """Update a Redis key so external monitors can assert liveness."""

    if redis_client is None:
        return
    payload = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "markets_processed": markets_processed,
        "latency_ms": round(latency_ms, 2),
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
            markets_processed=markets_processed,
            latency_ms=round(latency_ms, 2),
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
        process_once(redis_client)
        time.sleep(_calculate_sleep(loop_start))


def process_once(redis_client: Redis | None = None) -> dict[str, float | int]:
    """Fetch markets, persist them, and emit a heartbeat once."""

    _ensure_schema()
    markets, latency_ms = fetch_markets_from_polymarket()
    if markets:
        log_event(
            logger,
            logging.INFO,
            event="worker.persist.batch",
            message="synchronising markets into database",
            markets_processed=len(markets),
        )
        try:
            with session_scope() as session:
                for market in markets:
                    db_market = sync_market(session, market)
                    maybe_create_onchain_market(settings, db_market, session)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception(
                "failed to synchronise markets",
                extra={"event": "worker.persist.error", "error": str(exc)},
            )
    publish_heartbeat(redis_client, len(markets), latency_ms)
    if redis_client is not None:
        shared_cache.invalidate_tag(redis_client, "markets:list")
        shared_cache.invalidate_tag(redis_client, "markets:stats")
        seen_events: set[str] = set()
        seen_conditions: set[str] = set()
        for market in markets:
            if market.event_id and market.event_id not in seen_events:
                shared_cache.invalidate_tag(redis_client, f"market:{market.event_id}")
                seen_events.add(market.event_id)
            if market.condition_id:
                condition_id = market.condition_id.lower()
                if condition_id not in seen_conditions:
                    shared_cache.invalidate_tag(redis_client, f"resolution:{condition_id}")
                    seen_conditions.add(condition_id)
    log_event(
        logger,
        logging.DEBUG,
        event="worker.cache.invalidate",
        message="invalidated markets cache",
        markets_processed=len(markets),
        duration_ms=round(latency_ms, 2),
    )
    return {"markets_processed": len(markets), "latency_ms": round(latency_ms, 2)}


def main() -> None:  # pragma: no cover - CLI bootstrap
    """CLI entrypoint used by Docker/Procfile executions."""
    try:
        run_worker()
    except KeyboardInterrupt:  # pragma: no cover - graceful shutdown
        logger.info("worker interrupted, shutting down")


if __name__ == "__main__":
    main()
