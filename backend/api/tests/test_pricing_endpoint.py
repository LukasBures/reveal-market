from __future__ import annotations

import httpx
from pydantic import SecretStr


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


def test_pricing_quote_and_submit_signature_roundtrip(client, monkeypatch):
    # Force deterministic FX and signer env.
    from app.config import get_settings
    from eth_account import Account

    signer = Account.create()
    user = Account.create()
    settings = get_settings()
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "pricing_signer_private_key", SecretStr(signer._private_key.hex()), raising=False)
    monkeypatch.setattr("app.main.settings", settings, raising=False)
    monkeypatch.setattr("app.main.fetch_fx_price_sync", lambda *a, **k: (10, False))

    class DummySyncResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"price": 10, "stale": False}

    monkeypatch.setattr("app.main.httpx.get", lambda *a, **k: DummySyncResponse())

    quote_payload = {
        "stake_zen": 10,
        "wallet_address": user.address,
        "market_address": "0x1111111111111111111111111111111111111111",
        "outcome_id": 1,
        "market_id": "mkt-1",
        "user_id": "user-1",
    }
    quote_resp = client.post("/pricing/quote", json=quote_payload)
    assert quote_resp.status_code == 200
    quote = quote_resp.json()
    assert quote["signature"]
    assert quote["chain_id"] == 2651420

    submit_resp = client.post("/pricing/submit", json={"quote": quote})
    assert submit_resp.status_code == 200
    submit_body = submit_resp.json()
    assert submit_body["valid"] is True
    assert submit_body["quote"]["quote_id"] == quote["quote_id"]
