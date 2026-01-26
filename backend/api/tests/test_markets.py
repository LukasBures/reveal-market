from __future__ import annotations

from datetime import UTC, datetime, timedelta

import app.server as api_main
from app import crud, models
from app.services.markets import market_detail_cache_key
from prometheus_client import REGISTRY
from shared.cache_keys import markets_list_cache_key, suggest_cache_key
from sqlalchemy import select


def _make_market(
    event_id: str,
    title: str,
    *,
    category: str,
    oracle: str,
    status: str,
    rake_bps: int | None = None,
    group_slug: str | None = None,
    group_position: int | None = None,
    volume_24h_usd: float | None = None,
    orderbook_volume_usd: float | None = None,
    liquidity_usd: float | None = None,
) -> models.Market:
    now = datetime.now(tz=UTC)
    return models.Market(
        event_id=event_id,
        title=title,
        category=category,
        oracle=oracle,
        status=status,
        rake_bps=rake_bps,
        group_slug=group_slug,
        group_position=group_position,
        volume_24h_usd=volume_24h_usd,
        orderbook_volume_usd=orderbook_volume_usd,
        liquidity_usd=liquidity_usd,
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

    all_markets = client.get("/events").json()
    assert {m["event_id"] for m in all_markets} == {"evt-1", "evt-2", "evt-3"}

    filtered_status = client.get("/events", params={"status": "commit"}).json()
    assert {m["event_id"] for m in filtered_status} == {"evt-1", "evt-3"}

    filtered_category = client.get("/events", params={"category": "crypto"}).json()
    assert [m["event_id"] for m in filtered_category] == ["evt-2"]

    filtered_oracle = client.get("/events", params={"oracle": "0xaaa"}).json()
    assert {m["event_id"] for m in filtered_oracle} == {"evt-1", "evt-3"}

    filtered_search = client.get("/events", params={"search": "Alpha"}).json()
    assert {m["event_id"] for m in filtered_search} == {"evt-1", "evt-3"}


def test_volume_sorting_prefers_total_volume(client, db_session):
    m1 = _make_market(
        "evt-total-high",
        "Total volume first",
        category="sports",
        oracle="0xaaa",
        status="commit",
        volume_24h_usd=1,
    )
    m2 = _make_market(
        "evt-total-mid",
        "24h misleadingly high",
        category="sports",
        oracle="0xaaa",
        status="commit",
        volume_24h_usd=5_000,
    )
    m3 = _make_market(
        "evt-total-low",
        "Smallest total volume",
        category="sports",
        oracle="0xaaa",
        status="commit",
        volume_24h_usd=100_000,
    )
    db_session.add_all([m1, m2, m3])
    db_session.flush()
    db_session.add_all(
        [
            models.MarketGammaMetadata(market_id=m1.id, volume=200),
            models.MarketGammaMetadata(market_id=m2.id, volume=125),
            models.MarketGammaMetadata(market_id=m3.id, volume=75),
        ]
    )
    db_session.commit()

    ordered = client.get("/events", params={"order_by": "volume"}).json()
    ids = [m["event_id"] for m in ordered][:3]
    assert ids == ["evt-total-high", "evt-total-mid", "evt-total-low"]

    alias_ordered = client.get("/events", params={"order_by": "volume_24h_usd"}).json()
    alias_ids = [m["event_id"] for m in alias_ordered][:3]
    assert alias_ids == ids


def test_create_and_read_market(client):
    payload = {
        "event_id": "evt-100",
        "title": "New Market",
        "category": "sports",
        "oracle": "0xabc123",
        "status": "commit",
    }

    create_response = client.post("/events", json=payload)
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["event_id"] == payload["event_id"]
    assert created["title"] == payload["title"]
    assert created["status"] == payload["status"]
    assert created["rake_bps"] is None

    read_response = client.get(f"/events/by-key/{payload['event_id']}")
    assert read_response.status_code == 200
    retrieved = read_response.json()
    assert retrieved["event_id"] == payload["event_id"]
    assert retrieved["title"] == payload["title"]
    assert retrieved["markets"][0]["rake_bps"] is None


def test_create_market_with_rake(client):
    payload = {
        "event_id": "evt-101",
        "title": "Custom Rake",
        "category": "sports",
        "oracle": "0xabc123",
        "status": "commit",
        "rake_bps": 75,
    }

    response = client.post("/events", json=payload)
    assert response.status_code == 201
    created = response.json()
    assert created["rake_bps"] == 75

    fetched = client.get(f"/events/by-key/{payload['event_id']}").json()
    assert fetched["markets"][0]["rake_bps"] == 75


def test_market_detail_includes_grouping_and_siblings(client, db_session):
    group_slug = "makina-public-sale-total-commitments"
    first = _make_market(
        "evt-group-1",
        "Makina threshold 1",
        category="sales",
        oracle="0xgroup",
        status="commit",
        group_slug=group_slug,
        group_position=1500000,
        volume_24h_usd=10.5,
        liquidity_usd=50.0,
    )
    second = _make_market(
        "evt-group-2",
        "Makina threshold 2",
        category="sales",
        oracle="0xgroup",
        status="commit",
        group_slug=group_slug,
        group_position=2000000,
        volume_24h_usd=4.5,
        liquidity_usd=25.0,
    )
    db_session.add_all([first, second])
    db_session.flush()
    db_session.add_all(
        [
            models.MarketGammaMetadata(
                market_id=first.id,
                group_item_title=">$1.5M",
                group_item_threshold="1500000",
                group_slug=group_slug,
            ),
            models.MarketGammaMetadata(
                market_id=second.id,
                group_item_title=">$2M",
                group_item_threshold="2000000",
                group_slug=group_slug,
            ),
        ]
    )
    db_session.add_all(
        [
            models.MarketOutcome(market_id=first.id, outcome_id=0, label="Yes", price=0.55),
            models.MarketOutcome(market_id=first.id, outcome_id=1, label="No", price=0.45),
            models.MarketOutcome(market_id=second.id, outcome_id=0, label="Yes", price=0.35),
            models.MarketOutcome(market_id=second.id, outcome_id=1, label="No", price=0.65),
        ]
    )
    db_session.commit()

    response = client.get(f"/events/by-key/{first.event_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["group_slug"] == group_slug
    assert payload["aggregate_volume_24h_usd"] == 15.0
    markets = payload["markets"]
    assert isinstance(markets, list)
    assert {m["event_id"] for m in markets} == {first.event_id, second.event_id}
    assert markets[0]["group_position"] == 1500000
    assert markets[0]["group_item_title"] == ">$1.5M"
    assert markets[0]["outcome_prices"] == [0.55, 0.45]
    assert markets[1]["group_position"] == 2000000


def test_patch_market_and_stats(client, db_session):
    market = _make_market("evt-200", "Patch Me", category="culture", oracle="0xccc", status="commit")
    db_session.add(market)
    db_session.commit()

    patch_payload = {
        "title": "Patched Title",
        "status": "settled",
        "closed": True,
        "resolution_status": "final",
        "tags": ["patched"],
    }

    patch_response = client.patch(f"/events/{market.event_id}", json=patch_payload)
    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["title"] == "Patched Title"
    assert patched["status"] == "settled"
    assert patched["tags"] == ["patched"]
    assert patched["rake_bps"] is None

    stats_response = client.get("/events/stats")
    assert stats_response.status_code == 200
    stats = {entry["status"]: entry["count"] for entry in stats_response.json()}
    assert stats.get("finalized") == 1
    assert stats.get("total") == 1


def test_onchain_markets_unconfigured(client):
    response = client.get("/events/onchain")
    assert response.status_code == 503


def test_onchain_markets_success(client, monkeypatch):
    async def fake_fetch(settings):
        return ["0x1111111111111111111111111111111111111111"]

    monkeypatch.setattr("app.routes.markets.fetch_factory_markets", fake_fetch, raising=False)
    monkeypatch.setattr(api_main.settings, "factory_address", "0x123", raising=False)
    monkeypatch.setattr(api_main.settings, "rpc_url", "https://unit.test", raising=False)

    response = client.get("/events/onchain")
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
    db_session.add(market)
    db_session.flush()
    mid = db_session.execute(select(models.Market.id).where(models.Market.event_id == "evt-300")).scalar_one()
    db_session.add_all(
        [
            models.MarketOutcome(market_id=mid, outcome_id=0, label="Yes", price=0.45),
            models.MarketOutcome(market_id=mid, outcome_id=1, label="No", price=0.55),
        ]
    )
    db_session.commit()

    checked_at = datetime.now(UTC)
    resolution = models.Resolution(
        condition_id=market.condition_id.lower(),
        source="conditional_tokens",
        resolved=True,
        payouts=[0, 1],
        winners=[{"index": 1, "label": "No", "payout": 1}],
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


def test_resolution_endpoint_uses_goldsky_fallback(client, db_session, monkeypatch):
    market = _make_market(
        "evt-301",
        "Goldsky Market",
        category="economy",
        oracle="0xabc",
        status="commit",
    )
    market.condition_id = "0x2222222222222222222222222222222222222222222222222222222222222222"
    market.condition_id = market.condition_id.lower()
    db_session.add(market)
    db_session.flush()
    mid = db_session.execute(select(models.Market.id).where(models.Market.event_id == "evt-301")).scalar_one()
    db_session.add_all(
        [
            models.MarketOutcome(market_id=mid, outcome_id=0, label="Up", price=0.6),
            models.MarketOutcome(market_id=mid, outcome_id=1, label="Down", price=0.4),
        ]
    )
    db_session.commit()

    class DummyGoldsky:
        def __init__(self):
            self.called = False

        def resolution_summary(self, condition_id_hex, outcomes, outcome_count_hint):
            self.called = True
            return {
                "source": "goldsky_subgraph",
                "conditionId": condition_id_hex,
                "resolved": True,
                "outcomes": outcomes or [],
                "payouts": [1, 0],
                "winners": [{"index": 0, "label": "Up", "payout": 1}],
                "checkedAt": datetime.now(UTC),
                "blockNumber": 42,
                "blockTimestamp": datetime.now(UTC),
                "transactionHash": "0x" + "3" * 64,
                "oracle": "0xoracle",
                "questionId": "0x" + "4" * 64,
            }

    dummy = DummyGoldsky()
    monkeypatch.setattr("app.routes.markets.goldsky_client", dummy, raising=False)
    monkeypatch.setattr("app.runtime.goldsky_client", dummy, raising=False)

    response = client.get(f"/resolution/{market.condition_id}")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["source"] == "goldsky_subgraph"
    assert payload["resolved"] is True
    assert payload["outcomes"] == ["Up", "Down"]
    assert payload["transactionHash"].startswith("0x3")
    assert dummy.called is True
    assert payload["winners"] == [{"index": 0, "label": "Up", "payout": 1}]
    assert payload["marketId"] == market.id
    assert payload["eventId"] == market.event_id
    assert payload["title"] == market.title
    assert payload["oracle"] == "0xoracle"
    assert payload["questionId"].startswith("0x4")


def test_markets_cache_metrics_track_hits_and_misses(client, db_session):
    market = _make_market("evt-metric", "Metric Market", category="sports", oracle="0xmetric", status="commit")
    db_session.add(market)
    db_session.commit()

    miss_before = _cache_metric("miss")
    hit_before = _cache_metric("hit")

    response_one = client.get("/events", params={"limit": 10})
    assert response_one.status_code == 200
    assert _cache_metric("miss") == miss_before + 1

    response_two = client.get("/events", params={"limit": 10})
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

    cache_key = markets_list_cache_key("sports", None, None, None, 5, 0)
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


def test_category_endpoint_orders_by_volume(client, db_session):
    high = _make_market(
        "evt-cat-high",
        "High Volume",
        category="sports",
        oracle="0xvol",
        status="commit",
        orderbook_volume_usd=250,
    )
    low = _make_market(
        "evt-cat-low",
        "Low Volume",
        category="sports",
        oracle="0xvol",
        status="commit",
        orderbook_volume_usd=5,
    )
    db_session.add_all([low, high])
    db_session.commit()

    resp = client.get("/categories/sports", params={"limit": 5, "order_by": "volume"})
    assert resp.status_code == 200
    payload = resp.json()
    assert [item["event_id"] for item in payload] == ["evt-cat-high", "evt-cat-low"]
    cache_key = markets_list_cache_key("sports", None, None, None, 5, 0, order_by="volume")
    assert cache_key in api_main.cache_client.store


def test_markets_volume_order_respects_offset_and_cache(client, db_session):
    top = _make_market(
        "evt-vol-top",
        "Top Volume",
        category="sports",
        oracle="0xvol",
        status="commit",
        orderbook_volume_usd=500,
    )
    middle = _make_market(
        "evt-vol-mid",
        "Mid Volume",
        category="sports",
        oracle="0xvol",
        status="commit",
        orderbook_volume_usd=200,
    )
    low = _make_market(
        "evt-vol-low",
        "Low Volume",
        category="sports",
        oracle="0xvol",
        status="commit",
        orderbook_volume_usd=50,
    )
    db_session.add_all([low, middle, top])
    db_session.commit()

    resp = client.get("/events", params={"limit": 1, "offset": 1, "order_by": "volume"})
    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload) == 1
    assert payload[0]["event_id"] == "evt-vol-mid"
    cache_key = markets_list_cache_key(None, None, None, None, 1, 1, order_by="volume")
    assert cache_key in api_main.cache_client.store


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


def test_category_cache_respects_allowlist(client, db_session):
    original_allow = list(api_main.settings.market_category_allowlist)
    api_main.settings.market_category_allowlist = []
    try:
        db_session.add(
            _make_market("evt-allow-sports", "Allowlisted", category="sports", oracle="0xaaa", status="commit")
        )
        db_session.commit()

        first = client.get("/categories/sports", params={"limit": 5})
        assert first.status_code == 200
        assert len(first.json()) == 1

        api_main.settings.market_category_allowlist = ["politics"]
        cached = client.get("/categories/sports", params={"limit": 5})
        assert cached.status_code == 200
        assert cached.json() == []
    finally:
        api_main.settings.market_category_allowlist = original_allow


def test_suggest_endpoint_serves_cache_when_source_removed(client, db_session):
    market = _make_market("evt-suggest", "Alpha Prediction", category="alpha", oracle="0xsuggest", status="commit")
    db_session.add(market)
    db_session.commit()

    first = client.get("/events/suggest", params={"q": "Alpha", "limit": 3})
    assert first.status_code == 200
    assert {item["event_id"] for item in first.json()} == {"evt-suggest"}

    db_session.query(models.Market).delete()
    db_session.commit()

    second = client.get("/events/suggest", params={"q": "Alpha", "limit": 3})
    assert second.status_code == 200
    assert {item["event_id"] for item in second.json()} == {"evt-suggest"}
    cache_key = suggest_cache_key("Alpha", 3)
    assert cache_key in api_main.cache_client.store


def test_create_market_invalidates_list_cache(client, db_session):
    db_session.add(_make_market("evt-cache-base", "Base Market", category="sports", oracle="0xaaa", status="commit"))
    db_session.commit()

    first = client.get("/events", params={"limit": 10})
    assert first.status_code == 200
    assert {item["event_id"] for item in first.json()} == {"evt-cache-base"}

    payload = {
        "event_id": "evt-cache-new",
        "title": "Cached Addition",
        "category": "sports",
        "oracle": "0xbbb",
        "status": "commit",
    }
    create_response = client.post("/events", json=payload)
    assert create_response.status_code == 201

    second = client.get("/events", params={"limit": 10})
    assert second.status_code == 200
    assert {item["event_id"] for item in second.json()} == {"evt-cache-base", "evt-cache-new"}


def test_market_search_requests_not_cached(client, db_session):
    db_session.add(_make_market("evt-search", "AI Boom", category="tech", oracle="0xaaa", status="commit"))
    db_session.commit()

    response = client.get("/events", params={"search": "AI", "limit": 5})
    assert response.status_code == 200
    cache_key = markets_list_cache_key(None, None, None, "ai", 5, 0)
    assert cache_key not in api_main.cache_client.store


def test_patch_market_invalidates_detail_cache(client, db_session):
    market = _make_market("evt-detail-cache", "Detail Cache", category="sports", oracle="0xccc", status="commit")
    db_session.add(market)
    db_session.commit()

    detail = client.get(f"/events/by-key/{market.event_id}")
    assert detail.status_code == 200
    cache_key = market_detail_cache_key(market.event_id)
    assert cache_key in api_main.cache_client.store

    patch = client.patch(
        f"/events/{market.event_id}",
        json={"title": "Updated Detail", "status": "settled"},
    )
    assert patch.status_code == 200

    refreshed = client.get(f"/events/by-key/{market.event_id}")
    assert refreshed.status_code == 200
    assert refreshed.json()["markets"][0]["title"] == "Updated Detail"
    assert refreshed.json()["markets"][0]["status"] == "settled"


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

    response = client.get("/events", params={"limit": 1, "offset": 1})
    assert response.status_code == 200
    # Markets are ordered by created_at desc, so offset 1 should return the second newest entry.
    assert response.json()[0]["event_id"] == "evt-page-1"


def test_markets_limit_requires_positive_integer(client):
    resp = client.get("/events", params={"limit": 0})
    assert resp.status_code == 422


def test_suggest_requires_min_length(client):
    resp = client.get("/events/suggest", params={"q": "a", "limit": 5})
    assert resp.status_code == 422


def test_suggest_trims_and_is_case_insensitive(client, db_session):
    market = _make_market("evt-suggest-case", "Alpha Forecast", category="news", oracle="0xcase", status="commit")
    db_session.add(market)
    db_session.commit()

    resp = client.get("/events/suggest", params={"q": "  ALpHa  ", "limit": 5})
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

    resp = client.get("/events/suggest", params={"q": "sol", "limit": 5})
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

    resp = client.get("/events/suggest", params={"q": "alpha", "limit": 5})
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

    market_blocked = _make_market(
        "evt-blocked",
        "Blocked",
        category="finance",
        oracle="0xoracle",
        status="commit",
    )

    db_session.add_all([market_allowed, market_blocked])
    db_session.commit()

    original_categories = list(api_main.settings.market_category_allowlist)
    api_main.settings.market_category_allowlist = ["sports"]

    try:
        response = client.get("/events", params={"limit": 10})
        assert response.status_code == 200
        payload = response.json()
        assert len(payload) == 1
        market = payload[0]
        assert market["event_id"] == "evt-allowed"

        cached_response = client.get("/events", params={"limit": 10})
        assert cached_response.status_code == 200
        cached_payload = cached_response.json()
        assert [item["event_id"] for item in cached_payload] == ["evt-allowed"]
    finally:
        api_main.settings.market_category_allowlist = original_categories


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

    first = client.get("/categories/politics", params={"limit": 10})
    assert first.status_code == 200
    assert [item["event_id"] for item in first.json()] == ["evt-politics"]

    async def fail(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("category query should be served from cache")

    monkeypatch.setattr(crud, "get_markets", fail)
    cached = client.get("/categories/politics", params={"limit": 10})
    assert cached.status_code == 200
    assert [item["event_id"] for item in cached.json()] == ["evt-politics"]


def test_create_market_requires_mandatory_fields(client):
    response = client.post(
        "/events",
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
    response = client.get("/events", params={"limit": 0})
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

    response = client.get("/events/suggest", params={"q": "Election", "limit": 2})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2
    assert {item["event_id"] for item in payload} == {"evt-1", "evt-2"}
