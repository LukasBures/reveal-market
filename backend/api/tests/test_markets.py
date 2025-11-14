from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import app.main as api_main
from app import crud, models
from prometheus_client import REGISTRY
from shared.cache_keys import category_cache_key, resolution_cache_key, suggest_cache_key, tag_cache_key


def _make_market(
    event_id: str,
    title: str,
    *,
    category: str,
    oracle: str,
    status: str,
    rake_bps: int | None = None,
) -> models.Market:
    now = datetime.now(tz=UTC)
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


def _cache_metric(outcome: str, status: str = "*", category: str = "*") -> float:
    sample = REGISTRY.get_sample_value(
        "markets_cache_requests_total",
        labels={"outcome": outcome, "status": status, "category": category},
    )
    return float(sample or 0.0)


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


def test_market_response_includes_summary_fields(client, db_session):
    market = _make_market("evt-555", "Summary Ready", category="finance", oracle="0xdef", status="commit")
    market.summary = "AI generated overview."
    market.summary_source = "ai_enrichment"
    market.summary_model = "gpt-5.1-mini"
    now = datetime.now(UTC)
    market.summary_checked_at = now
    market.summary_metadata = {"mode": "fallback"}
    db_session.add(market)
    db_session.commit()

    response = client.get(f"/markets/{market.event_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == "AI generated overview."
    assert payload["summary_source"] == "ai_enrichment"
    assert payload["summary_model"] == "gpt-5.1-mini"
    assert payload["summary_checked_at"].startswith(now.strftime("%Y-%m-%d"))


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

    checked_at = datetime.now(UTC)
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
    cache_key = resolution_cache_key(market.condition_id)
    assert cache_key in api_main.cache_client.store

    cached = client.get(f"/resolution/{market.condition_id}")
    assert cached.status_code == 200
    assert cached.json()["eventId"] == market.event_id


def test_markets_cache_metrics_track_hits_and_misses(client, db_session):
    market = _make_market("evt-metric", "Metric Market", category="sports", oracle="0xmetric", status="commit")
    db_session.add(market)
    db_session.commit()

    miss_before = _cache_metric("miss")
    hit_before = _cache_metric("hit")

    response_one = client.get("/markets")
    assert response_one.status_code == 200
    assert _cache_metric("miss") == miss_before + 1

    response_two = client.get("/markets")
    assert response_two.status_code == 200
    assert _cache_metric("hit") == hit_before + 1


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


def test_category_endpoint_populates_trending_with_general_feed(client, db_session):
    db_session.add_all(
        [
            _make_market("evt-trend-a", "Macro Watch", category="Finance", oracle="0xtrend", status="commit"),
            _make_market("evt-trend-b", "Championship Odds", category="Sports", oracle="0xtrend", status="commit"),
        ]
    )
    db_session.commit()

    resp = client.get("/categories/trending", params={"limit": 2})
    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload) == 2
    assert {item["event_id"] for item in payload} == {"evt-trend-a", "evt-trend-b"}


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


def test_create_market_invalidates_list_cache(client, db_session):
    db_session.add(_make_market("evt-cache-base", "Base Market", category="sports", oracle="0xaaa", status="commit"))
    db_session.commit()

    first = client.get("/markets", params={"limit": 10})
    assert first.status_code == 200
    assert {item["event_id"] for item in first.json()} == {"evt-cache-base"}

    payload = {
        "event_id": "evt-cache-new",
        "title": "Cached Addition",
        "category": "sports",
        "oracle": "0xbbb",
        "status": "commit",
    }
    create_response = client.post("/markets", json=payload)
    assert create_response.status_code == 201

    second = client.get("/markets", params={"limit": 10})
    assert second.status_code == 200
    assert {item["event_id"] for item in second.json()} == {"evt-cache-base", "evt-cache-new"}


def test_patch_market_invalidates_detail_cache(client, db_session):
    market = _make_market("evt-detail-cache", "Detail Cache", category="sports", oracle="0xccc", status="commit")
    db_session.add(market)
    db_session.commit()

    detail = client.get(f"/markets/{market.event_id}")
    assert detail.status_code == 200
    cache_key = api_main._market_detail_cache_key(market.event_id)
    assert cache_key in api_main.cache_client.store

    patch = client.patch(
        f"/markets/{market.event_id}",
        json={"title": "Updated Detail", "status": "settled"},
    )
    assert patch.status_code == 200

    refreshed = client.get(f"/markets/{market.event_id}")
    assert refreshed.status_code == 200
    assert refreshed.json()["title"] == "Updated Detail"
    assert refreshed.json()["status"] == "settled"


def test_markets_support_pagination_with_offset(client, db_session):
    base = datetime.now(tz=UTC).replace(microsecond=0)
    entries = []
    for idx in range(3):
        market = _make_market(
            f"evt-page-{idx}",
            f"Market #{idx}",
            category="sports",
            oracle="0xpage",
            status="commit",
        )
        market.created_at = base + timedelta(minutes=idx)
        market.updated_at = market.created_at
        entries.append(market)
    db_session.add_all(entries)
    db_session.commit()

    response = client.get("/markets", params={"limit": 1, "offset": 1})
    assert response.status_code == 200
    # Markets are ordered by created_at desc, so offset 1 should return the second newest entry.
    assert response.json()[0]["event_id"] == "evt-page-1"


def test_markets_limit_requires_positive_integer(client):
    resp = client.get("/markets", params={"limit": 0})
    assert resp.status_code == 422


def test_suggest_requires_min_length(client):
    resp = client.get("/markets/suggest", params={"q": "a", "limit": 5})
    assert resp.status_code == 422


def test_suggest_trims_and_is_case_insensitive(client, db_session):
    market = _make_market("evt-suggest-case", "Alpha Forecast", category="news", oracle="0xcase", status="commit")
    db_session.add(market)
    db_session.commit()

    resp = client.get("/markets/suggest", params={"q": "  ALpHa  ", "limit": 5})
    assert resp.status_code == 200
    assert {item["event_id"] for item in resp.json()} == {"evt-suggest-case"}


def test_suggest_supports_partial_word_matches(client, db_session):
    market = _make_market(
        "evt-solana",
        "Solana Validator Adoption",
        category="crypto",
        oracle="0xsol",
        status="commit",
    )
    db_session.add(market)
    db_session.commit()

    resp = client.get("/markets/suggest", params={"q": "sol", "limit": 5})
    assert resp.status_code == 200
    payload = resp.json()
    assert any(item["event_id"] == "evt-solana" for item in payload)


def test_suggest_capped_at_limit_without_duplicates(client, db_session):
    markets = [
        _make_market(
            f"evt-alpha-{idx}",
            f"Alpha Signal #{idx}",
            category="macro",
            oracle="0xalpha",
            status="commit",
        )
        for idx in range(6)
    ]
    db_session.add_all(markets)
    db_session.commit()

    resp = client.get("/markets/suggest", params={"q": "alpha", "limit": 5})
    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload) == 5
    assert len({item["event_id"] for item in payload}) == 5


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


def test_list_markets_by_category_handles_unknown_slug(client):
    response = client.get("/categories/unknown-segment")
    assert response.status_code == 404
    assert response.json()["detail"] == "category_not_found"


def test_list_markets_by_category_uses_cache(client, db_session, monkeypatch):
    allowed = _make_market(
        "evt-politics",
        "Election Insights",
        category="Politics",
        oracle="0xoracle",
        status="commit",
    )
    db_session.add(allowed)
    db_session.commit()

    first = client.get("/categories/politics")
    assert first.status_code == 200
    assert [item["event_id"] for item in first.json()] == ["evt-politics"]

    def fail(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("category query should be served from cache")

    monkeypatch.setattr(crud, "get_markets", fail)
    cached = client.get("/categories/politics")
    assert cached.status_code == 200
    assert [item["event_id"] for item in cached.json()] == ["evt-politics"]


def test_list_markets_by_tag_handles_unknown_slug(client):
    response = client.get("/tags/unknown-tag")
    assert response.status_code == 404
    assert response.json()["detail"] == "tag_not_found"


def test_list_markets_by_tag_normalizes_slug_and_caches(client, db_session, monkeypatch):
    tagged = _make_market(
        "evt-tagged",
        "Shutdown Tracker",
        category="Politics",
        oracle="0xoracle",
        status="commit",
    )
    tagged.tags = ["Gov shutdown", "Macro"]
    db_session.add(tagged)
    db_session.commit()

    first = client.get("/tags/gov-shutdown")
    assert first.status_code == 200
    assert [item["event_id"] for item in first.json()] == ["evt-tagged"]

    def fail(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("tag query should be served from cache")

    monkeypatch.setattr(crud, "get_markets_by_tag", fail)
    cached = client.get("/tags/Gov%20Shutdown")
    assert cached.status_code == 200
    assert [item["event_id"] for item in cached.json()] == ["evt-tagged"]


def test_create_market_requires_mandatory_fields(client):
    response = client.post(
        "/markets",
        json={
            "title": "Invalid payload",
            "category": "sports",
            "status": "commit",
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    missing_fields = {item["loc"][-1] for item in detail}
    assert "event_id" in missing_fields
    assert "oracle" in missing_fields


def test_list_markets_validates_limit_bounds(client):
    response = client.get("/markets", params={"limit": 0})
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "greater_than_equal"


def test_category_endpoint_rejects_limit_above_max(client):
    over_limit = api_main.settings.max_page_size + 1
    response = client.get("/categories/politics", params={"limit": over_limit})
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "less_than_equal"


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
