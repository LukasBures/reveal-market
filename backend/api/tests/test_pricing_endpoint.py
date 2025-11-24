from __future__ import annotations

import httpx


class _AsyncClientSuccess:
    def __init__(self, payload: dict):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False

    async def get(self, *args, **kwargs):
        return _DummyResponse(self.payload)


class _DummyResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_pricing_fx_parses_nested_payload(client, monkeypatch):
    payload = {"horizen": {"usd": 7.5}, "stale": True}
    monkeypatch.setattr("app.pricing.httpx.AsyncClient", lambda *args, **kwargs: _AsyncClientSuccess(payload))

    resp = client.get("/pricing/fx")
    assert resp.status_code == 200
    data = resp.json()
    assert data["zen_usd"] == 7.5
    assert data["stale"] is True


def test_pricing_fx_falls_back_on_http_error(client, monkeypatch):
    class FailingAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

        async def get(self, *args, **kwargs):
            raise httpx.HTTPError("boom")

    monkeypatch.setattr("app.pricing.httpx.AsyncClient", FailingAsyncClient)
    from app.config import get_settings

    settings = get_settings()
    resp = client.get("/pricing/fx")
    assert resp.status_code == 200
    data = resp.json()
    assert data["stale"] is True
    assert data["zen_usd"] == settings.fx_fallback_price
