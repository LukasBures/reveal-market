from __future__ import annotations

import pytest
from app.config import Settings
from app.main import create_app
from app.state import StreamState
from fastapi.testclient import TestClient

from tests.test_utils import DummyStreamer, noop


class DummySubgraph:
    async def fetch_markets(self, **_kwargs):
        return [{"id": "m1"}]

    async def fetch_trades(self, **_kwargs):
        return [{"id": "t1"}]

    async def fetch_positions(self, **_kwargs):
        return [{"id": "p1"}]

    async def fetch_open_interest(self, **_kwargs):
        return [{"id": "oi1"}]

    async def fetch_pnl(self, **_kwargs):
        return [{"id": "pnl1"}]

    async def fetch_global_open_interest(self, **_kwargs):
        return [{"id": "goi1"}]

    async def fetch_activity(self, **_kwargs):
        return {"splits": [{"id": "s1"}], "merges": [{"id": "m1"}], "redemptions": [{"id": "r1"}]}

    async def fetch_market_data(self, **_kwargs):
        return [{"id": "md1"}]


@pytest.fixture()
def subgraph_app(monkeypatch):
    """Create a TestClient with mocked streamer/subgraph dependencies for subgraph tests."""

    settings = Settings(subgraph_default_url="https://example.com/subgraph")
    state = StreamState(settings)
    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]

    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.main.DataStreamer", lambda *_args, **_kwargs: DummyStreamer())
    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())
    dummy_subgraph = DummySubgraph()
    monkeypatch.setattr("app.main.SubgraphClient", lambda *_args, **_kwargs: dummy_subgraph)
    app = create_app()
    with TestClient(app) as client:
        yield client


def test_subgraph_markets_endpoint(subgraph_app):
    resp = subgraph_app.get("/subgraph/markets")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["count"] == 1
    assert payload["data"][0]["id"] == "m1"
    alias = subgraph_app.get("/data/subgraph/markets")
    assert alias.status_code == 200


def test_subgraph_trades_endpoint(subgraph_app):
    resp = subgraph_app.get("/subgraph/trades", params={"asset_ids": "a1"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["asset_ids"] == ["a1"]
    assert payload["count"] == 1


def test_subgraph_positions_endpoint(subgraph_app):
    resp = subgraph_app.get("/subgraph/positions", params={"user": "0xabc"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["user"] == "0xabc"
    assert payload["count"] == 1


def test_subgraph_open_interest_endpoint(subgraph_app):
    resp = subgraph_app.get("/subgraph/open-interest", params={"market_id": "m1"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["market_id"] == "m1"
    assert payload["count"] == 1


def test_subgraph_pnl_endpoint(subgraph_app):
    resp = subgraph_app.get("/subgraph/pnl", params={"user": "0xabc"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["user"] == "0xabc"
    assert payload["count"] == 1


def test_subgraph_global_oi_endpoint(subgraph_app):
    resp = subgraph_app.get("/subgraph/open-interest/global")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["count"] == 1
    alias = subgraph_app.get("/data/subgraph/open-interest/global")
    assert alias.status_code == 200


def test_subgraph_activity_endpoint(subgraph_app):
    resp = subgraph_app.get("/subgraph/activity")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["data"]["splits"][0]["id"] == "s1"


def test_subgraph_market_data_endpoint(subgraph_app):
    resp = subgraph_app.get("/subgraph/market-data")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["data"][0]["id"] == "md1"


def test_subgraph_ws_endpoints(subgraph_app):
    with subgraph_app.websocket_connect("/subgraph/ws/markets") as ws:
        message = ws.receive_json()
        assert message["data"][0]["id"] == "m1"
    with subgraph_app.websocket_connect("/subgraph/ws/trades?asset_ids=a1") as ws:
        message = ws.receive_json()
        assert message["data"][0]["id"] == "t1"
    with subgraph_app.websocket_connect("/subgraph/ws/positions?user=0xabc") as ws:
        message = ws.receive_json()
        assert message["data"][0]["id"] == "p1"
    with subgraph_app.websocket_connect("/subgraph/ws/open-interest?market_id=m1") as ws:
        message = ws.receive_json()
        assert message["data"][0]["id"] == "oi1"
    with subgraph_app.websocket_connect("/subgraph/ws/pnl?user=0xabc") as ws:
        message = ws.receive_json()
        assert message["data"][0]["id"] == "pnl1"
    with subgraph_app.websocket_connect("/subgraph/ws/open-interest/global") as ws:
        message = ws.receive_json()
        assert message["data"][0]["id"] == "goi1"
    with subgraph_app.websocket_connect("/subgraph/ws/activity") as ws:
        message = ws.receive_json()
        assert message["data"]["splits"][0]["id"] == "s1"
    with subgraph_app.websocket_connect("/subgraph/ws/market-data") as ws:
        message = ws.receive_json()
        assert message["data"][0]["id"] == "md1"


def test_subgraph_ws_clamps_first_and_skip(monkeypatch):
    settings = Settings(subgraph_default_url="https://example.com/subgraph")
    state = StreamState(settings)
    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]
    seen: list[dict] = []

    class DummySubgraph:
        async def fetch_markets(self, **kwargs):
            seen.append(kwargs)
            return [{"id": "m1"}]

    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.main.DataStreamer", lambda *_args, **_kwargs: DummyStreamer())
    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())
    monkeypatch.setattr("app.main.SubgraphClient", lambda *_args, **_kwargs: DummySubgraph())
    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect(
            "/subgraph/ws/markets?first=999999&skip=999999",
        ) as ws:
            message = ws.receive_json()
            assert message["data"][0]["id"] == "m1"
    assert seen
    assert seen[0]["first"] == 200
    assert seen[0]["skip"] == settings.subgraph_ws_max_skip


def test_subgraph_not_configured_returns_503(monkeypatch):
    settings = Settings(
        subgraph_default_url=None,
        subgraph_markets_url=None,
        subgraph_trades_url=None,
        subgraph_positions_url=None,
        subgraph_open_interest_url=None,
        subgraph_pnl_url=None,
    )
    state = StreamState(settings)

    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]

    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.main.DataStreamer", lambda *_args, **_kwargs: DummyStreamer())
    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/subgraph/markets")
        assert resp.status_code == 503
        body = resp.json()
        assert isinstance(body, dict)
        assert "detail" in body
        assert isinstance(body["detail"], str) and body["detail"]


def test_subgraph_http_error_surfaces_details(monkeypatch):
    settings = Settings(subgraph_default_url="https://example.com/subgraph")
    state = StreamState(settings)

    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]

    class DummySubgraph:
        async def fetch_markets(self, **_kwargs):
            import httpx

            request = httpx.Request("POST", "https://example.com/subgraph")
            response = httpx.Response(502, request=request)
            raise httpx.HTTPStatusError("bad gateway", request=request, response=response)

    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.main.DataStreamer", lambda *_args, **_kwargs: DummyStreamer())
    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())
    monkeypatch.setattr("app.main.SubgraphClient", lambda *_args, **_kwargs: DummySubgraph())
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/subgraph/markets")
        assert resp.status_code == 502
        payload = resp.json()
        assert payload["detail"]["error"] == "subgraph_http_error"
        assert payload["detail"]["status_code"] == 502
        assert "url" not in payload["detail"]


def test_subgraph_http_routes_apply_rate_limit(monkeypatch):
    settings = Settings(
        subgraph_default_url="https://example.com/subgraph",
        rate_limit_per_minute=1,
    )
    state = StreamState(settings)
    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]

    class DummySubgraph:
        async def fetch_markets(self, **_kwargs):
            return [{"id": "m1"}]

    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.main.DataStreamer", lambda *_args, **_kwargs: DummyStreamer())
    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())
    monkeypatch.setattr("app.main.SubgraphClient", lambda *_args, **_kwargs: DummySubgraph())
    app = create_app()
    with TestClient(app) as client:
        first = client.get("/subgraph/markets")
        second = client.get("/subgraph/markets")
        assert first.status_code == 200
        assert second.status_code == 429


def test_subgraph_ws_routes_apply_rate_limit(monkeypatch):
    settings = Settings(
        subgraph_default_url="https://example.com/subgraph",
        rate_limit_per_minute=1,
    )
    state = StreamState(settings)
    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]

    class DummySubgraph:
        async def fetch_markets(self, **_kwargs):
            return [{"id": "m1"}]

    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.main.DataStreamer", lambda *_args, **_kwargs: DummyStreamer())
    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())
    monkeypatch.setattr("app.main.SubgraphClient", lambda *_args, **_kwargs: DummySubgraph())
    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect("/subgraph/ws/markets") as ws1:
            message = ws1.receive_json()
            assert message["data"][0]["id"] == "m1"
        with client.websocket_connect("/subgraph/ws/markets") as ws2:
            message = ws2.receive_json()
            assert message["error"] == "subgraph_rate_limited"
