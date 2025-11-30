"""Tests for the Polymarket Gamma client pagination and normalisation behaviour."""

from __future__ import annotations

import logging

import httpx
from app.polymarket import MarketPayload, PolymarketClient, fetch_clob_markets, merge_clob_markets


def test_polymarket_client_handles_pagination():
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
    client = PolymarketClient("https://example.com", timeout=1.0, transport=transport)

    markets = client.fetch_markets(page_size=1)

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


def test_polymarket_client_parses_stringified_arrays():
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
    client = PolymarketClient("https://example.com", timeout=1.0, transport=transport)

    markets = client.fetch_markets(page_size=1, max_pages=1)
    assert len(markets) == 1
    market = markets[0]

    assert market.outcomes == ["Up", "Down"]
    assert market.outcome_prices == [0.12, 0.88]
    assert market.uma_resolution_status == "pending"
    assert market.clob_token_ids == ["abc", "def"]


def test_polymarket_client_derives_category_from_event_series_when_tags_missing():
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
    client = PolymarketClient("https://example.com", timeout=1.0, transport=transport)

    markets = client.fetch_markets(page_size=1, max_pages=1)

    assert len(markets) == 1
    assert markets[0].category == "Sports"


def test_polymarket_client_respects_closed_filter_and_extra_params():
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
    client = PolymarketClient("https://example.com", timeout=1.0, transport=transport)

    markets = client.fetch_markets(
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


def test_polymarket_client_handles_wrapped_payload():
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
    client = PolymarketClient("https://example.com", timeout=1.0, transport=transport)

    markets = client.fetch_markets(page_size=10, max_pages=1)

    assert len(markets) == 1
    assert markets[0].event_id == "wrapped-1"


def test_polymarket_client_supports_full_markets_endpoint(monkeypatch):
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
    client = PolymarketClient(
        "https://gamma.polymarket.example/polygon/markets",
        timeout=1.0,
        transport=transport,
    )

    markets = client.fetch_markets(page_size=1, max_pages=1)

    assert len(markets) == 1
    assert markets[0].event_id == "evt-custom"
    assert observed["path"] == "/polygon/markets"


def test_polymarket_client_appends_extra_filters():
    """Ensure polymarket-client forwards caller-provided filters (network/active/etc)."""

    observed_params: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_params.append(dict(request.url.params))
        return httpx.Response(status_code=200, json=[])

    transport = httpx.MockTransport(handler)
    client = PolymarketClient(
        "https://gamma.polymarket.example",
        timeout=1.0,
        transport=transport,
        empty_page_tolerance=1,
    )

    client.fetch_markets(
        page_size=1,
        max_pages=1,
        extra_params={"network": "137", "active": "true", "archived": "false"},
    )

    assert observed_params
    first = observed_params[0]
    assert first["network"] == "137"
    assert first["active"] == "true"
    assert first["archived"] == "false"


def test_polymarket_client_handles_empty_pages_with_meta_total():
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
    client = PolymarketClient(
        "https://gamma.polymarket.example",
        timeout=1.0,
        transport=transport,
        empty_page_tolerance=2,
    )

    markets = client.fetch_markets(page_size=1, max_pages=5)

    assert [m.event_id for m in markets] == ["evt-1", "evt-2"]


def test_polymarket_client_derives_grouping_fields():
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
    client = PolymarketClient("https://example.com", timeout=1.0, transport=transport)
    markets = client.fetch_markets(page_size=1, max_pages=1)

    assert len(markets) == 1
    market = markets[0]
    assert market.group_slug == "makina-public-sale-total-commitments"
    assert market.group_position == 1500000
    assert market.group_item_threshold == 1500000
    assert market.group_item_title == ">$1.5M"
    assert market.gamma_metadata.get("group_slug") == "makina-public-sale-total-commitments"


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
