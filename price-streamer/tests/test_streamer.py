from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from app.config import Settings
from app.state import StreamState
from app.streamer import PriceStreamer


class StubState(StreamState):
    def __init__(self):
        super().__init__(Settings(rest_poll_seconds=5, ws_reconnect_seconds=5))
        self.cached = []

    async def cache_tick(self, market_id: str, outcome: str, payload: dict) -> None:
        self.cached.append((market_id, outcome, payload))

    async def get_fx(self):
        from app.state import FxQuote
        from datetime import UTC, datetime

        return FxQuote(zen_usd=Decimal("1.0"), fetched_at=datetime.now(UTC), stale=False)


@pytest.mark.asyncio
async def test_normalize_and_publish_handles_prices():
    state = StubState()
    streamer = PriceStreamer(state, state.settings)
    data = {"id": "m1", "outcomePrices": [0.5, 0.25]}
    await streamer._normalize_and_publish(data, source="rest")
    assert len(state.cached) == 2
    _, _, payload = state.cached[0]
    assert payload["market_id"] == "m1"
    assert payload["display_price"] != payload["price"]


@pytest.mark.asyncio
async def test_throttled_publish_deduplicates():
    state = StubState()
    streamer = PriceStreamer(state, state.settings)
    await streamer._throttled_publish("m1", "0", {"price": "0.5"})
    await streamer._throttled_publish("m1", "0", {"price": "0.5"})
    assert len(streamer._publish_cache) == 1
