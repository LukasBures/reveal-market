from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from app import models
from app.schemas import FxQuoteResponse
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
    payload = {
        "horizen": {"usd": 7.5},
        "stale": False,
        "received_at": "2024-01-01T00:00:00Z",
    }
    monkeypatch.setattr("app.pricing.httpx.AsyncClient", lambda *args, **kwargs: _AsyncClientSuccess(payload))

    resp = client.get("/pricing/fx")
    assert resp.status_code == 200
    data = resp.json()
    assert data["zen_usd"] == 7.5
    assert data["stale"] is False
    assert data["received_at"].startswith("2024-01-01")


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
    resp = client.get("/pricing/fx")
    assert resp.status_code == 503
    data = resp.json()
    assert data["detail"]["error"] == "fx_unavailable"


def test_pricing_fx_rejects_stale_payload(client, monkeypatch):
    payload = {"price": 7.0, "stale": True, "received_at": "2024-02-02T00:00:00Z"}
    monkeypatch.setattr("app.pricing.httpx.AsyncClient", lambda *args, **kwargs: _AsyncClientSuccess(payload))

    resp = client.get("/pricing/fx")
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "fx_stale"


def test_pricing_quote_and_submit_signature_roundtrip(client, monkeypatch):
    # Force deterministic FX and signer env.
    import app.runtime as runtime
    from eth_account import Account

    signer = Account.create()
    user = Account.create()
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "pricing_signer_private_key", SecretStr(signer._private_key.hex()), raising=False)
    monkeypatch.setattr(settings, "max_stake_zen", 20, raising=False)
    monkeypatch.setattr(settings, "max_user_stake_per_market_zen", 100, raising=False)
    monkeypatch.setattr(settings, "max_market_stake_zen", 1000, raising=False)

    async def _fx_quote(*_args, **_kwargs):
        return FxQuoteResponse(zen_usd=Decimal("10"), stale=False, received_at=None)

    monkeypatch.setattr("app.routes.pricing.fetch_fx_quote", _fx_quote)

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


def test_pricing_quote_signature_recovers_signer(client, monkeypatch):
    import app.runtime as runtime
    from app.server import build_quote_digest
    from eth_account import Account
    from eth_account.messages import encode_defunct
    from pydantic import SecretStr

    signer = Account.create()
    user = Account.create()
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "pricing_signer_private_key", SecretStr(signer._private_key.hex()), raising=False)
    monkeypatch.setattr(settings, "max_stake_zen", 10, raising=False)
    monkeypatch.setattr(settings, "max_user_stake_per_market_zen", 100, raising=False)
    monkeypatch.setattr(settings, "max_market_stake_zen", 1000, raising=False)

    async def _fx_quote(*_args, **_kwargs):
        return FxQuoteResponse(zen_usd=Decimal("10"), stale=False, received_at=None)

    monkeypatch.setattr("app.routes.pricing.fetch_fx_quote", _fx_quote)

    quote_payload = {
        "stake_zen": 5,
        "wallet_address": user.address,
        "market_address": "0x1111111111111111111111111111111111111111",
        "outcome_id": 0,
        "market_id": "mkt-2",
        "user_id": "user-2",
    }
    resp = client.post("/pricing/quote", json=quote_payload)
    assert resp.status_code == 200
    quote = resp.json()

    digest = build_quote_digest(
        settings.pricing_chain_id,
        quote["market_address"],
        quote["wallet_address"],
        int(quote["outcome_id"]),
        int(quote["stake_wei"]),
        int(quote["zen_usd_scaled"]),
        int(quote["expiry_ts"]),
        quote["quote_id"],
    )
    recovered = Account.recover_message(encode_defunct(hexstr=digest.hex()), signature=quote["signature"])
    assert recovered.lower() == signer.address.lower()


def test_pricing_quote_rejects_stale_fx(client, monkeypatch):
    from app.config import get_settings
    from eth_account import Account

    signer = Account.create()
    user = Account.create()
    settings = get_settings()
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "pricing_signer_private_key", SecretStr(signer._private_key.hex()), raising=False)
    monkeypatch.setattr(settings, "max_stake_zen", 1, raising=False)
    monkeypatch.setattr("app.server.settings", settings, raising=False)
    now_ts = datetime.now(tz=UTC)

    async def _fx_quote(*_args, **_kwargs):
        return FxQuoteResponse(zen_usd=Decimal("10"), stale=True, received_at=now_ts)

    monkeypatch.setattr("app.routes.pricing.fetch_fx_quote", _fx_quote)

    payload = {
        "stake_zen": 0.1,
        "wallet_address": user.address,
        "market_address": "0x2222222222222222222222222222222222222222",
        "outcome_id": 0,
        "market_id": "stale-mkt",
        "user_id": "stale-user",
    }
    resp = client.post("/pricing/quote", json=payload)
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "fx_stale"


def test_pricing_quote_blocks_pending_resolution(client, db_session, monkeypatch):
    import app.runtime as runtime
    from eth_account import Account

    signer = Account.create()
    user = Account.create()
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "pricing_signer_private_key", SecretStr(signer._private_key.hex()), raising=False)
    monkeypatch.setattr(settings, "max_stake_zen", 5, raising=False)
    market = models.Market(
        event_id="pending-market",
        title="Pending market",
        oracle="0xoracle",
        status=models.MarketStatusEnum.COMMIT.value,
        resolution_status=models.ResolutionStatusEnum.PENDING.value,
        market_address="0x1111111111111111111111111111111111111111",
    )
    db_session.add(market)
    db_session.commit()

    payload = {
        "stake_zen": 0.1,
        "wallet_address": user.address,
        "market_address": market.market_address,
        "outcome_id": 0,
        "market_id": market.event_id,
        "user_id": "user-pending",
    }
    resp = client.post("/pricing/quote", json=payload)
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "market_resolution_pending"
    assert detail["resolution_status"] == models.ResolutionStatusEnum.PENDING.value


def test_pricing_quote_blocks_cutoff_window(client, db_session, monkeypatch):
    import app.runtime as runtime
    from eth_account import Account

    signer = Account.create()
    user = Account.create()
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "pricing_signer_private_key", SecretStr(signer._private_key.hex()), raising=False)
    monkeypatch.setattr(settings, "max_stake_zen", 5, raising=False)
    monkeypatch.setattr(settings, "commit_cutoff_seconds", 300, raising=False)
    market = models.Market(
        event_id="cutoff-market",
        title="Cutoff market",
        oracle="0xoracle",
        status=models.MarketStatusEnum.COMMIT.value,
        closes_at=datetime.now(tz=UTC) + timedelta(seconds=120),
        market_address="0x2222222222222222222222222222222222222222",
    )
    db_session.add(market)
    db_session.commit()

    payload = {
        "stake_zen": 0.1,
        "wallet_address": user.address,
        "market_address": market.market_address,
        "outcome_id": 1,
        "market_id": market.event_id,
        "user_id": "user-cutoff",
    }
    resp = client.post("/pricing/quote", json=payload)
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "market_near_resolution"
    assert detail["closes_at"]
