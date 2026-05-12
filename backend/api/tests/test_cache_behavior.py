from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import app.server as api_main
from app import crud, models
from app.services import markets as market_svc
from app.services.markets import market_detail_cache_key
from shared import models as shared_models
from shared.cache_async import _json_loads_compressed
from shared.cache_keys import markets_list_cache_key
from sqlalchemy import select

_FUTURE = datetime.now(tz=UTC) + timedelta(hours=12)


def test_markets_endpoint_uses_cache(client, db_session, monkeypatch):
    market = models.Market(
        event_id="evt-cache",
        title="Cache Test",
        category="sports",
        oracle="0xabc",
        status="commit",
        closes_at=_FUTURE,
    )
    db_session.add(market)
    db_session.commit()

    response = client.get("/events", params={"limit": 10})
    assert response.status_code == 200

    cache_key = markets_list_cache_key(None, None, None, None, 10, 0, closes_within_hours=None)
    cache_store = getattr(api_main.cache_client, "store", None)
    assert cache_store is not None and cache_key in cache_store

    async def fail(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("Database should not be queried on cache hit")

    monkeypatch.setattr(crud, "get_markets", fail)

    cached_response = client.get("/events", params={"limit": 10})
    assert cached_response.status_code == 200


def test_market_cache_stores_event_ids_and_records(client, db_session):
    market = models.Market(
        event_id="evt-cache-trim",
        title="Trim Test",
        category="sports",
        oracle="0xabc",
        status="commit",
        closes_at=_FUTURE,
    )
    db_session.add(market)
    db_session.flush()
    market_id = db_session.execute(
        select(models.Market.id).where(models.Market.event_id == "evt-cache-trim")
    ).scalar_one()
    db_session.add(shared_models.MarketGammaMetadata(market_id=market_id, description="Lightweight"))
    db_session.commit()

    response = client.get("/events", params={"limit": 5})
    assert response.status_code == 200

    cache_key = markets_list_cache_key(None, None, None, None, 5, 0, closes_within_hours=None)
    cache_store = getattr(api_main.cache_client, "store", {})
    assert cache_key in cache_store
    cached_raw = _json_loads_compressed(cache_store[cache_key])
    # Support PER-wrapped payloads (envelope has _v/_t/_ttl) or plain payloads
    cached_payload = cached_raw.get("_v", cached_raw) if isinstance(cached_raw, dict) else cached_raw
    assert cached_payload["event_ids"] == ["evt-cache-trim"]
    record_key = "market:evt-cache-trim"
    assert record_key in cache_store
    record = _json_loads_compressed(cache_store[record_key])
    assert record["event_id"] == "evt-cache-trim"
    assert record["description"] == "Lightweight"


def test_slim_market_cache_hit_does_not_reenrich_from_db(client, db_session, monkeypatch):
    market = models.Market(
        event_id="evt-slim-cache",
        title="Slim Cache",
        category="sports",
        oracle="0xabc",
        status="commit",
        closes_at=_FUTURE,
    )
    db_session.add(market)
    db_session.commit()

    first = client.get("/events", params={"limit": 5, "view": "list"})
    assert first.status_code == 200

    async def fail(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("Slim cache hits should not re-enrich from the database")

    monkeypatch.setattr(market_svc, "enrich_market_models", fail)

    second = client.get("/events", params={"limit": 5, "view": "list"})
    assert second.status_code == 200
    assert second.json()[0]["event_id"] == "evt-slim-cache"


def test_market_detail_cached(client, db_session, monkeypatch):
    market = models.Market(
        event_id="evt-detail",
        title="Detail Test",
        category="news",
        oracle="0xdef",
        status="commit",
        closes_at=_FUTURE,
    )
    db_session.add(market)
    db_session.commit()

    first = client.get(f"/events/by-key/{market.event_id}")
    assert first.status_code == 200

    cache_key = market_detail_cache_key(market.event_id)
    cache_store = getattr(api_main.cache_client, "store", None)
    assert cache_store is not None and cache_key in cache_store

    async def fail(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("Database should not be queried on cache hit")

    monkeypatch.setattr(crud, "get_market_by_event_id", fail)
    second = client.get(f"/events/by-key/{market.event_id}")
    assert second.status_code == 200


def test_hydrate_markets_cache_populates_from_db(client, db_session):
    first = models.Market(
        event_id="evt-hydrate-1",
        title="Hydrate Alpha",
        category="sports",
        oracle="0x1",
        status="commit",
        closes_at=_FUTURE,
    )
    second = models.Market(
        event_id="evt-hydrate-2",
        title="Hydrate Beta",
        category="crypto",
        oracle="0x2",
        status="commit",
        closes_at=_FUTURE,
    )
    db_session.add_all([first, second])
    db_session.commit()

    summary = asyncio.run(api_main.hydrate_markets_cache(source="test", limit=5))
    assert summary["status"] == "hydrated"
    cache_key = summary["cache_key"]
    cache_store = getattr(api_main.cache_client, "store", {})
    assert cache_key in cache_store
    raw_payload = _json_loads_compressed(cache_store[cache_key])
    payload = raw_payload.get("_v", raw_payload) if isinstance(raw_payload, dict) else raw_payload
    assert set(payload["event_ids"]) == {"evt-hydrate-1", "evt-hydrate-2"}
    for event_id in payload["event_ids"]:
        assert f"market:{event_id}" in cache_store


def test_cache_refresh_worker_disables_when_setting_false(monkeypatch):
    monkeypatch.setattr(api_main.settings, "cache_refresh_enabled", False, raising=False)
    calls: list[dict[str, int | None]] = []

    async def fake_hydrate(**kwargs):
        calls.append(kwargs)
        return {"status": "skipped"}

    monkeypatch.setattr(api_main, "hydrate_markets_cache", fake_hydrate, raising=False)
    asyncio.run(api_main._cache_refresh_loop())
    assert calls == []


def test_cache_refresh_worker_triggers_hydration(monkeypatch):
    calls: list[dict[str, int | None]] = []

    class DummyCache:
        def __init__(self):
            self.store: dict[str, Any] = {}

        async def ping(self):
            return True

        async def get(self, key: str):
            return self.store.get(key)

        async def set(self, key: str, value: Any, ex: int | None = None, nx: bool | None = None):
            if nx and key in self.store:
                return False
            self.store[key] = value
            return True

        async def delete(self, *keys: str):
            for key in keys:
                self.store.pop(key, None)

        async def scan_iter(self, match: str):
            prefix = match[:-1] if match.endswith("*") else match
            for key in list(self.store.keys()):
                if key.startswith(prefix):
                    yield key

        async def sscan_iter(self, key: str, count: int | None = None):
            members = self.store.get(key)
            if isinstance(members, set):
                for member in members:
                    yield member

        async def sadd(self, key: str, value: str):
            self.store.setdefault(key, set()).add(value)

        async def smembers(self, key: str):
            members = self.store.get(key)
            if isinstance(members, set):
                return set(members)
            return set()

    cache = DummyCache()
    monkeypatch.setattr("app.runtime.cache_client", cache, raising=False)
    monkeypatch.setattr("app.server.cache_client", cache, raising=False)

    async def fake_hydrate(**kwargs):
        calls.append(kwargs)
        return {"status": "hydrated", **kwargs}

    monkeypatch.setattr(api_main.settings, "cache_refresh_enabled", True, raising=False)
    monkeypatch.setattr(api_main.settings, "cache_refresh_interval_seconds", 0.01, raising=False)
    monkeypatch.setattr(api_main.settings, "cache_refresh_limit", 7, raising=False)
    monkeypatch.setattr("app.tasks.hydrate_markets_cache", fake_hydrate, raising=False)
    monkeypatch.setattr(api_main, "hydrate_markets_cache", fake_hydrate, raising=False)

    async def _run_once():
        task = asyncio.create_task(api_main._cache_refresh_loop())
        await asyncio.sleep(0.02)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return

    asyncio.run(_run_once())

    assert calls
    assert calls[0]["source"] == "refresh"
    assert calls[0]["limit"] == 7
    assert calls[0]["order_by"] == api_main.settings.cache_hydrate_order_by
