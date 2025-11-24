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


@pytest.mark.asyncio
async def test_normalize_prefers_clob_midpoints(monkeypatch):
    state = StubState()
    streamer = PriceStreamer(state, state.settings)

    async def fake_midpoints(token_ids):
        return [Decimal("0.7"), Decimal("0.3")]

    monkeypatch.setattr(streamer, "_fetch_midpoints", fake_midpoints)
    data = {"id": "m2", "outcomePrices": [0.1, 0.2], "clobTokenIds": ["t1", "t2"]}
    await streamer._normalize_and_publish(data, source="rest")
    assert state.cached
    _, _, payload = state.cached[0]
    assert payload["price"] == "0.7"


@pytest.mark.asyncio
async def test_normalize_uses_raw_prices_when_midpoints_missing(monkeypatch):
    state = StubState()
    streamer = PriceStreamer(state, state.settings)

    async def none_midpoints(token_ids):
        return None

    monkeypatch.setattr(streamer, "_fetch_midpoints", none_midpoints)
    data = {"id": "m3", "outcomePrices": [0.9, 0.1], "clobTokenIds": ["x", "y"]}
    await streamer._normalize_and_publish(data, source="rest")
    assert state.cached
    _, _, payload = state.cached[0]
    assert payload["price"] == "0.9"


@pytest.mark.asyncio
async def test_fetch_midpoints_parses_dict_payload(monkeypatch):
    state = StubState()
    streamer = PriceStreamer(state, state.settings)

    class StubClob:
        def get_midpoints(self, params):
            return [{"midpoint": "0.25"}, {"midpoint": 0.75}]

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    streamer.clob_client = StubClob()
    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)

    mids = await streamer._fetch_midpoints(["a", "b"])
    assert mids == [Decimal("0.25"), Decimal("0.75")]


@pytest.mark.asyncio
async def test_fetch_midpoints_returns_none_when_no_params(monkeypatch):
    state = StubState()
    streamer = PriceStreamer(state, state.settings)
    streamer.clob_client = object()  # ensure client exists
    mids = await streamer._fetch_midpoints([])
    assert mids is None


@pytest.mark.asyncio
async def test_fetch_midpoints_handles_client_failure(monkeypatch):
    state = StubState()
    streamer = PriceStreamer(state, state.settings)

    class StubClob:
        def get_midpoints(self, params):
            raise RuntimeError("boom")

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    streamer.clob_client = StubClob()
    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)

    mids = await streamer._fetch_midpoints(["a"])
    assert mids is None
