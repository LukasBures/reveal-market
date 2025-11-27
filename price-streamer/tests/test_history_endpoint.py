from __future__ import annotations

import pytest
from app.main import create_app
from app.state import StreamState
from fastapi.testclient import TestClient


class StubState(StreamState):
    def __init__(self):
        super().__init__()

    async def get_history(self, market_id: str, outcome: str, limit: int):
        return [
            {"market_id": market_id, "outcome": outcome, "price": "0.5", "display_price": "0.48", "timestamp": "t1"},
            {"market_id": market_id, "outcome": outcome, "price": "0.6", "display_price": "0.58", "timestamp": "t2"},
        ]


@pytest.fixture()
def history_client(monkeypatch):
    state = StubState()
    monkeypatch.setattr("app.main.StreamState", lambda settings=None: state)
    # Avoid spinning up real network streamer in tests.
    class DummyStreamer:
        async def start(self): ...

        async def stop(self): ...

    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())
    app = create_app()
    with TestClient(app) as client:
        yield client


def test_history_endpoint_returns_records(history_client):
    resp = history_client.get("/history", params={"market_id": "m1", "outcome": 0, "limit": 2})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["market_id"] == "m1"
    assert payload["count"] == 2
    assert isinstance(payload["data"], list)
