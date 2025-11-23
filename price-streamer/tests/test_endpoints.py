from __future__ import annotations

import asyncio

import pytest
from app.main import create_app
from app.state import StreamState
from fastapi.testclient import TestClient


@pytest.fixture()
def test_app(monkeypatch):
    # Use in-memory state with no Redis connection.
    state = StreamState()
    monkeypatch.setattr("app.main.StreamState", lambda settings=None: state)
    app = create_app()
    with TestClient(app) as client:
        yield client, state


def test_health_endpoint_reports_fx(test_app):
    client, _ = test_app
    resp = client.get("/health")
    assert resp.status_code == 200
    payload = resp.json()
    assert "fx_zen_usd" in payload


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
        for _ in resp.iter_lines():
            break
