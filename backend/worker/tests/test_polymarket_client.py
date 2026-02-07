"""Tests for the Polymarket Gamma async client pagination and normalisation behaviour."""

from __future__ import annotations

import logging

import httpx
import pytest
from app.polymarket import (
    AsyncPolymarketClient,
    MarketPayload,
    _build_market_hash_payload,
    _compute_market_hash,
    fetch_clob_markets,
    merge_clob_markets,
)


@pytest.mark.asyncio
async def test_polymarket_client_handles_pagination():
    """Ensure multiple offsets are fetched and converted into market payloads."""
    page_payloads = {
        0: [
            {
                "id": "1",
                "slug": "market-one",
                "question": "Market One?",
                "outcomes": ["Yes", "No"],
                "outcomePrices": ["0.65", "0.35"],
                "tags": ["sports", {"name": "macro"}],
                "conditionId": "0xaaa0000000000000000000000000000000000000000000000000000000000000",
                "closed": False,
            }
        ],
        1: [
            {
                "id": "2",
                "slug": "market-two",
                "question": "Second market?",
                "outcomes": ["Option A", "Option B", "Option C"],
                "outcomePrices": [0.2, 0.3, 0.5],
                "tags": [{"slug": "politics"}, "governance"],
                "conditionId": "0xbbb0000000000000000000000000000000000000000000000000000000000000",
                "closed": True,
                "umaResolutionStatus": "resolved",
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", "0"))
        limit = int(request.url.params.get("limit", "100"))
        data = page_payloads.get(offset, [])
        return httpx.Response(status_code=200, json=data[:limit])

    transport = httpx.MockTransport(handler)
    client = AsyncPolymarketClient("https://example.com", timeout=1.0, transport=transport)

    markets = await client.fetch_markets(page_size=1)

    assert len(markets) == 2
    first, second = markets

    assert first.event_id == "1"
    assert first.slug == "market-one"
    assert first.title == "Market One?"
    assert first.category == "Sports"
    assert first.tags == ["sports", "macro"]
    assert first.status == "commit"
    assert first.outcomes == ["Yes", "No"]
    assert first.outcome_prices == [0.65, 0.35]
    assert first.closed is False

    assert second.event_id == "2"
    assert second.slug == "market-two"
    assert second.category == "Politics"
    assert second.tags == ["politics", "governance"]
    assert second.status == "settled"
    assert second.closed is True
    assert second.outcomes == ["Option A", "Option B", "Option C"]
    assert second.outcome_prices == [0.2, 0.3, 0.5]
    assert second.gamma_metadata["slug"] == "market-two"


@pytest.mark.asyncio
async def test_polymarket_client_parses_stringified_arrays():
    """Markets with JSON-encoded strings for outcomes/prices populate columns."""

    payload = [
        {
            "id": "evt-string",
            "question": "Parsed?",
            "outcomes": '["Up", "Down"]',
            "outcomePrices": '["0.12", "0.88"]',
            "umaResolutionStatuses": '[{"status": "pending"}, {"status": "settled"}]',
            "clobTokenIds": '["abc", "def"]',
            "closed": True,
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json=payload)

    transport = httpx.MockTransport(handler)
    client = AsyncPolymarketClient("https://example.com", timeout=1.0, transport=transport)

    markets = await client.fetch_markets(page_size=1, max_pages=1)
    assert len(markets) == 1
    market = markets[0]

    assert market.outcomes == ["Up", "Down"]
    assert market.outcome_prices == [0.12, 0.88]
    assert market.uma_resolution_status == "pending"
    assert market.clob_token_ids == ["abc", "def"]


def test_market_hash_ignores_volatile_stats():
    base = MarketPayload(
        event_id="evt-hash",
        title="Hash Market",
        slug="hash-market",
        category="news",
        outcomes=["Yes", "No"],
        outcome_prices=[0.5, 0.5],
        best_bid=0.1,
        best_ask=0.2,
        spread=0.1,
        volume=100.0,
        open_interest=50.0,
        liquidity_usd=200.0,
        volume_24h_usd=20.0,
        orderbook_volume_usd=80.0,
        trades_quantity=5,
    )
    baseline_hash = _compute_market_hash(_build_market_hash_payload(base))
    updated = base.model_copy(
        update={
            "best_bid": 0.9,
            "best_ask": 0.95,
            "spread": 0.05,
            "volume": 300.0,
            "open_interest": 75.0,
            "liquidity_usd": 400.0,
            "volume_24h_usd": 60.0,
            "orderbook_volume_usd": 120.0,
            "trades_quantity": 12,
        }
    )
    updated_hash = _compute_market_hash(_build_market_hash_payload(updated))
    assert updated_hash == baseline_hash

    changed = base.model_copy(update={"title": "Hash Market Updated"})
    changed_hash = _compute_market_hash(_build_market_hash_payload(changed))
    assert changed_hash != baseline_hash


@pytest.mark.asyncio
async def test_polymarket_client_derives_category_from_event_series_when_tags_missing():
    """Ensure category falls back to event/series metadata when tags are absent."""

    payload = [
        {
            "id": "evt-derivation",
            "question": "Who wins?",
            "conditionId": "0xccc0000000000000000000000000000000000000000000000000000000000000",
            "events": [
                {
                    "slug": "cfb-sc-txam-2025-11-15",
                    "series": [{"title": "CFB 2025"}],
                }
            ],
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json=payload)

    transport = httpx.MockTransport(handler)
    client = AsyncPolymarketClient("https://example.com", timeout=1.0, transport=transport)

    markets = await client.fetch_markets(page_size=1, max_pages=1)

    assert len(markets) == 1
    assert markets[0].category == "Sports"


@pytest.mark.asyncio
async def test_polymarket_client_respects_closed_filter_and_extra_params():
    """Ensure closed flag + caller-provided params are forwarded in requests."""

    observed_params: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_params.append(dict(request.url.params))
        return httpx.Response(
            status_code=200,
            json=[
                {
                    "id": "99",
                    "question": "Tracked market?",
                    "outcomes": ["Yes", "No"],
                    "outcomePrices": [0.4, 0.6],
                    "tags": [],
                    "closed": True,
                }
            ],
        )

    transport = httpx.MockTransport(handler)
    client = AsyncPolymarketClient("https://example.com", timeout=1.0, transport=transport)

    markets = await client.fetch_markets(
        page_size=5,
        max_pages=1,
        closed=True,
        extra_params={"customFlag": "alpha"},
    )

    assert len(markets) == 1
    market = markets[0]
    assert market.event_id == "99"
    assert market.closed is True

    assert len(observed_params) == 1
    sent_params = observed_params[0]
    assert sent_params["closed"] == "true"
    assert sent_params["limit"] == "5"
    assert sent_params["offset"] == "0"
    assert sent_params["customFlag"] == "alpha"


@pytest.mark.asyncio
async def test_polymarket_client_handles_wrapped_payload():
    """Support Gamma responses that wrap markets inside a data/items container."""

    payload = {
        "data": [
            {
                "id": "wrapped-1",
                "question": "Wrapped market?",
                "outcomes": ["Yes", "No"],
                "outcomePrices": [0.5, 0.5],
            }
        ],
        "meta": {"total": 1},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json=payload)

    transport = httpx.MockTransport(handler)
    client = AsyncPolymarketClient("https://example.com", timeout=1.0, transport=transport)

    markets = await client.fetch_markets(page_size=10, max_pages=1)

    assert len(markets) == 1
    assert markets[0].event_id == "wrapped-1"


@pytest.mark.asyncio
async def test_polymarket_client_supports_full_markets_endpoint(monkeypatch):
    """Allow RM_POLYMARKET_API_BASE to include the markets segment already."""

    observed = {"path": None}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["path"] = request.url.path
        return httpx.Response(
            status_code=200,
            json=[
                {
                    "id": "evt-custom",
                    "question": "Custom endpoint?",
                    "outcomes": ["Yes", "No"],
                    "outcomePrices": [0.5, 0.5],
                }
            ],
        )

    transport = httpx.MockTransport(handler)
    client = AsyncPolymarketClient(
        "https://gamma.polymarket.example/polygon/markets",
        timeout=1.0,
        transport=transport,
    )

    markets = await client.fetch_markets(page_size=1, max_pages=1)

    assert len(markets) == 1
    assert markets[0].event_id == "evt-custom"
    assert observed["path"] == "/polygon/markets"


@pytest.mark.asyncio
async def test_polymarket_client_appends_extra_filters():
    """Ensure polymarket-client forwards caller-provided filters (network/active/etc)."""

    observed_params: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_params.append(dict(request.url.params))
        return httpx.Response(status_code=200, json=[])

    transport = httpx.MockTransport(handler)
    client = AsyncPolymarketClient(
        "https://gamma.polymarket.example",
        timeout=1.0,
        transport=transport,
        empty_page_tolerance=1,
    )

    await client.fetch_markets(
        page_size=1,
        max_pages=1,
        extra_params={"network": "137", "active": "true", "archived": "false"},
    )

    assert observed_params
    first = observed_params[0]
    assert first["network"] == "137"
    assert first["active"] == "true"
    assert first["archived"] == "false"


@pytest.mark.asyncio
async def test_polymarket_client_handles_empty_pages_with_meta_total():
    """Continue pagination when Gamma temporarily returns empty pages despite meta.total."""

    responses = {
        0: {"data": [{"id": "evt-1", "question": "First?"}], "meta": {"total": 2}},
        1: {"data": [], "meta": {"total": 2}},
        2: {"data": [{"id": "evt-2", "question": "Second?"}], "meta": {"total": 2}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", "0"))
        return httpx.Response(status_code=200, json=responses.get(offset, {"data": []}))

    transport = httpx.MockTransport(handler)
    client = AsyncPolymarketClient(
        "https://gamma.polymarket.example",
        timeout=1.0,
        transport=transport,
        empty_page_tolerance=2,
    )

    markets = await client.fetch_markets(page_size=1, max_pages=5)

    assert [m.event_id for m in markets] == ["evt-1", "evt-2"]


@pytest.mark.asyncio
async def test_polymarket_client_derives_grouping_fields():
    payload = [
        {
            "id": "grp-1",
            "slug": "makina-public-sale-total-commitments-1-5m",
            "question": "How much will be committed to the Makina public sale?",
            "groupItemTitle": ">$1.5M",
            "groupItemThreshold": "1500000",
            "outcomes": ["Yes", "No"],
            "outcomePrices": [0.44, 0.56],
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json=payload)

    transport = httpx.MockTransport(handler)
    client = AsyncPolymarketClient("https://example.com", timeout=1.0, transport=transport)
    markets = await client.fetch_markets(page_size=1, max_pages=1)

    assert len(markets) == 1
    market = markets[0]
    assert market.group_slug == "makina-public-sale-total-commitments"
    assert market.group_position == 1500000
    assert market.group_item_threshold == 1500000
    assert market.group_item_title == ">$1.5M"
    assert market.gamma_metadata.get("group_slug") == "makina-public-sale-total-commitments"


@pytest.mark.asyncio
async def test_polymarket_client_derives_group_slug_from_embedded_range():
    payload = [
        {
            "id": "grp-2",
            "slug": "will-the-eurozones-monthly-inflation-increase-by-0pt2-in-november",
            "question": "Will the Eurozone's monthly inflation increase by 0.2% in November?",
            "groupItemTitle": "0.2%",
            "outcomes": ["Yes", "No"],
            "outcomePrices": [0.5, 0.5],
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json=payload)

    transport = httpx.MockTransport(handler)
    client = AsyncPolymarketClient("https://example.com", timeout=1.0, transport=transport)
    markets = await client.fetch_markets(page_size=1, max_pages=1)

    assert len(markets) == 1
    market = markets[0]
    assert market.group_slug == "will-the-eurozones-monthly-inflation-increase-by"
    assert market.group_item_title == "0.2%"


@pytest.mark.asyncio
async def test_polymarket_client_fetches_events_and_flattens_markets():
    events_payload = [
        {
            "id": "ev-multi",
            "slug": "multi-event",
            "markets": [
                {
                    "id": "m-1",
                    "question": "Q1?",
                    "outcomes": ["Yes", "No"],
                    "outcomePrices": [0.6, 0.4],
                },
                {
                    "id": "m-2",
                    "question": "Q2?",
                    "outcomes": ["Up", "Down"],
                    "outcomePrices": [0.5, 0.5],
                },
            ],
        },
        {
            "id": "ev-single",
            "slug": "single-event",
            "markets": [
                {
                    "id": "m-3",
                    "question": "Solo?",
                    "outcomes": ["Left", "Right"],
                    "outcomePrices": [0.3, 0.7],
                }
            ],
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", "0"))
        if offset > 0:
            return httpx.Response(status_code=200, json=[])
        return httpx.Response(status_code=200, json=events_payload)

    transport = httpx.MockTransport(handler)
    client = AsyncPolymarketClient("https://example.com", timeout=1.0, transport=transport)
    markets = await client.fetch_events_markets(page_size=10, max_pages=2)

    assert len(markets) == 3
    multi = [m for m in markets if m.event_id in {"m-1", "m-2"}]
    single = [m for m in markets if m.event_id == "m-3"]
    assert {m.group_slug for m in multi} == {"multi-event"}
    assert single[0].group_slug is None
    # Ensure event metadata was attached


@pytest.mark.asyncio
async def test_polymarket_events_inherit_tags_for_category():
    events_payload = [
        {
            "id": "ev-1",
            "slug": "finance-event",
            "tags": [{"id": "120", "label": "Finance", "slug": "finance"}],
            "markets": [
                {
                    "id": "m-1",
                    "question": "Q?",
                    "outcomes": ["Yes", "No"],
                    "outcomePrices": [0.5, 0.5],
                }
            ],
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", "0"))
        if offset > 0:
            return httpx.Response(status_code=200, json=[])
        return httpx.Response(status_code=200, json=events_payload)

    transport = httpx.MockTransport(handler)
    client = AsyncPolymarketClient("https://example.com", timeout=1.0, transport=transport)
    markets = await client.fetch_events_markets(page_size=10, max_pages=1)

    assert markets[0].category == "Finance"
    assert markets[0].tags == ["finance"]


@pytest.mark.asyncio
async def test_polymarket_client_forwards_event_filters(monkeypatch):
    observed: dict[str, list[tuple[str, str]]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["params"] = list(request.url.params.multi_items())
        return httpx.Response(
            status_code=200,
            json={
                "data": [
                    {
                        "id": "e1",
                        "markets": [
                            {
                                "id": "m1",
                                "question": "Q?",
                                "outcomes": ["Yes", "No"],
                                "outcomePrices": [0.5, 0.5],
                            }
                        ],
                    }
                ],
                "meta": {"total": 1},
            },
        )

    transport = httpx.MockTransport(handler)
    client = AsyncPolymarketClient("https://example.com", timeout=1.0, transport=transport)
    await client.fetch_events_markets(
        page_size=1,
        max_pages=1,
        order="id",
        ascending=True,
        closed=False,
        extra_params={
            "tag_id": 42,
            "exclude_tag_id": [1, 2],
            "slug": ["a", "b"],
            "related_tags": True,
            "include_chat": False,
        },
    )

    params = observed["params"]
    assert ("limit", "1") in params
    assert ("offset", "0") in params
    assert ("order", "id") in params
    assert ("ascending", "true") in params
    assert ("closed", "false") in params
    assert ("tag_id", "42") in params
    assert ("exclude_tag_id", "1") in params and ("exclude_tag_id", "2") in params
    assert ("slug", "a") in params and ("slug", "b") in params
    assert ("related_tags", "true") in params
    assert ("include_chat", "false") in params


def test_merge_clob_markets_enriches_payload():
    markets = [
        MarketPayload(
            event_id="evt-merge",
            title="Merge me?",
            oracle="polymarket",
            condition_id="0xabc",
            outcomes=["Yes", "No"],
        )
    ]

    clob_market = {
        "condition_id": "0xabc",
        "tokens": [
            {"token_id": "tok1", "outcome": "Yes", "price": 0.55},
            {"token_id": "tok2", "outcome": "No", "price": 0.45},
        ],
        "minimum_order_size": 5,
        "minimum_tick_size": 0.001,
        "enable_order_book": True,
    }

    class StubClobClient:
        def get_simplified_markets(self, next_cursor: str = "MA=="):
            return {"data": [clob_market], "next_cursor": "LTE="}

    merge_clob_markets(markets, StubClobClient())
    merged = markets[0]
    assert merged.clob_token_ids == ["tok1", "tok2"]
    assert merged.order_min_size == 5
    assert merged.price_tick_size == 0.001
    assert merged.enable_order_book is True
    assert merged.gamma_metadata is None


def test_merge_clob_matches_by_slug():
    markets = [
        MarketPayload(
            event_id="evt-slug",
            title="Market with slug",
            oracle="polymarket",
            slug="market-slug",
        )
    ]
    clob_market = {
        "market_slug": "market-slug",
        "tokens": [
            {"token_id": "tok-a", "outcome": "Yes", "price": 0.4},
            {"token_id": "tok-b", "outcome": "No", "price": 0.6},
        ],
        "minimum_order_size": 10,
    }

    class StubClobClient:
        def get_simplified_markets(self, next_cursor: str = "MA=="):
            return {"data": [clob_market], "next_cursor": "LTE="}

    merge_clob_markets(markets, StubClobClient())
    merged = markets[0]
    assert merged.clob_token_ids == ["tok-a", "tok-b"]
    assert merged.order_min_size == 10
    assert merged.outcomes == ["Yes", "No"]
    assert merged.outcome_prices == [0.4, 0.6]


def test_merge_clob_preserves_existing_prices():
    market = MarketPayload(
        event_id="evt-existing",
        title="Existing",
        oracle="polymarket",
        condition_id="0xdef",
        outcomes=["Yes", "No"],
        outcome_prices=[0.1, 0.2],
    )
    clob_market = {
        "condition_id": "0xdef",
        "tokens": [
            {"token_id": "tok1", "outcome": "Yes", "price": 0.55},
            {"token_id": "tok2", "outcome": "No", "price": 0.45},
        ],
    }

    class StubClobClient:
        def get_simplified_markets(self, next_cursor: str = "MA=="):
            return {"data": [clob_market], "next_cursor": "LTE="}

    merge_clob_markets([market], StubClobClient())
    assert market.clob_token_ids == ["tok1", "tok2"]
    # Outcome prices are not overridden when already present.
    assert market.outcome_prices == [0.1, 0.2]


def test_merge_clob_skips_unmatched_markets(caplog):
    caplog.set_level("WARNING")
    markets = [
        MarketPayload(
            event_id="evt-keep",
            title="Keep",
            oracle="polymarket",
        )
    ]

    class StubClobClient:
        def get_simplified_markets(self, next_cursor: str = "MA=="):
            return {"data": [{"condition_id": "other"}], "next_cursor": "LTE="}

    merge_clob_markets(markets, StubClobClient(), logger=logging.getLogger("merge"))
    # No crash, no enrichment
    assert markets[0].clob_token_ids is None
    assert markets[0].outcome_prices is None


def test_fetch_clob_markets_handles_empty_data():
    class StubClobClient:
        def get_simplified_markets(self, next_cursor: str = "MA=="):
            return {"data": None, "next_cursor": "LTE="}

    results = fetch_clob_markets(StubClobClient())
    assert results == []


def test_fetch_clob_markets_respects_max_pages_and_cursor():
    calls: list[str] = []

    class StubClobClient:
        def __init__(self):
            self.payloads = [
                {"data": [{"id": "a"}], "next_cursor": "MQ=="},
                {"data": [{"id": "b"}], "next_cursor": "LTE="},
            ]

        def get_simplified_markets(self, next_cursor: str = "MA=="):
            calls.append(next_cursor)
            index = 0 if next_cursor == "MA==" else 1
            return self.payloads[index]

    client = StubClobClient()
    # Stops after first page when capped
    first_page_only = fetch_clob_markets(client, max_pages=1)
    assert first_page_only == [{"id": "a"}]
    # Full pagination reaches END_CURSOR
    calls.clear()
    all_pages = fetch_clob_markets(client, max_pages=None)
    assert all_pages == [{"id": "a"}, {"id": "b"}]
    assert calls == ["MA==", "MQ=="]
