from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.config import Settings
from app.data_streamer import DataStreamer
from app.price_streamer import PriceStreamer
from app.state import StreamState


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
