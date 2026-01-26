from __future__ import annotations

import app.server as api_main
from app import models


def _disable_cache(monkeypatch):
    monkeypatch.setattr(api_main, "cache_client", None, raising=False)
    monkeypatch.setattr("app.runtime.cache_client", None, raising=False)

    async def _no_cache():
        return None

    monkeypatch.setattr(api_main, "get_cache_client", _no_cache, raising=False)


def test_markets_endpoint_bypasses_cache_when_unavailable(client, db_session, monkeypatch):
    _disable_cache(monkeypatch)
    market = models.Market(
        event_id="evt-nocache",
        title="Cacheless Market",
        category="sports",
        oracle="0xabc",
        status="commit",
    )
    db_session.add(market)
    db_session.commit()

    response = client.get("/events", params={"limit": 5})
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload[0]["event_id"] == "evt-nocache"


def test_market_stats_bypasses_cache_when_unavailable(client, monkeypatch):
    _disable_cache(monkeypatch)
    response = client.get("/events/stats")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
