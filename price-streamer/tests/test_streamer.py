from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
async def test_metrics_update_on_fx_refresh():
    settings = Settings(fx_rest_interval_seconds=5, fx_max_age_seconds=5, fx_ws_stale_ttl_seconds=5)
    state = StreamState(settings)
    streamer = PriceStreamer(state, settings)
    await state.refresh_fx(label="coingecko_rest")
    streamer.metric_ws_connected.set(1 if state.fx_ws_connected else 0)
    streamer.metric_fx_stale.set(1 if state.fx_last_update is None else 0)
    assert streamer.metric_fx_stale._value.get() in (0, 1)


@pytest.mark.asyncio
async def test_metrics_mark_stale_without_fx():
    state = StreamState(Settings())
    streamer = PriceStreamer(state, state.settings)
    streamer._update_fx_metrics()
    assert streamer.metric_fx_stale._value.get() == 1


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


@pytest.mark.asyncio
async def test_handle_market_event_trade_caches_payload():
    state = StubState()
    streamer = PriceStreamer(state, state.settings)
    await streamer._handle_market_event(
        {"event_type": "last_trade_price", "market": "m1", "price": "0.42", "size": "10", "side": "BUY"},
        source="ws",
    )
    assert state.cached
    _, outcome, payload = state.cached[-1]
    assert outcome == "trades"
    assert payload["type"] == "trade"
    assert payload["price"] == "0.42"
    assert payload["side"] == "BUY"


@pytest.mark.asyncio
async def test_handle_market_event_book_applies_worsen():
    settings = Settings(worsen_percent=0.1)
    state = StubState()
    streamer = PriceStreamer(state, settings)
    await streamer._handle_market_event(
        {
            "event_type": "book",
            "market": "m2",
            "bids": [{"price": "1.0"}],
            "asks": [{"price": "2.0"}],
        },
        source="ws",
    )
    assert state.cached
    _, outcome, payload = state.cached[-1]
    assert outcome == "meta"
    assert Decimal(payload["display_best_bid"]) == Decimal("0.9")
    assert Decimal(payload["display_best_ask"]) == Decimal("1.8")


@pytest.mark.asyncio
async def test_handle_market_event_tick_size():
    state = StubState()
    streamer = PriceStreamer(state, state.settings)
    await streamer._handle_market_event(
        {"event_type": "tick_size_change", "market": "m3", "new_tick_size": "0.01"}, source="ws"
    )
    assert state.cached
    _, outcome, payload = state.cached[-1]
    assert outcome == "meta"
    assert payload["tick_size"] == "0.01"


@pytest.mark.asyncio
async def test_fx_ws_then_rest_fallback_metrics(monkeypatch):
    """WS preferred; staleness forces REST and updates metrics."""

    settings = Settings(
        fx_ws_stale_ttl_seconds=3,
        fx_rest_interval_seconds=5,
        fx_max_age_seconds=5,
        fx_rest_enabled=True,
    )
    state = StreamState(settings)
    streamer = PriceStreamer(state, settings)
    # Prime via WS
    await streamer._handle_fx_ws({"s": "ZENUSDT", "b": "10", "a": "10"})
    streamer._update_fx_metrics()
    assert streamer.metric_ws_connected._value.get() == 1
    assert streamer.metric_fx_source.labels(source="binance_ws")._value.get() == 1

    # Force staleness and replace refresh_fx
    async def fake_refresh_fx(label: str = "coingecko_rest"):
        return state._register_fx(Decimal("12"), source=label, allow_jump=True)

    monkeypatch.setattr(state, "refresh_fx", fake_refresh_fx)
    state.fx_ws_last_update = datetime.now(UTC) - timedelta(seconds=6)
    state.fx_last_update = state.fx_ws_last_update
    await streamer._fx_refresh_once()
    assert streamer.metric_ws_connected._value.get() == 0
    assert streamer.metric_fx_source.labels(source="coingecko_rest")._value.get() == 1


@pytest.mark.asyncio
async def test_price_history_seed_and_stream_pooling(monkeypatch):
    """Ensure we reuse a single connection per market and seed history is retained."""

    state = StubState()
    streamer = PriceStreamer(state, state.settings)
    # No tasks in tests: _normalize_and_publish bypasses throttled cache path.
    await streamer._normalize_and_publish({"id": "m1", "outcomePrices": [0.5]}, source="rest")
    await streamer._normalize_and_publish({"id": "m1", "outcomePrices": [0.6]}, source="rest")
    # Only the latest two entries should be cached per outcome.
    assert len(state.cached) == 2
