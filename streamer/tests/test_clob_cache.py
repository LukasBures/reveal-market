from __future__ import annotations

import pytest
from app.main import create_app
from app.state import StreamState
from fastapi.testclient import TestClient

from tests.test_utils import DummyStreamer, noop


class StubCacheState(StreamState):
    def __init__(self):
        super().__init__()
        self.redis = object()

    async def get_latest(self, market_id: str, outcome: str):
        return {"market_id": market_id, "outcome": outcome, "price": "0.5"}


@pytest.fixture()
def clob_client(monkeypatch):
    state = StubCacheState()

    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]

    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)
    monkeypatch.setattr("app.main.get_settings", lambda: state.settings)
    monkeypatch.setattr("app.main.DataStreamer", lambda *_args, **_kwargs: DummyStreamer())
    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())
    app = create_app()
    with TestClient(app) as client:
        yield client


def test_clob_latest_endpoint(clob_client):
    resp = clob_client.get("/clob/latest", params={"market_id": "m1", "outcome": "1"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["market_id"] == "m1"
    assert payload["outcome"] == "1"
    assert payload["data"]["price"] == "0.5"
    alias = clob_client.get("/data/clob/latest", params={"market_id": "m1", "outcome": "1"})
    assert alias.status_code == 200


def test_clob_book_endpoint(clob_client):
    resp = clob_client.get("/clob/book", params={"market_id": "m1"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["market_id"] == "m1"
    assert payload["data"]["outcome"] == "meta"
    alias = clob_client.get("/data/clob/book", params={"market_id": "m1"})
    assert alias.status_code == 200
