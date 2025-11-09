from __future__ import annotations

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

    response = client.get("/markets")
    assert response.status_code == 200

    cache_key = markets_list_cache_key(
        None,
        None,
        None,
        None,
        api_main.settings.default_page_size,
        0,
    )
    cache_store = getattr(api_main.cache_client, "store", None)
    assert cache_store is not None and cache_key in cache_store

    def fail(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("Database should not be queried on cache hit")

    monkeypatch.setattr(crud, "get_markets", fail)

    cached_response = client.get("/markets")
    assert cached_response.status_code == 200


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
