from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.config import Settings
from app.metrics import StreamerMetrics
from app.state import FxQuote, StreamState
from prometheus_client import CollectorRegistry


class _DummyPipeline:
    """Minimal pipeline that queues commands and replays them on execute."""

    def __init__(self, redis: DummyRedis):
        self._redis = redis
        self._ops: list[tuple[str, tuple, dict]] = []

    def hset(self, key: str, mapping: dict):
        self._ops.append(("hset", (key,), {"mapping": mapping}))
        return self

    def lpush(self, key: str, value: str):
        self._ops.append(("lpush", (key, value), {}))
        return self

    def ltrim(self, key: str, start: int, end: int):
        self._ops.append(("ltrim", (key, start, end), {}))
        return self

    def expire(self, key: str, seconds: int):
        self._ops.append(("expire", (key, seconds), {}))
        return self

    async def execute(self):
        for method, args, kwargs in self._ops:
            await getattr(self._redis, method)(*args, **kwargs)


class DummyRedis:
    def __init__(self):
        self.data = {}
        self.published = []
        self.history = {}
        self.expires = {}

    def pipeline(self, transaction: bool = True):  # noqa: FBT001,FBT002
        return _DummyPipeline(self)

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

    async def expire(self, key: str, seconds: int):
        self.expires[key] = seconds


@pytest.mark.asyncio
async def test_fx_refresh_fallback(monkeypatch):
    state = StreamState(Settings(fx_primary_rest_url="http://invalid", fx_timeout_seconds=0.1))

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


def testregister_fx_rejects_large_jump():
    state = StreamState(Settings(fx_max_jump_percent=20.0, fx_jump_window_seconds=10))
    state._fx_prev_price = Decimal("1.0")
    state._fx_prev_price_ts = datetime.now(UTC)
    quote = state.register_fx(Decimal("1.5"), source="binance_ws")  # 50% jump
    assert quote is None
    assert state.fx_quote is None


def testregister_fx_accepts_small_jump():
    state = StreamState(Settings(fx_max_jump_percent=20.0, fx_jump_window_seconds=10, fx_min_price=0.5, fx_max_price=5))
    state._fx_prev_price = Decimal("1.0")
    state._fx_prev_price_ts = datetime.now(UTC)
    quote = state.register_fx(Decimal("1.1"), source="binance_ws")  # 10% jump
    assert quote is not None
    assert state.fx_quote is not None


def testregister_fx_rejects_non_positive():
    state = StreamState(Settings())
    quote = state.register_fx(Decimal("0"), source="binance_ws")
    assert quote is None
    assert state.fx_quote is None


def testregister_fx_bounds_and_circuit_breaker():
    state = StreamState(
        Settings(
            fx_min_price=0.5,
            fx_max_price=2.0,
            fx_max_consecutive_rejections=2,
            fx_fallback_price=1.0,
        )
    )
    # First out-of-bounds should increment rejection count.
    assert state.register_fx(Decimal("10"), source="binance_ws") is None
    # Second rejection trips circuit breaker.
    assert state.register_fx(Decimal("0.1"), source="binance_ws") is None
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
    state = StreamState(
        Settings(
            cache_prefix="ps:test",
            pubsub_prefix="ps:stream",
            signing_secret="dummy_signing_key",  # noqa: S106 - test-only secret
        )
    )
    dummy = DummyRedis()
    state.redis = dummy  # type: ignore[assignment]
    await state.cache_tick("m1", "0", {"price": "0.5"})
    stored = dummy.data["ps:test:m1:0"]
    assert "sig" in stored


@pytest.mark.asyncio
async def test_cache_tick_trims_history():
    settings = Settings(history_limit=10, history_ttl_seconds=60, history_debounce_seconds=0.0)
    state = StreamState(settings)
    dummy = DummyRedis()
    state.redis = dummy  # type: ignore[assignment]
    state.subscriptions.add_assets(["m1"])

    for idx in range(11):
        await state.cache_tick(
            "m1",
            "0",
            {"price": f"{0.4 + idx / 10:.1f}", "type": "price", "timestamp": f"t{idx + 1}"},
        )

    history_key = f"{settings.history_prefix}:m1:0"
    assert history_key in dummy.history
    assert len(dummy.history[history_key]) == 10
    assert dummy.expires[history_key] == 60

    parsed = [json.loads(entry) for entry in dummy.history[history_key]]
    assert parsed[0]["timestamp"] == "t11"
    assert parsed[-1]["timestamp"] == "t2"


@pytest.mark.asyncio
async def test_refresh_fx_skips_self_url_and_uses_secondary(monkeypatch):
    settings = Settings(
        fx_primary_rest_url="http://streamer:8100/fx/zen-usd",
        fx_secondary_rest_url="https://example.com/fx",
    )
    state = StreamState(settings)
    calls: list[tuple[str, str]] = []

    async def fake_fetch(url, label):
        calls.append((str(url), label))
        return state.register_fx(Decimal("5"), source=label, allow_jump=True)

    monkeypatch.setattr(state, "_fetch_fx_from_url", fake_fetch)
    quote = await state.refresh_fx()

    assert quote is not None
    assert calls == [("https://example.com/fx", "cryptocompare_rest")]


def test_stale_markets_detection():
    state = StreamState(Settings())
    state.subscriptions.add_assets(["fresh", "old"])
    state.last_seen["fresh"] = datetime.now(UTC)
    state.last_seen["old"] = datetime.now(UTC) - timedelta(seconds=120)
    stale = state.stale_markets(stale_after_seconds=60)
    assert "old" in stale and "fresh" not in stale


def test_stale_markets_eviction():
    metrics = StreamerMetrics(registry=CollectorRegistry())
    settings = Settings(market_stale_seconds=60, market_stale_evict_seconds=120)
    state = StreamState(settings, metrics=metrics)
    state.subscriptions.add_assets(["stale", "evict"])
    state.last_seen["stale"] = datetime.now(UTC) - timedelta(seconds=90)
    state.last_seen["evict"] = datetime.now(UTC) - timedelta(seconds=300)
    metrics.market_staleness.labels(market_id="evict").set(300)
    stale = state.stale_markets(stale_after_seconds=settings.market_stale_seconds)
    assert "stale" in stale
    assert "evict" not in stale
    assert "evict" not in state.last_seen
    assert metrics.stale_market_total._value.get() == len(stale)


def test_add_rtds_symbols_increments_version():
    state = StreamState(Settings())
    assert state.rtds_symbols_version == 0
    state.add_rtds_symbols(["zenusdt", "ethusdt"])
    assert state.rtds_symbols_version == 1
    # Adding duplicates should not increment.
    state.add_rtds_symbols(["zenusdt"])
    assert state.rtds_symbols_version == 1


def test_remove_rtds_symbols_increments_version():
    state = StreamState(Settings())
    state.add_rtds_symbols(["zenusdt", "ethusdt"])
    start_version = state.rtds_symbols_version
    removed = state.remove_rtds_symbols(["zenusdt"])
    assert removed == ["zenusdt"]
    assert state.rtds_symbols_version == start_version + 1
    # Removing missing symbols should not increment.
    removed = state.remove_rtds_symbols(["missing"])
    assert removed == []
    assert state.rtds_symbols_version == start_version + 1


def test_add_rtds_symbols_respects_cap():
    state = StreamState(Settings(max_subscriptions=1))
    added = state.add_rtds_symbols(["sym-a", "sym-b"])
    assert added == ["sym-a"]
    assert state.rtds_symbols == {"sym-a"}
