from __future__ import annotations

import app.server as api_main


def test_clob_orderbook_endpoint(client, monkeypatch):
    api_main.settings.clob_host = "https://clob.example"

    class DummyClobClient:
        def __init__(self, host: str):
            self.host = host

        def get_order_book(self, token_id: str):
            return {
                "market": "mkt-1",
                "asset_id": token_id,
                "bids": [{"price": "0.5", "size": "10"}],
                "asks": [{"price": "0.6", "size": "12"}],
                "timestamp": "2025-01-01T00:00:00+00:00",
                "min_order_size": "5",
                "tick_size": "0.01",
                "hash": "abc123",
            }

    monkeypatch.setattr("app.routes.markets.ClobClient", DummyClobClient)

    resp = client.get("/clob/orderbook/token-1")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["asset_id"] == "token-1"
    assert payload["bids"][0]["price"] == "0.5"
    assert payload["asks"][0]["size"] == "12"


def test_clob_orderbook_missing_host_returns_503(client, monkeypatch):
    api_main.settings.clob_host = None
    resp = client.get("/clob/orderbook/token-1")
    assert resp.status_code == 503


def test_clob_orderbook_handles_downstream_failure(client, monkeypatch):
    api_main.settings.clob_host = "https://clob.example"

    class FailingClient:
        def __init__(self, host: str):
            self.host = host

        def get_order_book(self, token_id: str):
            raise ValueError("boom")

    monkeypatch.setattr("app.routes.markets.ClobClient", FailingClient)
    resp = client.get("/clob/orderbook/token-err")
    assert resp.status_code == 502
