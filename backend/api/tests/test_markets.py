from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import app.main as api_main

from app import models
from shared.cache_keys import category_cache_key, suggest_cache_key, tag_cache_key


def _make_market(
    event_id: str,
    title: str,
    *,
    category: str,
    oracle: str,
    status: str,
    rake_bps: int | None = None,
) -> models.Market:
    now = datetime.now(tz=timezone.utc)
    return models.Market(
        event_id=event_id,
        title=title,
        category=category,
        oracle=oracle,
        status=status,
        rake_bps=rake_bps,
        created_at=now,
        updated_at=now,
    )


def test_list_markets_supports_filters(client, db_session):
    db_session.add_all(
        [
            _make_market("evt-1", "Alpha Market", category="sports", oracle="0xaaa", status="commit"),
            _make_market("evt-2", "Beta Trade", category="crypto", oracle="0xbbb", status="settled"),
            _make_market("evt-3", "Gamma Alpha", category="sports", oracle="0xaaa", status="commit"),
        ]
    )
    db_session.commit()

    all_markets = client.get("/markets").json()
    assert {m["event_id"] for m in all_markets} == {"evt-1", "evt-2", "evt-3"}

    filtered_status = client.get("/markets", params={"status": "commit"}).json()
    assert {m["event_id"] for m in filtered_status} == {"evt-1", "evt-3"}

    filtered_category = client.get("/markets", params={"category": "crypto"}).json()
    assert [m["event_id"] for m in filtered_category] == ["evt-2"]

    filtered_oracle = client.get("/markets", params={"oracle": "0xaaa"}).json()
    assert {m["event_id"] for m in filtered_oracle} == {"evt-1", "evt-3"}

    filtered_search = client.get("/markets", params={"search": "Alpha"}).json()
    assert {m["event_id"] for m in filtered_search} == {"evt-1", "evt-3"}


def test_create_and_read_market(client):
    payload = {
        "event_id": "evt-100",
        "title": "New Market",
        "category": "sports",
        "oracle": "0xabc123",
        "status": "commit",
    }

    create_response = client.post("/markets", json=payload)
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["event_id"] == payload["event_id"]
    assert created["title"] == payload["title"]
    assert created["status"] == payload["status"]
    assert created["rake_bps"] is None

    read_response = client.get(f"/markets/{payload['event_id']}")
    assert read_response.status_code == 200
    retrieved = read_response.json()
    assert retrieved["event_id"] == payload["event_id"]
    assert retrieved["title"] == payload["title"]
    assert retrieved["rake_bps"] is None


def test_create_market_with_rake(client):
    payload = {
        "event_id": "evt-101",
        "title": "Custom Rake",
        "category": "sports",
        "oracle": "0xabc123",
        "status": "commit",
        "rake_bps": 75,
    }

    response = client.post("/markets", json=payload)
    assert response.status_code == 201
    created = response.json()
    assert created["rake_bps"] == 75

    fetched = client.get(f"/markets/{payload['event_id']}").json()
    assert fetched["rake_bps"] == 75


def test_patch_market_and_stats(client, db_session):
    market = _make_market("evt-200", "Patch Me", category="culture", oracle="0xccc", status="commit")
    db_session.add(market)
    db_session.commit()

    patch_payload = {
        "title": "Patched Title",
        "status": "settled",
        "extra_data": {"note": "updated"},
    }

    patch_response = client.patch(f"/markets/{market.event_id}", json=patch_payload)
    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["title"] == "Patched Title"
    assert patched["status"] == "settled"
    assert patched["extra_data"] == {"note": "updated"}
    assert patched["rake_bps"] is None

    stats_response = client.get("/markets/stats")
    assert stats_response.status_code == 200
    stats = {entry["status"]: entry["count"] for entry in stats_response.json()}
    assert stats.get("settled") == 1


def test_onchain_markets_unconfigured(client):
    response = client.get("/markets/onchain")
    assert response.status_code == 503


def test_onchain_markets_success(client, monkeypatch):
    async def fake_fetch(settings):
        return ["0x1111111111111111111111111111111111111111"]

    monkeypatch.setattr(api_main, "fetch_factory_markets", fake_fetch)
    monkeypatch.setattr(
        api_main,
        "get_settings",
        lambda: SimpleNamespace(factory_address="0x123", rpc_url="https://unit.test"),
    )

    response = client.get("/markets/onchain")
    assert response.status_code == 200
    assert response.json()["markets"] == ["0x1111111111111111111111111111111111111111"]


def test_resolution_endpoint_unconfigured(client):
    condition_id = "0x" + "a" * 64
    response = client.get(f"/resolution/{condition_id}")
    assert response.status_code == 404


def test_resolution_endpoint_returns_summary(client, db_session):
    market = _make_market(
        "evt-300",
        "Resolved Market",
        category="news",
        oracle="0xabc",
        status="commit",
    )
    market.condition_id = "0x1111111111111111111111111111111111111111111111111111111111111111"
    market.condition_id = market.condition_id.lower()
    market.outcomes = ["Yes", "No"]
    market.outcome_prices = [0.45, 0.55]
    db_session.add(market)
    db_session.commit()

    checked_at = datetime.now(timezone.utc)
    resolution = models.Resolution(
        condition_id=market.condition_id.lower(),
        source="conditional_tokens",
        resolved=True,
        payouts=[0, 1],
        winners=[{"index": 1, "label": "No", "payout": 1}],
        outcomes=["Yes", "No"],
        oracle="0xfeed",
        question_id="0x" + "f" * 64,
        transaction_hash="0x" + "1" * 64,
        block_number=1234,
        block_timestamp=checked_at,
        checked_at=checked_at,
    )
    db_session.add(resolution)
    db_session.commit()

    response = client.get(f"/resolution/{market.condition_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["resolved"] is True
    assert payload["winners"] == [{"index": 1, "label": "No", "payout": 1}]
    assert payload["marketId"] == market.id
    assert payload["eventId"] == market.event_id
    assert payload["title"] == market.title
    assert payload["transactionHash"] == resolution.transaction_hash
    assert payload["blockNumber"] == resolution.block_number
    assert payload["oracle"] == resolution.oracle
    assert datetime.fromisoformat(payload["checkedAt"]) == resolution.checked_at.replace(tzinfo=None)
    assert datetime.fromisoformat(payload["blockTimestamp"]) == resolution.block_timestamp.replace(tzinfo=None)


def test_category_endpoint_caches_results(client, db_session):
    sports = _make_market("evt-cat1", "Sports Market", category="sports", oracle="0xcat", status="commit")
    other = _make_market("evt-cat2", "Crypto Market", category="crypto", oracle="0xcat", status="commit")
    db_session.add_all([sports, other])
    db_session.commit()

    response = client.get("/categories/sports", params={"limit": 5})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["event_id"] == "evt-cat1"

    cache_key = category_cache_key("sports", 5)
    assert cache_key in api_main.cache_client.store
    db_session.query(models.Market).delete()
    db_session.commit()
    cached = client.get("/categories/sports", params={"limit": 5})
    assert cached.status_code == 200
    assert len(cached.json()) == 1
    assert cached.json()[0]["event_id"] == "evt-cat1"


def test_category_endpoint_validates_slug(client):
    resp = client.get("/categories/unknown-category")
    assert resp.status_code == 404


def test_category_endpoint_allows_hyphenated_slug(client, db_session):
    market = _make_market("evt-cat-slug", "AI Tech Market", category="AI & Tech", oracle="0xslug", status="commit")
    db_session.add(market)
    db_session.commit()

    resp = client.get("/categories/ai-tech", params={"limit": 2})
    assert resp.status_code == 200
    assert resp.json()[0]["event_id"] == "evt-cat-slug"


def test_tag_endpoint_filters_and_caches(client, db_session):
    market = _make_market("evt-tag1", "Tagged Market", category="news", oracle="0xaaa", status="commit")
    market.tags = ["BTC Halving", "Crypto"]
    db_session.add(market)
    db_session.commit()

    response = client.get("/tags/btc-halving", params={"limit": 10})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["event_id"] == "evt-tag1"

    cache_key = tag_cache_key("btc-halving", 10)
    assert cache_key in api_main.cache_client.store
    db_session.query(models.Market).delete()
    db_session.commit()
    cached = client.get("/tags/btc-halving", params={"limit": 10})
    assert cached.status_code == 200
    assert len(cached.json()) == 1
    assert cached.json()[0]["event_id"] == "evt-tag1"


def test_tag_endpoint_validates_slug(client):
    resp = client.get("/tags/unknown")
    assert resp.status_code == 404


def test_tag_endpoint_accepts_encoded_spaces(client, db_session):
    market = _make_market("evt-tag-space", "Gov Market", category="news", oracle="0xgov", status="commit")
    market.tags = ["Gov shutdown"]
    db_session.add(market)
    db_session.commit()

    resp = client.get("/tags/gov%20shutdown", params={"limit": 5})
    assert resp.status_code == 200
    assert resp.json()[0]["event_id"] == "evt-tag-space"


def test_suggest_endpoint_serves_cache_when_source_removed(client, db_session):
    market = _make_market("evt-suggest", "Alpha Prediction", category="alpha", oracle="0xsuggest", status="commit")
    db_session.add(market)
    db_session.commit()

    first = client.get("/markets/suggest", params={"q": "Alpha", "limit": 3})
    assert first.status_code == 200
    assert {item["event_id"] for item in first.json()} == {"evt-suggest"}

    db_session.query(models.Market).delete()
    db_session.commit()

    second = client.get("/markets/suggest", params={"q": "Alpha", "limit": 3})
    assert second.status_code == 200
    assert {item["event_id"] for item in second.json()} == {"evt-suggest"}
    cache_key = suggest_cache_key("Alpha", 3)
    assert cache_key in api_main.cache_client.store


def test_market_allowlists_filter_results(client, db_session):
    market_allowed = _make_market(
        "evt-allowed",
        "Allowed",
        category="sports",
        oracle="0xoracle",
        status="commit",
    )
    market_allowed.tags = ["gov-shutdown", "macro"]

    market_blocked = _make_market(
        "evt-blocked",
        "Blocked",
        category="finance",
        oracle="0xoracle",
        status="commit",
    )
    market_blocked.tags = ["equities"]

    db_session.add_all([market_allowed, market_blocked])
    db_session.commit()

    original_categories = list(api_main.settings.market_category_allowlist)
    original_tags = list(api_main.settings.market_tag_allowlist)
    api_main.settings.market_category_allowlist = ["sports"]
    api_main.settings.market_tag_allowlist = ["gov-shutdown"]

    try:
        response = client.get("/markets")
        assert response.status_code == 200
        payload = response.json()
        assert len(payload) == 1
        market = payload[0]
        assert market["event_id"] == "evt-allowed"
        assert market["tags"] == ["gov-shutdown", "macro"]

        # cached result should still respect filters
        cached_response = client.get("/markets")
        assert cached_response.status_code == 200
        cached_payload = cached_response.json()
        assert [item["event_id"] for item in cached_payload] == ["evt-allowed"]
    finally:
        api_main.settings.market_category_allowlist = original_categories
        api_main.settings.market_tag_allowlist = original_tags


def test_market_suggestions_endpoint(client, db_session):
    db_session.add_all(
        [
            _make_market("evt-1", "Election Alpha", category="politics", oracle="0x1", status="commit"),
            _make_market("evt-2", "Election Beta", category="politics", oracle="0x1", status="commit"),
            _make_market("evt-3", "Sports Final", category="sports", oracle="0x2", status="commit"),
        ]
    )
    db_session.commit()

    response = client.get("/markets/suggest", params={"q": "Election", "limit": 2})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2
    assert {item["event_id"] for item in payload} == {"evt-1", "evt-2"}
