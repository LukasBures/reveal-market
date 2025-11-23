from __future__ import annotations

from decimal import Decimal

import pytest
from app.config import Settings
from app.state import FxQuote, StreamState


class DummyRedis:
    def __init__(self):
        self.data = {}
        self.published = []
        self.history = {}

    async def hset(self, key: str, mapping: dict):
        self.data[key] = mapping

    async def publish(self, channel: str, payload: str):
        self.published.append((channel, payload))

    async def lpush(self, key: str, value: str):
        self.history.setdefault(key, []).insert(0, value)

    async def ltrim(self, key: str, start: int, end: int):
        if key not in self.history:
            return
        self.history[key] = self.history[key][start : end + 1]


@pytest.mark.asyncio
async def test_fx_refresh_fallback(monkeypatch):
    state = StreamState(Settings(fx_feed_url="http://invalid", fx_timeout_seconds=0.1))

    async def fake_refresh():
        return FxQuote(
            zen_usd=Decimal("1.23"), fetched_at=state.fx_quote.fetched_at if state.fx_quote else None, stale=False
        )

    monkeypatch.setattr(state, "refresh_fx", fake_refresh)
    quote = await state.get_fx()
    assert quote.zen_usd == Decimal("1.23")


@pytest.mark.asyncio
async def test_cache_tick_uses_prefix(monkeypatch):
    state = StreamState(Settings(cache_prefix="ps:test", pubsub_prefix="ps:stream"))
    dummy = DummyRedis()
    state.redis = dummy  # type: ignore[assignment]
    await state.cache_tick("m1", "0", {"price": "0.5"})
    assert "ps:test:m1:0" in dummy.data
    assert dummy.published[0][0] == "ps:stream:m1"
