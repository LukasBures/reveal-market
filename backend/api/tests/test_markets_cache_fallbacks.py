from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import app.server as api_main
from app import models
from app.services import markets as market_service

_FUTURE = datetime.now(tz=UTC) + timedelta(hours=12)


def _make_market(event_id: str):
    return models.Market(
        event_id=event_id,
        title="Market",
        oracle="0xabc",
        status=models.MarketStatusEnum.COMMIT.value,
        created_at=datetime.now(UTC),
        closes_at=_FUTURE,
    )


def test_hydrate_markets_cache_skips_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr(api_main, "cache_client", None, raising=False)

    async def _no_cache():
        return None

    monkeypatch.setattr("app.services.cache_client.get_cache_client", _no_cache, raising=False)
    summary = asyncio.run(api_main.hydrate_markets_cache(source="test"))
    assert summary["status"] == "skipped"
    assert summary["reason"] == "redis_unavailable"


def test_markets_endpoint_serves_db_when_cache_missing(client, db_session, monkeypatch):
    monkeypatch.setattr(api_main, "cache_client", None, raising=False)

    async def _no_cache():
        return None

    monkeypatch.setattr("app.runtime.cache_client", None, raising=False)
    monkeypatch.setattr("app.server.cache_client", None, raising=False)
    monkeypatch.setattr("app.services.cache_client.get_cache_client", _no_cache, raising=False)

    market = _make_market("evt-nocache")
    db_session.add(market)
    db_session.commit()

    resp = client.get("/events", params={"limit": 1})
    assert resp.status_code == 200
    assert resp.json()[0]["event_id"] == "evt-nocache"


def test_expand_event_groups_loads_events_sequentially(monkeypatch):
    active = 0
    max_active = 0

    async def _fake_load(*_args, **_kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        active -= 1
        return []

    monkeypatch.setattr(market_service, "_load_group_markets_for_event", _fake_load)
    events = [SimpleNamespace(markets=[]) for _ in range(3)]

    result = asyncio.run(
        market_service.expand_event_groups_for_list(
            object(),
            events,
            status=None,
            category=None,
            oracle=None,
            featured=None,
            closes_after=None,
            closes_before=None,
        )
    )

    assert result == events
    assert max_active == 1
