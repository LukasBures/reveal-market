"""Worker entrypoint that periodically syncs markets from Polymarket into the local database."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Iterator, List

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from redis import Redis
from shared import cache as shared_cache
from shared import repository as shared_repository
from shared.logging import configure_json_logging, log_event

from .config import get_settings
from .polymarket import MarketPayload, PolymarketClient

configure_json_logging("reveal_market.worker")
logger = logging.getLogger("reveal_market.worker")

settings = get_settings()

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
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

polymarket_client = PolymarketClient(
    settings.polymarket_api_base,
    timeout=settings.polymarket_timeout_seconds,
)

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
    )

    markets = polymarket_client.fetch_markets(
        page_size=settings.polymarket_page_size,
        max_pages=settings.polymarket_max_pages,
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


def sync_market(session: Session, market: MarketPayload) -> None:
    """Upsert a market row using `event_id` as the natural key."""
    shared_repository.upsert_market(session, market.model_dump())
    session.flush()


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
                    sync_market(session, market)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception(
                "failed to synchronise markets",
                extra={"event": "worker.persist.error", "error": str(exc)},
            )
    publish_heartbeat(redis_client, len(markets), latency_ms)
    shared_cache.delete_prefix(redis_client, "markets:list")
    shared_cache.delete(redis_client, "markets:stats")
    for market in markets:
        shared_cache.delete(redis_client, f"markets:detail:{market.event_id}")
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
    except KeyboardInterrupt:
        logger.info("worker interrupted, shutting down")


if __name__ == "__main__":
    main()
