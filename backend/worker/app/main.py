"""Worker entrypoint that periodically syncs markets from Polymarket into the local database."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator, List

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from shared import repository as shared_repository

from .config import get_settings
from .polymarket import MarketPayload, PolymarketClient

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


def fetch_markets_from_polymarket() -> List[MarketPayload]:
    """Pull the latest markets from Polymarket using the shared client."""
    markets = polymarket_client.fetch_markets(
        page_size=settings.polymarket_page_size,
        max_pages=settings.polymarket_max_pages,
    )
    if not markets:
        logger.debug("no markets returned from polymarket feed")
    return markets


def sync_market(session: Session, market: MarketPayload) -> None:
    """Upsert a market row using `event_id` as the natural key."""
    shared_repository.upsert_market(session, market.model_dump())
    session.flush()


def _calculate_sleep(start_time: float) -> float:
    """Determine how long the worker should sleep to honour the poll interval."""
    elapsed = time.time() - start_time
    return max(settings.poll_interval_seconds - elapsed, 5)


def run_worker() -> None:
    """Main polling loop that downloads markets and writes them into the database."""
    from shared import models as shared_models

    shared_models.Base.metadata.create_all(bind=engine)
    logger.info("starting reveal-market sync worker (interval=%ss)", settings.poll_interval_seconds)
    while True:
        loop_start = time.time()
        markets = fetch_markets_from_polymarket()
        if markets:
            logger.info("synchronising %s markets", len(markets))
            try:
                with session_scope() as session:
                    for market in markets:
                        sync_market(session, market)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("failed to synchronise markets: %s", exc)

        time.sleep(_calculate_sleep(loop_start))


def main() -> None:  # pragma: no cover - CLI bootstrap
    """CLI entrypoint used by Docker/Procfile executions."""
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
