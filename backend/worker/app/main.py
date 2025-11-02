import time
from typing import Any

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from .config import settings

engine = create_engine(settings.database_url, future=True)


def fetch_markets_from_polymarket() -> list[dict[str, Any]]:
    try:
        response = httpx.get(settings.polymarket_api_base, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # pragma: no cover - logged in worker
        print(f"[worker] failed to fetch markets: {exc}")
        return []

    items = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
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


def run_worker() -> None:
    print("[worker] starting reveal-market sync worker")
    while True:
        start = time.time()
        markets = fetch_markets_from_polymarket()
        if markets:
            with engine.begin() as connection:
                session = Session(bind=connection)
                for market_data in markets:
                    sync_market(session, market_data)
                session.flush()
                session.close()
        elapsed = time.time() - start
        sleep_for = max(settings.poll_interval_seconds - elapsed, 5)
        time.sleep(sleep_for)


if __name__ == "__main__":  # pragma: no cover - worker entrypoint
    run_worker()
