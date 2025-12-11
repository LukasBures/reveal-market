from __future__ import annotations

from decimal import Decimal

from app import models
from app.config import get_settings
from app.schemas import FxQuoteResponse
from pydantic import SecretStr


def _mock_fx(monkeypatch, price: float = 2.5):
    async def _fx_quote(*_args, **_kwargs):
        return FxQuoteResponse(zen_usd=Decimal(str(price)), stale=False, received_at=None)

    monkeypatch.setattr("app.main.fetch_fx_quote", _fx_quote)
    monkeypatch.setattr("app.pricing.fetch_fx_quote", _fx_quote)


def _configure_signer():
    settings = get_settings()
    settings.pricing_chain_id = 1337
    settings.pricing_signer_private_key = SecretStr(
        "0x4c0883a69102937d6231471b5dbb6204fe512961708279fe52e05f728621f081"
    )


def test_pricing_quote_persists_and_consumes(client, db_session, monkeypatch):
    _configure_signer()
    _mock_fx(monkeypatch, price=1.5)
    settings = get_settings()
    settings.max_stake_zen = 10

    payload = {
        "stake_zen": 5.0,
        "market_id": "evt-quote-test",
        "user_id": "user-123",
        "wallet_address": "0x00000000000000000000000000000000000000aa",
        "market_address": "0x00000000000000000000000000000000000000bb",
        "outcome_id": 0,
    }

    response = client.post("/pricing/quote", json=payload)
    assert response.status_code == 200, response.json()
    quote = response.json()
    quote_id = quote["quote_id"]

    record = db_session.get(models.Quote, quote_id)
    assert record is not None
    assert record.status == models.QuoteStatusEnum.ISSUED.value
    assert float(record.stake_zen) == payload["stake_zen"]

    submit_payload = {"quote": quote}
    submit_response = client.post("/pricing/submit", json=submit_payload)
    assert submit_response.status_code == 200

    db_session.refresh(record)
    assert record.status == models.QuoteStatusEnum.CONSUMED.value

    admin_response = client.get(f"/pricing/quotes/{quote_id}")
    assert admin_response.status_code == 200
    admin_body = admin_response.json()
    assert admin_body["status"] == models.QuoteStatusEnum.CONSUMED.value
