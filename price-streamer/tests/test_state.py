from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
        quote = FxQuote(zen_usd=Decimal("1.23"), fetched_at=datetime.now(UTC), stale=False, source="test")
        state._update_fx(quote)
        return quote

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


def test_register_fx_rejects_large_jump():
    state = StreamState(Settings(fx_max_jump_percent=20.0, fx_jump_window_seconds=10))
    state._fx_prev_price = Decimal("1.0")
    state._fx_prev_price_ts = datetime.now(UTC)
    quote = state._register_fx(Decimal("1.5"), source="binance_ws")  # 50% jump
    assert quote is None
    assert state.fx_quote is None


def test_register_fx_accepts_small_jump():
    state = StreamState(Settings(fx_max_jump_percent=20.0, fx_jump_window_seconds=10, fx_min_price=0.5, fx_max_price=5))
    state._fx_prev_price = Decimal("1.0")
    state._fx_prev_price_ts = datetime.now(UTC)
    quote = state._register_fx(Decimal("1.1"), source="binance_ws")  # 10% jump
    assert quote is not None
    assert state.fx_quote is not None


def test_register_fx_rejects_non_positive():
    state = StreamState(Settings())
    quote = state._register_fx(Decimal("0"), source="binance_ws")
    assert quote is None
    assert state.fx_quote is None


def test_register_fx_bounds_and_circuit_breaker():
    state = StreamState(Settings(fx_min_price=0.5, fx_max_price=2.0, fx_max_consecutive_rejections=2))
    # First out-of-bounds should increment rejection count.
    assert state._register_fx(Decimal("10"), source="binance_ws") is None
    # Second rejection trips circuit breaker.
    assert state._register_fx(Decimal("0.1"), source="binance_ws") is None
    assert state.fx_ws_connected is False


@pytest.mark.asyncio
async def test_get_fx_marks_stale(monkeypatch):
    state = StreamState(Settings(fx_max_age_seconds=5))
    now = datetime.now(UTC) - timedelta(seconds=10)
    state.fx_quote = FxQuote(zen_usd=Decimal("1"), fetched_at=now, stale=False, source="test")
    state.fx_last_update = now
    quote = await state.get_fx()
    assert quote.stale is True


@pytest.mark.asyncio
async def test_cache_tick_signs_payload():
    state = StreamState(Settings(cache_prefix="ps:test", pubsub_prefix="ps:stream", signing_secret="abc"))
    dummy = DummyRedis()
    state.redis = dummy  # type: ignore[assignment]
    await state.cache_tick("m1", "0", {"price": "0.5"})
    stored = dummy.data["ps:test:m1:0"]
    assert "sig" in stored


def test_stale_markets_detection():
    state = StreamState(Settings())
    state.last_seen["fresh"] = datetime.now(UTC)
    state.last_seen["old"] = datetime.now(UTC) - timedelta(seconds=120)
    stale = state.stale_markets(stale_after_seconds=60)
    assert "old" in stale and "fresh" not in stale
