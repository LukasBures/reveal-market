from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator, List

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

logger = logging.getLogger("reveal_market.worker")

settings = get_settings()

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
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def fetch_markets_from_polymarket() -> List[dict[str, Any]]:
    try:
        with httpx.Client(timeout=settings.polymarket_timeout_seconds) as client:
            response = client.get(settings.polymarket_api_base)
            response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # pragma: no cover - logged for observability
        logger.error("failed to fetch markets from polymarket: %s", exc)
        return []

    items = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        logger.warning("unexpected payload structure from polymarket: %s", type(payload))
        return []
    return items


def sync_market(session: Session, market_data: dict[str, Any]) -> None:
    attributes = market_data.get("attributes", {})
    event_id = str(market_data.get("id"))
    title = attributes.get("title", f"Market {event_id}")
    category = attributes.get("category")
    metadata_uri = attributes.get("metadataUri")
    oracle = attributes.get("oracle", "polymarket")
    outcomes = attributes.get("outcomes")

    session.execute(
        """
        INSERT INTO markets (event_id, title, category, metadata_uri, oracle, status, outcomes, created_at, updated_at)
        VALUES (:event_id, :title, :category, :metadata_uri, :oracle, :status, :outcomes, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (event_id) DO UPDATE SET
            title = excluded.title,
            category = excluded.category,
            metadata_uri = excluded.metadata_uri,
            oracle = excluded.oracle,
            status = excluded.status,
            outcomes = excluded.outcomes,
            updated_at = CURRENT_TIMESTAMP
        """,
        {
            "event_id": event_id,
            "title": title,
            "category": category,
            "metadata_uri": metadata_uri,
            "oracle": oracle,
            "status": attributes.get("status", "commit"),
            "outcomes": outcomes,
        },
    )


def _calculate_sleep(start_time: float) -> float:
    elapsed = time.time() - start_time
    return max(settings.poll_interval_seconds - elapsed, 5)


def run_worker() -> None:
    logger.info("starting reveal-market sync worker (interval=%ss)", settings.poll_interval_seconds)
    while True:
        loop_start = time.time()
        markets = fetch_markets_from_polymarket()
        if markets:
            logger.info("synchronising %s markets", len(markets))
            try:
                with session_scope() as session:
                    for market_data in markets:
                        sync_market(session, market_data)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("failed to synchronise markets: %s", exc)
        else:
            logger.debug("no markets retrieved from polymarket feed")

        time.sleep(_calculate_sleep(loop_start))


def main() -> None:  # pragma: no cover - CLI bootstrap
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )
    try:
        run_worker()
    except KeyboardInterrupt:
        logger.info("worker interrupted, shutting down")


if __name__ == "__main__":
    main()
