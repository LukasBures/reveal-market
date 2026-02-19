from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.config import Settings
from app.main import create_app
from app.price_streamer import PriceStreamer
from app.state import FxQuote, StreamState
from fastapi.testclient import TestClient


def test_fx_websocket_stream(monkeypatch):
    state = StreamState()
    now = datetime.now(UTC)
    adjusted = Decimal("5.5") * (Decimal("1") - Decimal(str(state.settings.worsen_percent)))
    state.fx_quote = FxQuote(zen_usd=adjusted, raw_zen_usd=Decimal("5.5"), fetched_at=now, stale=False, source="test")
    state.fx_last_update = now

    # Keep startup/shutdown from doing network work
    async def noop():
        return None

    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]

    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)

    class DummyStreamer:
        async def start(self):
            return None

        async def stop(self):
            return None

    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())
    monkeypatch.setattr("app.main.DataStreamer", lambda *_args, **_kwargs: DummyStreamer())

    app = create_app()
    with TestClient(app) as client:
        for path in ("/fx/zen-usd", "/fx/zen-usdc", "/fx/zen-usdt"):
            with client.websocket_connect(path) as ws:
                message = ws.receive_json()
                expected = float(Decimal("5.5") * (Decimal("1") - Decimal(str(state.settings.worsen_percent))))
                assert message["zen_usd"] == expected
                assert message["raw_zen_usd"] == 5.5
                assert message["stale"] is False
                assert message["pair"] == "ZEN/USDC"


@pytest.mark.asyncio
async def test_fx_rest_fallback_after_ws_jump_rejection(monkeypatch):
    settings = Settings(
        fx_max_jump_percent=5, fx_max_age_seconds=5, fx_rest_interval_seconds=5, fx_min_price=0.5, fx_max_price=10
    )
    state = StreamState(settings)
    state._fx_prev_price = Decimal("1.0")
    state._fx_prev_price_ts = datetime.now(UTC)
    streamer = PriceStreamer(state, settings)

    async def fake_refresh_fx(label: str = "binance_rest"):
        return state.register_fx(Decimal("1.1"), source="cryptocompare_rest", allow_jump=True)

    monkeypatch.setattr(state, "refresh_fx", fake_refresh_fx)
    # WS update is a large jump and should be rejected.
    state.fx_last_update = datetime.now(UTC) - timedelta(seconds=10)
    state.fx_ws_last_update = state.fx_last_update - timedelta(seconds=10)
    streamer.state.fx_ws_connected = True
    # Jump rejection leaves fx_quote unset.
    await streamer._handle_fx_ws({"s": "ZENUSDT", "b": "2.0", "a": "2.0"})
    assert state.fx_quote is None
    # REST fallback should now run and accept cryptocompare quote.
    await streamer._fx_refresh_once()
    assert state.fx_quote is not None
    assert state.fx_quote.source == "cryptocompare_rest"


@pytest.mark.asyncio
async def test_fx_secondary_rest_used_when_primary_rejects(monkeypatch):
    settings = Settings(
        fx_primary_rest_url="https://primary.example.com", fx_secondary_rest_url="https://secondary.example.com"
    )
    state = StreamState(settings)
    calls: list[str] = []

    async def fake_fetch(url, label):
        calls.append(str(url))
        if "primary" in str(url):
            return None
        return state.register_fx(Decimal("9.9"), source="cryptocompare_rest", allow_jump=True)

    monkeypatch.setattr(state, "_fetch_fx_from_url", fake_fetch)
    quote = await state.refresh_fx()
    assert "primary.example.com" in calls[0]
    assert "secondary.example.com" in calls[1]
    assert quote.source == "cryptocompare_rest"
