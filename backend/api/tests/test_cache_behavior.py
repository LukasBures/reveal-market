from __future__ import annotations

import json
import time

import app.main as api_main
from app import crud, models
from shared.cache_keys import markets_list_cache_key


def test_markets_endpoint_uses_cache(client, db_session, monkeypatch):
    market = models.Market(
        event_id="evt-cache",
        title="Cache Test",
        category="sports",
        oracle="0xabc",
        status="commit",
    )
    db_session.add(market)
    db_session.commit()

    response = client.get("/markets", params={"limit": 10})
    assert response.status_code == 200

    cache_key = markets_list_cache_key(None, None, None, None, 10, 0)
    cache_store = getattr(api_main.cache_client, "store", None)
    assert cache_store is not None and cache_key in cache_store

    def fail(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("Database should not be queried on cache hit")

    monkeypatch.setattr(crud, "get_markets", fail)

    cached_response = client.get("/markets", params={"limit": 10})
    assert cached_response.status_code == 200


def test_market_cache_stores_event_ids_and_records(client, db_session):
    market = models.Market(
        event_id="evt-cache-trim",
        title="Trim Test",
        category="sports",
        oracle="0xabc",
        status="commit",
        extra_data={"gamma": {"id": "evt-cache-trim"}, "description": "Lightweight"},
    )
    db_session.add(market)
    db_session.commit()

    response = client.get("/markets", params={"limit": 5})
    assert response.status_code == 200

    cache_key = markets_list_cache_key(None, None, None, None, 5, 0)
    cache_store = getattr(api_main.cache_client, "store", {})
    assert cache_key in cache_store
    cached_payload = json.loads(cache_store[cache_key])
    assert cached_payload["event_ids"] == ["evt-cache-trim"]
    record_key = "market:evt-cache-trim"
    assert record_key in cache_store
    record = json.loads(cache_store[record_key])
    assert record["event_id"] == "evt-cache-trim"
    assert record["extra_data"] == {"description": "Lightweight"}


def test_market_detail_cached(client, db_session, monkeypatch):
    market = models.Market(
        event_id="evt-detail",
        title="Detail Test",
        category="news",
        oracle="0xdef",
        status="commit",
    )
    db_session.add(market)
    db_session.commit()

    first = client.get(f"/markets/{market.event_id}")
    assert first.status_code == 200

    cache_key = api_main._market_detail_cache_key(market.event_id)
    cache_store = getattr(api_main.cache_client, "store", None)
    assert cache_store is not None and cache_key in cache_store

    def fail(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("Database should not be queried on cache hit")

    monkeypatch.setattr(crud, "get_market_by_event_id", fail)
    second = client.get(f"/markets/{market.event_id}")
    assert second.status_code == 200


def test_hydrate_markets_cache_populates_from_db(client, db_session):
    first = models.Market(
        event_id="evt-hydrate-1", title="Hydrate Alpha", category="sports", oracle="0x1", status="commit"
    )
    second = models.Market(
        event_id="evt-hydrate-2", title="Hydrate Beta", category="crypto", oracle="0x2", status="commit"
    )
    db_session.add_all([first, second])
    db_session.commit()

    summary = api_main.hydrate_markets_cache(source="test", limit=5)
    assert summary["status"] == "hydrated"
    cache_key = summary["cache_key"]
    cache_store = getattr(api_main.cache_client, "store", {})
    assert cache_key in cache_store
    payload = json.loads(cache_store[cache_key])
    assert set(payload["event_ids"]) == {"evt-hydrate-1", "evt-hydrate-2"}
    for event_id in payload["event_ids"]:
        assert f"market:{event_id}" in cache_store


def test_cache_refresh_worker_disables_when_setting_false(monkeypatch):
    monkeypatch.setattr(api_main.settings, "cache_refresh_enabled", False, raising=False)
    stop_event = api_main._start_cache_refresh_worker()
    assert stop_event is None


def test_cache_refresh_worker_triggers_hydration(monkeypatch):
    calls: list[dict[str, int | None]] = []

    def fake_hydrate(*, source: str, limit: int | None = None):
        calls.append({"source": source, "limit": limit})
        return {"status": "hydrated", "limit": limit}

    monkeypatch.setattr(api_main.settings, "cache_refresh_enabled", True, raising=False)
    monkeypatch.setattr(api_main.settings, "cache_refresh_interval_seconds", 0.05, raising=False)
    monkeypatch.setattr(api_main.settings, "cache_refresh_limit", 7, raising=False)
    monkeypatch.setattr(api_main, "hydrate_markets_cache", fake_hydrate, raising=False)

    stop_event = api_main._start_cache_refresh_worker()
    assert stop_event is not None
    try:
        time.sleep(0.12)
    finally:
        stop_event.set()

    assert calls
    assert calls[0]["source"] == "refresh"
    assert calls[0]["limit"] == 7
