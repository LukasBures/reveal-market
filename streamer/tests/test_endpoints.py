from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.config import Settings
from app.main import create_app
from app.state import FxQuote, StreamState
from fastapi.testclient import TestClient


@pytest.fixture()
def test_app(monkeypatch):
    # Use in-memory state with no Redis connection.
    state = StreamState()
    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)
    now = datetime.now(UTC)
    state.fx_quote = FxQuote(
        zen_usd=Decimal("1.0"),
        raw_zen_usd=Decimal("1.0"),
        fetched_at=now,
        stale=False,
        source="test",
    )
    state.fx_last_update = now

    # Avoid starting real streamer/network loops in tests.
    class DummyStreamer:
        def __init__(self, *_args, **_kwargs): ...

        async def start(self): ...

        async def stop(self): ...

    async def noop():
        return None

    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]
    monkeypatch.setattr("app.main.DataStreamer", lambda *_args, **_kwargs: DummyStreamer())
    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())
    app = create_app()
    with TestClient(app) as client:
        yield client, state


def test_health_endpoint_reports_fx(test_app):
    client, _ = test_app
    resp = client.get("/health")
    assert resp.status_code == 200
    payload = resp.json()
    assert "fx_zen_usd" in payload
    assert "status" in payload


def test_health_status_stale(monkeypatch):
    settings = Settings(market_stale_seconds=60)
    state = StreamState(settings)
    state.fx_quote = FxQuote(
        zen_usd=1, fetched_at=datetime.now(UTC) - timedelta(seconds=120), stale=True, source="test"
    )
    state.fx_last_update = state.fx_quote.fetched_at
    state.fx_ws_connected = False
    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    class DummyStreamer:
        def __init__(self, *_args, **_kwargs): ...

        async def start(self): ...

        async def stop(self): ...

    async def noop():
        return None

    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]
    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.json()["status"] == "stale"


def test_health_status_degraded(monkeypatch):
    settings = Settings(market_stale_seconds=10)
    state = StreamState(settings)
    state.fx_quote = FxQuote(zen_usd=1, fetched_at=datetime.now(UTC), stale=False, source="test")
    state.fx_last_update = state.fx_quote.fetched_at
    state.fx_ws_connected = True
    state.last_seen["m1"] = datetime.now(UTC) - timedelta(seconds=120)
    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    class DummyStreamer:
        def __init__(self, *_args, **_kwargs): ...

        async def start(self): ...

        async def stop(self): ...

    async def noop():
        return None

    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]
    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.json()["status"] == "degraded"


def test_fx_endpoint(monkeypatch):
    settings = Settings()
    state = StreamState(settings)
    now = datetime.now(UTC)
    expected = Decimal("2") * (Decimal("1") - Decimal(str(settings.worsen_percent)))
    state.fx_quote = FxQuote(
        zen_usd=expected, raw_zen_usd=Decimal("2"), fetched_at=now, stale=False, source="binance_ws"
    )
    state.fx_last_update = now
    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    class DummyStreamer:
        def __init__(self, *_args, **_kwargs): ...

        async def start(self): ...

        async def stop(self): ...

    async def noop():
        return None

    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]
    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/fx/zen-usd")
        payload = resp.json()
        assert payload["pair"] == "ZEN/USDC"
        expected = float(2 * (1 - settings.worsen_percent))
        assert payload["zen_usd"] == expected
        assert payload["raw_zen_usd"] == 2.0
        alias = client.get("/data/fx")
        assert alias.status_code == 200


def test_subscriptions_endpoint(monkeypatch):
    settings = Settings()
    state = StreamState(settings)
    state.subscriptions.add_assets(["a1", "a2"])
    state.rtds_symbols.add("zenusdt")
    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    class DummyStreamer:
        def __init__(self, *_args, **_kwargs): ...

        async def start(self): ...

        async def stop(self): ...

    async def noop():
        return None

    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]
    monkeypatch.setattr("app.main.DataStreamer", lambda *_args, **_kwargs: DummyStreamer())
    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/subscriptions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert "zenusdt" in data["symbols"]


def test_stream_endpoint_connects(test_app):
    client, state = test_app

    # Set up a dummy redis pubsub to avoid actual Redis.
    class DummyPubSub:
        async def get_message(self, ignore_subscribe_messages=True, timeout=None):
            await asyncio.sleep(0.01)
            return None

        async def close(self):
            return

    async def fake_subscribe(market_id: str):
        return DummyPubSub()

    state.subscribe = fake_subscribe  # type: ignore[assignment]
    with client.stream("GET", "/stream", params={"market_id": "m1", "max_events": 1, "heartbeat": 1}) as resp:
        assert resp.status_code == 200
        # Subscription should have been registered at least once.
        assert "m1" in state._acquired_history
        for _ in resp.iter_lines():
            break


def test_stream_websocket_sends_messages(test_app):
    client, state = test_app

    class DummyPubSub:
        def __init__(self):
            import asyncio

            self.queue = asyncio.Queue()

        async def get_message(self, ignore_subscribe_messages=True, timeout=None):
            import asyncio

            try:
                return await asyncio.wait_for(self.queue.get(), timeout=timeout)
            except TimeoutError:
                return None

        async def close(self):
            return

        def feed(self, data: str):
            self.queue.put_nowait({"data": data})

    pubsub = DummyPubSub()

    async def fake_subscribe(market_id: str):
        return pubsub

    state.subscribe = fake_subscribe  # type: ignore[assignment]

    with client.websocket_connect("/stream/ws?market_id=m1&heartbeat=1") as ws:
        # Seed a tick for the websocket loop to forward.
        pubsub.feed('{"market_id":"m1","price":"0.42"}')
        incoming = ws.receive_text()
        if "ping" in incoming:
            incoming = ws.receive_text()
        assert '"price":"0.42"' in incoming
    # Subscription should have been registered at least once.
    assert "m1" in state._acquired_history


def test_dashboard_endpoint(monkeypatch):
    settings = Settings()
    state = StreamState(settings)
    now = datetime.now(UTC)
    state.fx_quote = FxQuote(
        zen_usd=Decimal("1.25"),
        raw_zen_usd=Decimal("1.25"),
        fetched_at=now,
        stale=False,
        source="test",
    )
    state.fx_last_update = now
    state.last_seen["dash-m1"] = now
    state.last_published["dash-m1"] = now

    async def noop():
        return None

    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]
    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)

    class DummyStreamer:
        async def start(self): ...

        async def stop(self): ...

    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["subscriptions"]["count"] == 0
        assert "fx" in payload
        assert "dash-m1" in payload["last_seen"]


def test_control_subscription_endpoints(monkeypatch):
    settings = Settings(control_token="secret", max_subscriptions=2)  # noqa: S106
    state = StreamState(settings)
    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    class DummyStreamer:
        async def start(self): ...

        async def stop(self): ...

    async def noop():
        return None

    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]

    class DummyPubSub:
        async def get_message(self, ignore_subscribe_messages=True, timeout=None):
            await asyncio.sleep(0.01)
            return None

        async def close(self):
            return

    async def fake_subscribe(market_id: str):
        return DummyPubSub()

    state.subscribe = fake_subscribe  # type: ignore[assignment]

    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())
    monkeypatch.setattr("app.main.DataStreamer", lambda *_args, **_kwargs: DummyStreamer())
    app = create_app()
    with TestClient(app) as client:
        # Unauthorized without token
        assert client.get("/control/subscriptions").status_code == 403
        # Add assets/symbols
        resp = client.post(
            "/control/subscriptions",
            headers={"x-control-token": "secret"},
            params=[("assets_ids", "a1"), ("symbols", "sym1")],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "a1" in data["assets"]
        assert "sym1" in data["symbols"]
        # Remove assets/symbols
        resp = client.delete(
            "/control/subscriptions",
            headers={"x-control-token": "secret"},
            params=[("assets_ids", "a1"), ("symbols", "sym1")],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["assets"] == []
        assert data["symbols"] == []


def test_access_token_and_connection_cap(monkeypatch):
    settings = Settings(access_token="tok", max_active_connections=1)  # noqa: S106
    state = StreamState(settings)
    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    class DummyStreamer:
        async def start(self): ...

        async def stop(self): ...

    async def noop():
        return None

    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]

    class DummyPubSub:
        async def get_message(self, ignore_subscribe_messages=True, timeout=None):
            return None

        async def close(self):
            return

    async def fake_subscribe(market_id: str):
        return DummyPubSub()

    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())
    monkeypatch.setattr("app.main.DataStreamer", lambda *_args, **_kwargs: DummyStreamer())
    app = create_app()
    with TestClient(app) as client:
        state.subscribe = fake_subscribe  # ensure patched after app creation
        # missing token
        assert client.get("/stream", params={"market_id": "m1"}).status_code == 403
        # valid token
        resp = client.get("/stream", params={"market_id": "m1", "max_events": 1}, headers={"x-access-token": "tok"})
        assert resp.status_code == 200
        # exceed connection cap
        state.active_connections = settings.max_active_connections
        assert client.get("/stream", params={"market_id": "m2"}, headers={"x-access-token": "tok"}).status_code == 429


def test_ws_requires_access_token(monkeypatch):
    settings = Settings(access_token="tok", rate_limit_per_minute=2)  # noqa: S106
    state = StreamState(settings)
    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    class DummyStreamer:
        async def start(self): ...

        async def stop(self): ...

    class DummyPubSub:
        async def get_message(self, ignore_subscribe_messages=True, timeout=None):
            # Mimic redis pubsub timeout so the websocket loop sends a heartbeat and yields.
            if timeout:
                import asyncio

                await asyncio.sleep(timeout)
            return None

        async def close(self):
            return

    async def fake_subscribe(market_id: str):
        return DummyPubSub()

    state.subscribe = fake_subscribe  # type: ignore[assignment]
    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())
    monkeypatch.setattr("app.main.DataStreamer", lambda *_args, **_kwargs: DummyStreamer())

    async def noop():
        return None

    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]
    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect("/stream/ws?market_id=m1&heartbeat=1", headers={"x-access-token": "tok"}) as ws:
            msg = ws.receive_json()
            assert "ping" in msg.get("event", "")


def test_rate_limit_overflow(monkeypatch):
    settings = Settings(rate_limit_per_minute=1)
    state = StreamState(settings)
    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    class DummyStreamer:
        async def start(self): ...

        async def stop(self): ...

    async def fake_subscribe(market_id: str):
        class DummyPubSub:
            async def get_message(self, ignore_subscribe_messages=True, timeout=None):
                await asyncio.sleep(0.01)
                return None

            async def close(self):
                return

        return DummyPubSub()

    state.subscribe = fake_subscribe  # type: ignore[assignment]
    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())
    monkeypatch.setattr("app.main.DataStreamer", lambda *_args, **_kwargs: DummyStreamer())

    async def noop():
        return None

    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/stream", params={"market_id": "m1", "max_events": 1})
        assert resp.status_code == 200
        resp2 = client.get("/stream", params={"market_id": "m1", "max_events": 1})
        assert resp2.status_code == 429
