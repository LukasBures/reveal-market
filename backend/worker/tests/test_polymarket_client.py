"""Tests for the Polymarket Gamma client pagination and normalisation behaviour."""

from __future__ import annotations

import httpx
from app.polymarket import PolymarketClient


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
    assert second.extra_data["gamma"]["slug"] == "market-two"


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
