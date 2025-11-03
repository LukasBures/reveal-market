"""Tests for the Polymarket client pagination and normalisation behaviour."""

from __future__ import annotations

from typing import Any

import httpx

from app.polymarket import PolymarketClient


def test_polymarket_client_handles_pagination():
    """Ensure multiple pages are fetched and converted into market payloads."""
    page_payloads: dict[int, dict[str, Any]] = {
        1: {
            "data": [
                {
                    "id": "1",
                    "attributes": {
                        "title": "Market One",
                        "category": "sports",
                        "status": "commit",
                        "outcomes": [{"name": "YES", "price": "0.6"}],
                    },
                }
            ],
            "meta": {"pagination": {"page": 1, "pageSize": 1, "pageCount": 2, "total": 2}},
        },
        2: {
            "data": [
                {
                    "id": "2",
                    "attributes": {
                        "question": "Second market?",
                        "collections": {
                            "data": [
                                {
                                    "attributes": {
                                        "slug": "news",
                                    }
                                }
                            ]
                        },
                        "status": "settled",
                        "marketAddress": "0xabc",
                        "prices": [{"name": "NO", "price": "0.45"}],
                    },
                }
            ],
            "meta": {"pagination": {"page": 2, "pageSize": 1, "pageCount": 2, "total": 2}},
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        page_param = request.url.params.get("pagination[page]")
        page = int(page_param) if page_param is not None else 1
        payload = page_payloads.get(page, {"data": []})
        return httpx.Response(status_code=200, json=payload)

    transport = httpx.MockTransport(handler)
    client = PolymarketClient("https://example.com/api/markets", timeout=1.0, transport=transport)

    markets = client.fetch_markets(page_size=1)

    assert len(markets) == 2
    first, second = markets
    assert first.event_id == "1"
    assert first.title == "Market One"
    assert first.category == "sports"
    assert second.event_id == "2"
    assert second.title == "Second market?"
    assert second.category == "news"
    assert second.market_address == "0xabc"
