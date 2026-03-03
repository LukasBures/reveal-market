from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import app.server as api_main
from app import models
from shared.cache_keys import markets_list_cache_key

_FUTURE = datetime.now(tz=UTC) + timedelta(hours=12)


def test_hydrator_writes_tagged_cache_and_respects_lock(client, db_session, monkeypatch):
    # seed markets
    for i in range(3):
        db_session.add(
            models.Market(
                event_id=f"evt-{i}",
                title=f"Market {i}",
                category="sports",
                oracle="0xabc",
                status="commit",
                closes_at=_FUTURE,
            )
        )
    db_session.commit()

    # first hydrate should populate cache
    summary = asyncio.run(api_main.hydrate_markets_cache(source="test", limit=2))
    assert summary["status"] == "hydrated"

    cache = asyncio.run(api_main.get_cache_client())
    cache_key = markets_list_cache_key(
        "active",
        None,
        None,
        None,
        2,
        0,
        order_by=api_main.settings.cache_hydrate_order_by,
        coalesce_groups=True,
        closes_within_hours=24,
    )
    assert summary["cache_key"] == cache_key
    payload = asyncio.run(cache.get(cache_key))
    assert payload is not None
    # second hydrate should detect lock and skip
    asyncio.run(cache.set("lock:markets_cache:hydrate", "1", ex=30, nx=True))
    skipped = asyncio.run(api_main.hydrate_markets_cache(source="test", limit=2))
    assert skipped["status"] == "skipped"
    assert skipped["reason"] == "hydrate_in_progress"
