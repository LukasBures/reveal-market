from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import app.server as api_main
import pytest
from app import models


def _make_market(event_id: str):
    return models.Market(
        event_id=event_id,
        title="Market",
        oracle="0xabc",
        status=models.MarketStatusEnum.COMMIT.value,
        created_at=datetime.now(UTC),
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

    resp = client.get("/markets", params={"limit": 1})
    assert resp.status_code == 200
    assert resp.json()[0]["event_id"] == "evt-nocache"
