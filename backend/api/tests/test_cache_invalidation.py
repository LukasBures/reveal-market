from __future__ import annotations

import app.main as api_main
from app import models
from shared.cache_keys import markets_list_cache_key, suggest_cache_key


def _create_market(idx: int) -> models.Market:
    return models.Market(
        event_id=f"evt-cache-{idx}",
        title=f"Cache Market {idx}",
        category="sports",
        oracle="0xcache",
        status="commit",
    )


def test_post_market_invalidates_cached_list(client, db_session):
    db_session.add(_create_market(1))
    db_session.commit()

    cache_key = markets_list_cache_key(None, None, None, None, 10, 0)
    first = client.get("/markets", params={"limit": 10})
    assert first.status_code == 200
    assert cache_key in api_main.cache_client.store

    payload = {
        "event_id": "evt-cache-new",
        "title": "New Market",
        "category": "sports",
        "oracle": "0xcache",
        "status": "commit",
    }
    response = client.post("/markets", json=payload)
    assert response.status_code == 201

    assert cache_key not in api_main.cache_client.store


def test_patch_market_invalidates_detail_and_suggest_cache(client, db_session):
    market = _create_market(2)
    db_session.add(market)
    db_session.commit()

    detail = client.get(f"/markets/{market.event_id}")
    assert detail.status_code == 200
    detail_key = api_main._market_detail_cache_key(market.event_id)
    assert detail_key in api_main.cache_client.store

    suggest = client.get("/markets/suggest", params={"q": "Cache", "limit": 5})
    assert suggest.status_code == 200
    suggestion_key = suggest_cache_key("Cache", 5)
    assert suggestion_key in api_main.cache_client.store

    patch = client.patch(f"/markets/{market.event_id}", json={"title": "Retitled"})
    assert patch.status_code == 200

    assert detail_key not in api_main.cache_client.store
    # invalidate_tag removes the suggestion key and the tag set.
    assert suggestion_key not in api_main.cache_client.store
