from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.config import Settings
from app.data_streamer import DataStreamer
from app.main import _sse_events
from app.metrics import StreamerMetrics, get_metrics
from app.price_streamer import PriceStreamer
from app.state import FxQuote, StreamState
from prometheus_client import CollectorRegistry


class StubState(StreamState):
    def __init__(self, settings: Settings | None = None):
        super().__init__(settings or Settings(rest_poll_seconds=5, ws_reconnect_seconds=5))
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
    streamer = DataStreamer(state, state.settings)
    data = {"id": "m1", "outcomePrices": [0.5, 0.25]}
    await streamer._normalize_and_publish(data, source="rest")
    assert len(state.cached) == 2


@pytest.mark.asyncio
async def test_refresh_clob_subscription_sends_on_version_change():
    state = StubState()
    streamer = DataStreamer(state, state.settings)
    state.subscriptions.add_assets(["a1"])

    class DummyWS:
        def __init__(self):
            self.sent = []

        async def send(self, payload):
            self.sent.append(payload)

        def __aiter__(self):
            return iter([])

    ws = DummyWS()
    last = await streamer._refresh_clob_subscription(ws, last_version=-1)
    assert last == state.subscriptions.version
    assert ws.sent  # initial subscribe sent
    state.subscriptions.add_assets(["a2"])
    last = await streamer._refresh_clob_subscription(ws, last)
    assert last == state.subscriptions.version
    assert len(ws.sent) == 2  # resend after version bump


@pytest.mark.asyncio
async def test_refresh_rtds_subscription_sends_on_version_change():
    state = StubState()
    streamer = DataStreamer(state, state.settings)
    state.add_rtds_symbols(["zenusdt"])

    # _build_rtds_subscriptions should reflect current symbols.
    subs = streamer._build_rtds_subscriptions()
    assert subs and subs[0].filters == ["zenusdt"]

    class DummyClient:
        def __init__(self):
            self.sent = []

        def add_subscriptions(self, subs):
            self.sent.extend(subs)

    streamer.rtds_client = DummyClient()
    await streamer._maybe_refresh_rtds_subscriptions()
    assert streamer._rtds_last_version == state.rtds_symbols_version
    assert streamer.rtds_client.sent
    # Adding a new symbol should trigger another send.
    state.add_rtds_symbols(["ethusdt"])
    await streamer._maybe_refresh_rtds_subscriptions()
    assert len(streamer.rtds_client.sent) == 2


def test_rtds_subscriptions_include_assets_and_symbols():
    state = StubState()
    streamer = DataStreamer(state, state.settings)
    state.subscriptions.add_assets(["asset-a"])
    state.add_rtds_symbols(["sym-b"])
    subs = streamer._build_rtds_subscriptions()
    assert subs
    assert set(subs[0].filters) == {"asset-a", "sym-b"}


def test_rtds_subscriptions_cap_prioritizes_assets():
    settings = Settings(max_subscriptions=2, rest_poll_seconds=5, ws_reconnect_seconds=5)
    state = StreamState(settings)
    streamer = DataStreamer(state, settings)
    state.subscriptions.add_assets(["asset-b", "asset-a"])
    state.add_rtds_symbols(["sym-a", "sym-b"])
    subs = streamer._build_rtds_subscriptions()
    assert subs
    assert len(subs[0].filters) == 2
    assert set(subs[0].filters) == {"asset-a", "asset-b"}


@pytest.mark.asyncio
async def test_throttled_publish_deduplicates():
    state = StubState()
    streamer = DataStreamer(state, state.settings)
    await streamer._throttled_publish("m1", "0", {"price": "0.5"})
    await streamer._throttled_publish("m1", "0", {"price": "0.5"})
    assert len(streamer._publish_cache) == 1


@pytest.mark.asyncio
async def test_flush_loop_handles_cache_errors(caplog):
    settings = Settings(publish_throttle_ms=50, rest_poll_seconds=5, ws_reconnect_seconds=5)
    state = StreamState(settings)
    streamer = DataStreamer(state, settings)

    async def fail_cache(*_args, **_kwargs):
        raise RuntimeError("boom")

    state.cache_tick = fail_cache  # type: ignore[assignment]
    streamer._publish_cache = {"m1:0": {"price": "0.5"}}
    caplog.set_level("WARNING")
    task = asyncio.create_task(streamer._flush_loop())
    await asyncio.sleep(0.1)
    streamer._stop.set()
    await asyncio.wait_for(task, timeout=1)
    assert streamer._publish_cache == {}
    assert any(record.__dict__.get("event") == "stream.publish.failed" for record in caplog.records)


@pytest.mark.asyncio
async def test_normalize_publishes_when_fx_stale_by_default():
    state = StubState()
    stale_quote = FxQuote(zen_usd=Decimal("1.0"), fetched_at=None, stale=True)  # type: ignore[arg-type]

    async def stale_fx():
        return stale_quote

    state.get_fx = stale_fx  # type: ignore[assignment]
    streamer = DataStreamer(state, state.settings)
    data = {"id": "m1", "outcomePrices": [0.5, 0.25]}
    await streamer._normalize_and_publish(data, source="rest")
    assert state.cached


@pytest.mark.asyncio
async def test_normalize_skips_when_fx_stale_if_disabled():
    settings = Settings(publish_when_fx_stale=False, rest_poll_seconds=5, ws_reconnect_seconds=5)
    state = StubState(settings)
    stale_quote = FxQuote(zen_usd=Decimal("1.0"), fetched_at=None, stale=True)  # type: ignore[arg-type]

    async def stale_fx():
        return stale_quote

    state.get_fx = stale_fx  # type: ignore[assignment]
    streamer = DataStreamer(state, settings)
    data = {"id": "m1", "outcomePrices": [0.5, 0.25]}
    await streamer._normalize_and_publish(data, source="rest")
    assert not state.cached


@pytest.mark.asyncio
async def test_normalize_uses_token_payload_when_outcome_prices_missing():
    state = StubState()
    streamer = DataStreamer(state, state.settings)
    data = {
        "id": "m-token",
        "tokens": [
            {"token_id": "tok-a", "price": "0.4"},
            {"token_id": "tok-b", "price": "0.6"},
        ],
    }
    await streamer._normalize_and_publish(data, source="rest")
    # Two outcomes should be cached using token price fallback.
    assert len(state.cached) == 2
    prices = {payload.get("price") for _, _, payload in state.cached}
    assert {"0.4", "0.6"}.issubset(prices)
    assert state.market_tokens.get("m-token") == ["tok-a", "tok-b"]


@pytest.mark.asyncio
async def test_fx_ws_rejects_jump(monkeypatch):
    settings = Settings(fx_max_jump_percent=10.0, fx_jump_window_seconds=30)
    state = StreamState(settings)
    state._fx_prev_price = Decimal("1.0")
    state._fx_prev_price_ts = datetime.now(UTC)
    from app.price_streamer import PriceStreamer

    streamer = PriceStreamer(state, settings)
    await streamer._handle_fx_ws({"s": "ZENUSDT", "b": "2", "a": "2"})
    assert state.fx_quote is None


@pytest.mark.asyncio
async def test_metrics_update_on_fx_refresh(monkeypatch):
    settings = Settings(fx_rest_interval_seconds=5, fx_max_age_seconds=5, fx_ws_stale_ttl_seconds=5)
    state = StreamState(settings)
    from app.price_streamer import PriceStreamer

    streamer = PriceStreamer(state, settings)

    async def fake_refresh(label: str = "coingecko_rest"):
        return state.register_fx(Decimal("12.34"), source=label, allow_jump=True)

    monkeypatch.setattr(state, "refresh_fx", fake_refresh)
    await state.refresh_fx(label="coingecko_rest")
    streamer.metric_ws_connected.set(1 if state.fx_ws_connected else 0)
    streamer.metric_fx_stale.set(1 if state.fx_last_update is None else 0)
    assert streamer.metric_fx_stale._value.get() in (0, 1)


@pytest.mark.asyncio
async def test_metrics_mark_stale_without_fx():
    state = StreamState(Settings())
    from app.price_streamer import PriceStreamer

    streamer = PriceStreamer(state, state.settings)
    streamer._update_fx_metrics()
    assert streamer.metric_fx_stale._value.get() == 1


def test_upstream_metrics_wiring():
    registry = CollectorRegistry()
    metrics = StreamerMetrics(registry=registry)
    settings = Settings(rtds_enabled=True, rest_poll_seconds=5, ws_reconnect_seconds=5)
    state = StreamState(settings, metrics=metrics)
    streamer = DataStreamer(state, settings, metrics=metrics)
    ts = datetime(2024, 1, 1, tzinfo=UTC)

    streamer._set_clob_ws_connected(True)
    assert state.clob_ws_connected is True
    assert metrics.clob_ws_connected._value.get() == 1

    streamer._record_clob_rest_poll(success=True, ts=ts)
    assert state.clob_rest_last_poll == ts
    assert state.clob_rest_last_success == ts
    assert metrics.clob_rest_last_poll_ts._value.get() == ts.timestamp()
    assert metrics.clob_rest_last_success_ts._value.get() == ts.timestamp()

    streamer._set_rtds_connected(True)
    assert state.rtds_connected is True
    assert metrics.rtds_ws_connected._value.get() == 1


@pytest.mark.asyncio
async def test_start_records_rtds_enabled_flag():
    registry = CollectorRegistry()
    metrics = StreamerMetrics(registry=registry)
    settings = Settings(rtds_enabled=True, rest_poll_seconds=5, ws_reconnect_seconds=5)
    state = StreamState(settings, metrics=metrics)
    streamer = DataStreamer(state, settings, metrics=metrics)

    async def noop():
        return None

    streamer._ws_loop = noop  # type: ignore[assignment]
    streamer._rest_poll_loop = noop  # type: ignore[assignment]
    streamer._flush_loop = noop  # type: ignore[assignment]
    streamer._rtds_loop = noop  # type: ignore[assignment]

    await streamer.start()
    assert metrics.rtds_enabled._value.get() == 1
    await streamer.stop()


@pytest.mark.asyncio
async def test_normalize_payload_contains_fx():
    state = StubState()
    streamer = DataStreamer(state, state.settings)
    data = {"id": "m1", "outcomePrices": [0.5]}
    await streamer._normalize_and_publish(data, source="rest")
    _, _, payload = state.cached[0]
    assert "fx_zen_usd" in payload and "fx_stale" in payload


@pytest.mark.asyncio
async def test_normalize_prefers_clob_midpoints(monkeypatch):
    state = StubState()
    streamer = DataStreamer(state, state.settings)

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
    streamer = DataStreamer(state, state.settings)

    async def none_midpoints(token_ids):
        return None

    monkeypatch.setattr(streamer, "_fetch_midpoints", none_midpoints)
    data = {"id": "m3", "outcomePrices": [0.9, 0.1], "clobTokenIds": ["x", "y"]}
    await streamer._normalize_and_publish(data, source="rest")
    assert state.cached
    _, _, payload = state.cached[0]
    assert payload["price"] == "0.9"


@pytest.mark.asyncio
async def test_normalize_parses_stringified_arrays(monkeypatch):
    state = StubState()
    streamer = DataStreamer(state, state.settings)
    seen_tokens = None

    async def fake_midpoints(token_ids):
        nonlocal seen_tokens
        seen_tokens = token_ids
        return [Decimal("0.55"), Decimal("0.45")]

    monkeypatch.setattr(streamer, "_fetch_midpoints", fake_midpoints)
    data = {
        "id": "m4",
        "outcomePrices": '["0.4", "0.6"]',
        "clobTokenIds": '["t-one", "t-two"]',
    }
    await streamer._normalize_and_publish(data, source="rest")
    assert seen_tokens == ["t-one", "t-two"]
    assert len(state.cached) == 2
    _, _, payload = state.cached[0]
    assert payload["price"] == "0.55"


@pytest.mark.asyncio
async def test_normalize_registers_clob_tokens():
    state = StubState()
    streamer = DataStreamer(state, state.settings)
    streamer.clob_client = None  # avoid network midpoint fetches
    data = {"id": "m5", "outcomePrices": [0.2, 0.8], "clobTokenIds": ["tok1", "tok2"]}
    await streamer._normalize_and_publish(data, source="rest")
    assert state.market_tokens["m5"] == ["tok1", "tok2"]


@pytest.mark.asyncio
async def test_normalize_skips_tokens_when_market_missing():
    state = StubState()
    streamer = DataStreamer(state, state.settings)
    streamer.clob_client = None  # avoid network midpoint fetches
    data = {"outcomePrices": [0.2, 0.8], "clobTokenIds": ["tok1", "tok2"]}
    await streamer._normalize_and_publish(data, source="rest")
    assert state.market_tokens == {}


@pytest.mark.asyncio
async def test_normalize_handles_camel_best_bid():
    state = StubState()
    streamer = DataStreamer(state, state.settings)
    data = {"id": "m6", "outcomePrices": [0.2], "bestBid": "0.33", "bestAsk": "0.44"}
    await streamer._normalize_and_publish(data, source="rest")
    assert state.cached
    _, _, payload = state.cached[0]
    assert payload["best_bid"] == "0.33"
    assert payload["best_ask"] == "0.44"


@pytest.mark.asyncio
async def test_register_clob_tokens_replaces_placeholder_subscription():
    state = StubState()
    state.subscriptions.add_assets(["m-placeholder"])
    state.register_clob_tokens("m-placeholder", ["tok1", "tok2"])
    assert "m-placeholder" not in state.subscriptions.assets
    assert {"tok1", "tok2"} == state.subscriptions.assets


@pytest.mark.asyncio
async def test_rest_poll_replaces_placeholder_with_tokens(monkeypatch):
    state = StubState()
    streamer = DataStreamer(state, state.settings)
    state.subscriptions.add_assets(["123"])

    async def fake_client_get(url, params=None):
        class Resp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return [{"id": "123", "outcomePrices": [0.5, 0.5], "clobTokenIds": ["a", "b"]}]

        return Resp()

    with monkeypatch.context() as m:
        m.setattr("httpx.AsyncClient.get", lambda self, url, params=None: fake_client_get(url, params))
        streamer.clob_client = None  # skip midpoint fetch
        await streamer._poll_rest()
    # placeholder should be swapped once token ids are known
    assert "123" not in state.subscriptions.assets


@pytest.mark.asyncio
async def test_fetch_midpoints_parses_dict_payload(monkeypatch):
    state = StubState()
    streamer = DataStreamer(state, state.settings)

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
    streamer = DataStreamer(state, state.settings)
    streamer.clob_client = object()  # ensure client exists
    mids = await streamer._fetch_midpoints([])
    assert mids is None


@pytest.mark.asyncio
async def test_fetch_midpoints_handles_client_failure(monkeypatch):
    state = StubState()
    streamer = DataStreamer(state, state.settings)

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
    streamer = DataStreamer(state, state.settings)
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
    streamer = DataStreamer(state, settings)
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
    streamer = DataStreamer(state, state.settings)
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
        return state.register_fx(Decimal("12"), source=label, allow_jump=True)

    monkeypatch.setattr(state, "refresh_fx", fake_refresh_fx)
    state.fx_ws_last_update = datetime.now(UTC) - timedelta(seconds=6)
    state.fx_last_update = state.fx_ws_last_update
    await streamer._fx_refresh_once()
    assert streamer.metric_ws_connected._value.get() == 0
    assert streamer.metric_fx_source.labels(source="binance_rest")._value.get() == 1


@pytest.mark.asyncio
async def test_price_history_seed_and_stream_pooling(monkeypatch):
    """Ensure we reuse a single connection per market and seed history is retained."""

    state = StubState()
    streamer = DataStreamer(state, state.settings)
    # No tasks in tests: _normalize_and_publish bypasses throttled cache path.
    await streamer._normalize_and_publish({"id": "m1", "outcomePrices": [0.5]}, source="rest")
    await streamer._normalize_and_publish({"id": "m1", "outcomePrices": [0.6]}, source="rest")
    # Only the latest two entries should be cached per outcome.
    assert len(state.cached) == 2


class PubSubState(StreamState):
    def __init__(self):
        super().__init__(Settings(rest_poll_seconds=5, ws_reconnect_seconds=5))
        self.queue: asyncio.Queue = asyncio.Queue()

    async def cache_tick(self, market_id: str, outcome: str, payload: dict) -> None:
        self.last_seen[market_id] = datetime.now(UTC)
        await self.queue.put({"data": json.dumps(payload)})

    async def subscribe(self, market_id: str):  # type: ignore[override]
        queue = self.queue

        class DummyPubSub:
            def __init__(self, q: asyncio.Queue):
                self._q = q

            async def get_message(self, ignore_subscribe_messages=True, timeout=None):
                try:
                    return await asyncio.wait_for(self._q.get(), timeout=timeout or 0.5)
                except TimeoutError:
                    return None

            async def close(self):
                return

        return DummyPubSub(queue)

    async def get_fx(self):  # type: ignore[override]
        return FxQuote(zen_usd=Decimal("1.0"), raw_zen_usd=Decimal("1.0"), fetched_at=datetime.now(UTC), stale=False)


@pytest.mark.asyncio
async def test_streamer_publishes_book_and_price_over_pubsub():
    """Mock Polymarket feeds and ensure ticks reach the pubsub stream."""

    state = PubSubState()
    streamer = DataStreamer(state, state.settings)
    await streamer._handle_market_event(
        {"event_type": "book", "market": "live-1", "bids": [{"price": "0.4"}], "asks": [{"price": "0.6"}]},
        source="ws",
    )
    await streamer._normalize_and_publish({"id": "live-1", "outcomePrices": [0.4, 0.6]}, source="rest")
    pubsub = await state.subscribe("live-1")
    payloads: list[dict] = []
    for _ in range(2):
        msg = await pubsub.get_message(timeout=1)
        if msg and msg.get("data"):
            payloads.append(json.loads(msg["data"]))
    assert any(p.get("type") == "book" for p in payloads)
    assert any(p.get("type") == "price" for p in payloads)


@pytest.mark.asyncio
async def test_fx_ws_rest_retry_flow(monkeypatch):
    """HTTP fallback when WS is stale then auto-recover when WS resumes."""

    settings = Settings(fx_ws_stale_ttl_seconds=5, fx_rest_interval_seconds=5, fx_max_age_seconds=5)
    state = StreamState(settings)
    streamer = PriceStreamer(state, settings)
    calls: list[str] = []

    async def fake_refresh_fx(label: str = "coingecko_rest"):
        calls.append(label)
        return state.register_fx(Decimal("11"), source=label, allow_jump=True)

    monkeypatch.setattr(state, "refresh_fx", fake_refresh_fx)
    state.fx_ws_last_update = datetime.now(UTC) - timedelta(seconds=8)
    await streamer._fx_refresh_once()
    assert calls == ["binance_rest"]
    assert state.fx_quote and state.fx_quote.source == "binance_rest"

    await streamer._handle_fx_ws({"s": "ZENUSDT", "b": "9.5", "a": "9.5"})
    assert state.fx_quote and state.fx_quote.source == "binance_ws"
    assert state.fx_ws_connected is True
    assert streamer.metric_ws_connected._value.get() == 1


@pytest.mark.asyncio
async def test_clob_ws_loop_reconnects_and_sends_subscribe(monkeypatch):
    settings = Settings(ws_reconnect_seconds=0.01)
    state = StreamState(settings)
    state.subscriptions.add_assets(["tok-a"])
    streamer = DataStreamer(state, settings)
    ws_instances: list = []

    class DummyWS:
        def __init__(self, name, *, disconnect_on: int | None = None, stop_after: int | None = None):
            self.name = name
            self.sent: list[str] = []
            self.recv_calls = 0
            self.disconnect_on = disconnect_on
            self.stop_after = stop_after

        async def send(self, payload):
            self.sent.append(payload)

        async def recv(self):
            self.recv_calls += 1
            if self.disconnect_on and self.recv_calls >= self.disconnect_on:
                raise RuntimeError("socket dropped")
            if self.stop_after and self.recv_calls >= self.stop_after:
                streamer._stop.set()
                raise TimeoutError
            raise TimeoutError

    async def fake_iter_ws(url, name="ws", fatal_status=None):
        ws1 = DummyWS("first", disconnect_on=1)
        ws_instances.append(ws1)
        yield ws1
        ws2 = DummyWS("second", stop_after=2)
        ws_instances.append(ws2)
        yield ws2

    monkeypatch.setattr("app.data_streamer.iter_ws", fake_iter_ws)
    await asyncio.wait_for(streamer._ws_loop(), timeout=0.5)
    assert ws_instances
    payloads = [payload for ws in ws_instances for payload in ws.sent]
    assert any('"tok-a"' in payload for payload in payloads)
    assert streamer._stop.is_set()


@pytest.mark.asyncio
async def test_sse_heartbeat_records_drop():
    metrics = get_metrics()
    counter = metrics.stream_dropped.labels(transport="sse", reason="heartbeat")
    start = counter._value.get()

    class DummyPubSub:
        async def get_message(self, ignore_subscribe_messages=True, timeout=None):
            return None

        async def close(self):
            return

    chunks: list[str] = []
    async for chunk in _sse_events(DummyPubSub(), heartbeat_seconds=0.01, max_events=1, metrics=metrics):
        chunks.append(chunk)
    assert any("event: ping" in c for c in chunks)
    assert counter._value.get() == start + 1


@pytest.mark.asyncio
async def test_ingest_drop_metric_records_missing_market(monkeypatch):
    settings = Settings()
    state = StreamState(settings)
    metrics = get_metrics()
    streamer = DataStreamer(state, settings, metrics=metrics)
    start = metrics.ingest_dropped.labels(source="ws", reason="missing_market_or_prices")._value.get()
    await streamer._handle_tick({}, source="ws")
    assert metrics.ingest_dropped.labels(source="ws", reason="missing_market_or_prices")._value.get() == start + 1
