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


def test_release_assets_handles_token_swap():
    state = StreamState(Settings())
    state.acquire_assets(["m1"])
    assert "m1" in state.subscriptions.assets
    state.register_clob_tokens("m1", ["t1", "t2"])
    assert "m1" not in state.subscriptions.assets
    assert {"t1", "t2"}.issubset(state.subscriptions.assets)
    state.release_assets(["m1"])
    assert "t1" not in state.subscriptions.assets
    assert "t2" not in state.subscriptions.assets


def test_fx_priority_skips_lower_sources():
    state = StreamState(Settings())
    quote = state.register_fx(Decimal("10"), source="binance_rest", allow_jump=True)
    assert quote is not None

    lower = state.register_fx(Decimal("9"), source="cryptocompare_rest", allow_jump=True)
    assert lower is None
    assert state.fx_quote and state.fx_quote.raw_zen_usd == Decimal("10")


def test_fx_updates_refresh_same_source_timestamp():
    state = StreamState(Settings(fx_max_age_seconds=60))
    first = state.register_fx(Decimal("8.5"), source="binance_ws")
    assert first is not None
    first_ts = state.fx_last_update
    # Simulate an aging quote that is still within the freshness window.
    staleish_ts = (first_ts or datetime.now(UTC)) - timedelta(seconds=30)
    state.fx_quote = FxQuote(
        zen_usd=first.zen_usd,
        raw_zen_usd=first.raw_zen_usd,
        fetched_at=staleish_ts,
        stale=False,
        source="binance_ws",
    )
    state.fx_last_update = staleish_ts
    state.fx_last_source = "binance_ws"

    refreshed = state.register_fx(Decimal("8.6"), source="binance_ws")
    assert refreshed is not None
    assert state.fx_last_update and first_ts and state.fx_last_update > first_ts
    assert state.fx_quote and state.fx_quote.stale is False


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
    assert calls["kwargs"]["socket_connect_timeout"] == 3.0


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
    await state.startup()
    assert state.redis is None
    assert state.redis_error is not None
