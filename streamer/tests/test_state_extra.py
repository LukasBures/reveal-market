from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.config import Settings
from app.data_streamer import DataStreamer
from app.price_streamer import PriceStreamer
from app.state import FxQuote, StreamState


def test_asset_refcounts_add_and_release():
    state = StreamState(Settings())
    added = state.acquire_assets(["a", "b"])
    assert set(added) == {"a", "b"}
    assert {"a", "b"}.issubset(state.subscriptions.assets)

    # Release one asset; only that one should be removed.
    state.release_assets(["a"])
    assert "a" not in state.subscriptions.assets
    assert "b" in state.subscriptions.assets


def test_fx_priority_skips_lower_sources():
    state = StreamState(Settings())
    quote = state.register_fx(Decimal("10"), source="binance_rest", allow_jump=True)
    assert quote is not None

    lower = state.register_fx(Decimal("9"), source="cryptocompare_rest", allow_jump=True)
    assert lower is None
    assert state.fx_quote and state.fx_quote.raw_zen_usd == Decimal("10")


@pytest.mark.asyncio
async def test_price_streamer_rest_refresh_when_ws_stale():
    settings = Settings(fx_ws_stale_ttl_seconds=3, fx_rest_interval_seconds=5, fx_max_age_seconds=5)
    state = StreamState(settings)
    ps = PriceStreamer(state, settings)

    called: list[str] = []

    async def fake_refresh(label: str = "binance_rest"):
        called.append(label)
        return state.register_fx(Decimal("5"), source=label, allow_jump=True)

    state.refresh_fx = fake_refresh  # type: ignore[assignment]
    state.fx_ws_last_update = datetime.now(UTC) - timedelta(seconds=10)
    await ps._fx_refresh_once()
    assert called and called[0] == "binance_rest"


def test_data_streamer_rtds_subscription_filters_are_json():
    state = StreamState(Settings())
    ds = DataStreamer(state, state.settings)
    state.subscriptions.add_assets(["a", "b"])
    subs = ds._build_rtds_subscriptions()
    assert subs and subs[0].filters == ["a", "b"]


@pytest.mark.asyncio
async def test_history_debounce_and_ttl(monkeypatch):
    settings = Settings(history_debounce_seconds=5, history_ttl_seconds=60, history_limit=10)
    state = StreamState(settings)
    dummy = type("DummyRedis", (), {})()
    dummy.data = {}
    dummy.published = []
    dummy.history = {}
    dummy.expires = {}

    async def hset(key, mapping=None, **kwargs):
        dummy.data[key] = mapping or {}

    async def publish(channel, payload):
        dummy.published.append(payload)

    async def lpush(key, value):
        dummy.history.setdefault(key, []).insert(0, value)

    async def ltrim(key, start, end):
        if key not in dummy.history:
            return
        dummy.history[key] = dummy.history[key][start : end + 1]

    async def expire(key, seconds):
        dummy.expires[key] = seconds

    dummy.hset = hset
    dummy.publish = publish
    dummy.lpush = lpush
    dummy.ltrim = ltrim
    dummy.expire = expire
    state.redis = dummy  # type: ignore[assignment]

    await state.cache_tick("m1", "0", {"price": "0.5"})
    # Second write inside debounce window skips history push
    await state.cache_tick("m1", "0", {"price": "0.6"})
    assert len(dummy.history.get(f"{settings.history_prefix}:m1:0", [])) == 1
    assert dummy.expires[f"{settings.history_prefix}:m1:0"] == 60


def test_subscription_cap_skips_new_assets(caplog):
    settings = Settings(max_subscriptions=1)
    state = StreamState(settings)
    state.acquire_assets(["a"])
    state.acquire_assets(["b"])  # should skip due to cap
    assert state.subscriptions.assets == {"a"}
    assert any(
        "stream.assets.cap" in record.message or record.__dict__.get("event") == "stream.assets.cap"
        for record in caplog.records
    )


def test_refcount_reuse_and_release():
    state = StreamState(Settings())
    added = state.acquire_assets(["a"])
    assert added == ["a"]
    # acquiring same asset should not duplicate subscription
    added_second = state.acquire_assets(["a"])
    assert added_second == []
    assert state._asset_refcounts["a"] == 2
    state.release_assets(["a"])
    assert state._asset_refcounts["a"] == 1
    state.release_assets(["a"])
    assert "a" not in state._asset_refcounts
    assert "a" not in state.subscriptions.assets


@pytest.mark.asyncio
async def test_state_startup_requires_redis(monkeypatch):
    calls = {}

    class DummyRedis:
        def __init__(self, **kwargs):
            calls["kwargs"] = kwargs

        async def ping(self):
            return True

        async def aclose(self):
            return

    monkeypatch.setattr("app.state.Redis", type("DummyRedisFactory", (), {"from_url": lambda *a, **k: DummyRedis(**k)}))
    state = StreamState(Settings())

    async def fake_refresh():
        state.fx_quote = FxQuote(zen_usd=Decimal("1"), fetched_at=datetime.now(UTC), stale=False, source="test")
        return state.fx_quote

    state.refresh_fx = fake_refresh  # type: ignore[assignment]
    await state.startup()
    assert calls["kwargs"]["socket_timeout"] == 5
    assert calls["kwargs"]["socket_connect_timeout"] == 5


@pytest.mark.asyncio
async def test_state_startup_fails_when_redis_unreachable(monkeypatch):
    class BadRedis:
        async def ping(self):
            raise RuntimeError("no redis")

    monkeypatch.setattr("app.state.Redis", type("BadRedisFactory", (), {"from_url": lambda *a, **k: BadRedis()}))
    state = StreamState(Settings())

    async def fake_refresh():
        return None

    state.refresh_fx = fake_refresh  # type: ignore[assignment]
    with pytest.raises(RuntimeError):
        await state.startup()
