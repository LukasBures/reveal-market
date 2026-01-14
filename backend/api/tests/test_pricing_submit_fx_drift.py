from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import app.runtime as runtime
import pytest
from app.schemas import FxQuoteResponse
from eth_account import Account
from pydantic import SecretStr


async def _streamer_price(*_args, **_kwargs):
    return Decimal("0.5")


@pytest.mark.asyncio
async def test_pricing_submit_rejects_fx_drift(client, monkeypatch):
    signer = Account.create()
    user = Account.create()
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "pricing_signer_private_key", SecretStr(signer._private_key.hex()), raising=False)
    monkeypatch.setattr(settings, "max_stake_zen", 1, raising=False)
    monkeypatch.setattr(settings, "haircut_percent", 0.12, raising=False)
    monkeypatch.setattr(settings, "pricing_edge_percent", 0.05, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", int(Decimal("1e17")), raising=False)

    now_ts = datetime.now(tz=UTC)

    async def _fx_quote(*_args, **_kwargs):
        return FxQuoteResponse(zen_usd=Decimal("10"), stale=False, received_at=now_ts)

    async def _fx_quote_drift(*_args, **_kwargs):
        return FxQuoteResponse(zen_usd=Decimal("12"), stale=False, received_at=now_ts)

    monkeypatch.setattr("app.routes.pricing.fetch_fx_quote", _fx_quote)
    monkeypatch.setattr("app.routes.pricing._fetch_streamer_price", _streamer_price)

    payload = {
        "stake_zen": 0.1,
        "wallet_address": user.address,
        "market_address": "0x1111111111111111111111111111111111111111",
        "outcome_id": 0,
        "market_id": "fx-drift",
    }

    quote_resp = client.post("/pricing/quote", json=payload)
    assert quote_resp.status_code == 200, quote_resp.text
    quote = quote_resp.json()

    monkeypatch.setattr("app.routes.pricing.fetch_fx_quote", _fx_quote_drift)
    submit_resp = client.post(
        "/pricing/submit",
        json={"quote": quote, "max_fx_diff_percent": 1},
    )
    assert submit_resp.status_code == 409
    assert "FX drift" in submit_resp.json()["detail"]


@pytest.mark.asyncio
async def test_pricing_submit_rejects_stale_fx(client, monkeypatch):
    signer = Account.create()
    user = Account.create()
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "pricing_signer_private_key", SecretStr(signer._private_key.hex()), raising=False)
    monkeypatch.setattr(settings, "max_stake_zen", 1, raising=False)
    monkeypatch.setattr(settings, "haircut_percent", 0.12, raising=False)
    monkeypatch.setattr(settings, "pricing_edge_percent", 0.05, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", int(Decimal("1e17")), raising=False)

    now_ts = datetime.now(tz=UTC)

    async def _fx_quote(*_args, **_kwargs):
        return FxQuoteResponse(zen_usd=Decimal("10"), stale=False, received_at=now_ts)

    async def _fx_quote_stale(*_args, **_kwargs):
        return FxQuoteResponse(zen_usd=Decimal("10"), stale=True, received_at=now_ts)

    monkeypatch.setattr("app.routes.pricing.fetch_fx_quote", _fx_quote)
    monkeypatch.setattr("app.routes.pricing._fetch_streamer_price", _streamer_price)

    payload = {
        "stake_zen": 0.1,
        "wallet_address": user.address,
        "market_address": "0x1111111111111111111111111111111111111111",
        "outcome_id": 0,
        "market_id": "fx-stale",
    }

    quote_resp = client.post("/pricing/quote", json=payload)
    assert quote_resp.status_code == 200, quote_resp.text
    quote = quote_resp.json()

    monkeypatch.setattr("app.routes.pricing.fetch_fx_quote", _fx_quote_stale)
    submit_resp = client.post(
        "/pricing/submit",
        json={"quote": quote, "max_fx_diff_percent": 1},
    )
    assert submit_resp.status_code == 503
    assert submit_resp.json()["detail"]["error"] == "fx_stale"
