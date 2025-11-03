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
                "tags": ["sports"],
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
                "tags": [{"slug": "politics"}],
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
    assert first.category == "sports"
    assert first.status == "commit"
    assert first.outcomes == ["Yes", "No"]
    assert first.outcome_prices == [0.65, 0.35]
    assert first.closed is False

    assert second.event_id == "2"
    assert second.slug == "market-two"
    assert second.category == "politics"
    assert second.status == "settled"
    assert second.closed is True
    assert second.outcomes == ["Option A", "Option B", "Option C"]
    assert second.outcome_prices == [0.2, 0.3, 0.5]
    assert second.extra_data["gamma"]["slug"] == "market-two"
