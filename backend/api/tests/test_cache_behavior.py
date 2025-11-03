from __future__ import annotations

import logging

import app.main as api_main
from app import crud, models


def test_markets_endpoint_uses_cache(client, db_session, monkeypatch, caplog):
    market = models.Market(
        event_id="evt-cache",
        title="Cache Test",
        category="sports",
        oracle="0xabc",
        status="commit",
    )
    db_session.add(market)
    db_session.commit()

    caplog.set_level(logging.DEBUG, logger="reveal_market.api")

    response = client.get("/markets")
    assert response.status_code == 200

    cache_key = api_main._markets_list_cache_key(
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

    cache_logs = [record for record in caplog.records if getattr(record, "event", "").startswith("markets.list")]
    assert any(record.event == "markets.list.cache_miss" for record in cache_logs)
    assert any(record.event == "markets.list.cache_hit" for record in cache_logs)
    assert any(record.event == "markets.list.cache_miss" and record.cache_hit is False for record in cache_logs)
    assert any(record.event == "markets.list.cache_hit" and record.cache_hit is True for record in cache_logs)


def test_market_detail_cached(client, db_session, monkeypatch, caplog):
    market = models.Market(
        event_id="evt-detail",
        title="Detail Test",
        category="news",
        oracle="0xdef",
        status="commit",
    )
    db_session.add(market)
    db_session.commit()

    caplog.set_level(logging.DEBUG, logger="reveal_market.api")

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

    detail_logs = [record for record in caplog.records if getattr(record, "event", "").startswith("markets.detail")]
    assert any(record.event == "markets.detail.cache_miss" for record in detail_logs)
    assert any(record.event == "markets.detail.cache_hit" for record in detail_logs)
    assert any(record.event == "markets.detail.cache_miss" and record.cache_hit is False for record in detail_logs)
    assert any(record.event == "markets.detail.cache_hit" and record.cache_hit is True for record in detail_logs)
