from __future__ import annotations

import app.main as api_main
from app import models
from shared.cache_keys import markets_list_cache_key


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
            )
        )
    db_session.commit()

    # first hydrate should populate cache
    summary = api_main.hydrate_markets_cache(source="test", limit=2)
    assert summary["status"] == "hydrated"

    cache = api_main.get_cache_client()
    cache_key = markets_list_cache_key(None, None, None, None, 2, 0)
    payload = cache.get(cache_key)
    assert payload is not None
    # second hydrate should detect lock and skip
    cache.set("lock:markets_cache:hydrate", "1", ex=30, nx=True)
    skipped = api_main.hydrate_markets_cache(source="test", limit=2)
    assert skipped["status"] == "skipped"
    assert skipped["reason"] == "hydrate_in_progress"
