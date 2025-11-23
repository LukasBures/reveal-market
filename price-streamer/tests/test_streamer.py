from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.config import Settings
from app.state import FxQuote, StreamState
from app.streamer import PriceStreamer


class StubState(StreamState):
    def __init__(self):
        super().__init__(Settings(rest_poll_seconds=5, ws_reconnect_seconds=5))
        self.cached = []

    async def cache_tick(self, market_id: str, outcome: str, payload: dict) -> None:
        self.cached.append((market_id, outcome, payload))

    async def get_fx(self):
        from datetime import UTC, datetime

        from app.state import FxQuote

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


@pytest.mark.asyncio
async def test_normalize_skips_when_fx_stale(monkeypatch):
    state = StubState()
    stale_quote = FxQuote(zen_usd=Decimal("1.0"), fetched_at=None, stale=True)  # type: ignore[arg-type]

    async def stale_fx():
        return stale_quote

    state.get_fx = stale_fx  # type: ignore[assignment]
    streamer = PriceStreamer(state, state.settings)
    data = {"id": "m1", "outcomePrices": [0.5, 0.25]}
    await streamer._normalize_and_publish(data, source="rest")
    assert not state.cached


@pytest.mark.asyncio
async def test_fx_ws_rejects_jump(monkeypatch):
    settings = Settings(fx_max_jump_percent=10.0, fx_jump_window_seconds=30)
    state = StreamState(settings)
    state._fx_prev_price = Decimal("1.0")
    state._fx_prev_price_ts = datetime.now(UTC)
    streamer = PriceStreamer(state, settings)
    await streamer._handle_fx_ws({"s": "ZENUSDT", "b": "2", "a": "2"})
    assert state.fx_quote is None


@pytest.mark.asyncio
async def test_normalize_payload_contains_fx():
    state = StubState()
    streamer = PriceStreamer(state, state.settings)
    data = {"id": "m1", "outcomePrices": [0.5]}
    await streamer._normalize_and_publish(data, source="rest")
    _, _, payload = state.cached[0]
    assert "fx_zen_usd" in payload and "fx_stale" in payload
