from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.config import Settings
from app.price_streamer import PriceStreamer
from app.state import StreamState, FxQuote


def test_fx_refresh_triggers_rest_when_ws_stale():
    settings = Settings(fx_ws_stale_ttl_seconds=3, fx_max_age_seconds=5, fx_rest_interval_seconds=5)
    state = StreamState(settings)
    streamer = PriceStreamer(state, settings)

    called: list[str] = []

    async def fake_refresh(label: str = "binance_rest"):
        called.append(label)
        return state.register_fx(Decimal("5"), source=label, allow_jump=True)

    state.refresh_fx = fake_refresh  # type: ignore[assignment]
    state.fx_ws_last_update = datetime.now(UTC) - timedelta(seconds=10)
    state.fx_last_update = datetime.now(UTC) - timedelta(seconds=10)

    asyncio.run(streamer._fx_refresh_once())
    assert called == ["binance_rest"]


def test_refresh_fx_falls_back_to_secondary_source(monkeypatch):
    settings = Settings()
    state = StreamState(settings)

    async def primary(_url, _label):
        return None

    async def secondary(_url, label):
        assert label == "cryptocompare_rest"
        return state.register_fx(Decimal("6"), source="cryptocompare_rest", allow_jump=True)

    calls = {"count": 0}

    async def fake_fetch(url, label):
        calls["count"] += 1
        if calls["count"] == 1:
            return await primary(url, label)
        return await secondary(url, label)

    monkeypatch.setattr(state, "_fetch_fx_from_url", fake_fetch)
    quote = asyncio.run(state.refresh_fx())
    assert quote.source == "cryptocompare_rest"


def test_refresh_fx_keeps_existing_on_priority_reject(monkeypatch):
    settings = Settings()
    state = StreamState(settings)
    existing = state.register_fx(Decimal("5"), source="binance_ws", allow_jump=True)
    assert existing is not None

    async def fake_fetch(_url, label):
        return state.register_fx(Decimal("4"), source=label, allow_jump=True)

    monkeypatch.setattr(state, "_fetch_fx_from_url", fake_fetch)
    quote = asyncio.run(state.refresh_fx(label="binance_rest"))
    assert quote.source == "binance_ws"


def test_ws_update_from_non_target_symbol_noops():
    settings = Settings()
    state = StreamState(settings)
    streamer = PriceStreamer(state, settings)

    asyncio.run(streamer._handle_fx_ws({"s": "BTCUSDT", "c": "1.0"}))
    assert state.fx_quote is None


def test_ws_update_sets_state_when_valid():
    settings = Settings()
    state = StreamState(settings)
    streamer = PriceStreamer(state, settings)

    asyncio.run(streamer._handle_fx_ws({"s": "ZENUSDT", "b": "5.0", "a": "5.2"}))
    assert isinstance(state.fx_quote, FxQuote)
    assert state.fx_quote.source == "binance_ws"
