from __future__ import annotations

from decimal import Decimal

from app import models
from app.config import get_settings
from app.schemas import FxQuoteResponse
from eth_account import Account
from eth_account.messages import encode_defunct
from pydantic import SecretStr


def _mock_fx(monkeypatch, price: float = 2.5):
    async def _fx_quote(*_args, **_kwargs):
        return FxQuoteResponse(zen_usd=Decimal(str(price)), stale=False, received_at=None)

    monkeypatch.setattr("app.routes.pricing.fetch_fx_quote", _fx_quote)
    monkeypatch.setattr("app.pricing.fetch_fx_quote", _fx_quote)


def _mock_streamer_price(monkeypatch, price: float = 0.5):
    async def _streamer(*_args, **_kwargs):
        from decimal import Decimal

        return Decimal(str(price))

    monkeypatch.setattr("app.routes.pricing._fetch_streamer_price", _streamer)


def _configure_signer():
    settings = get_settings()
    settings.pricing_chain_id = 1337
    settings.pricing_signer_private_key = SecretStr(
        "0x4c0883a69102937d6231471b5dbb6204fe512961708279fe52e05f728621f081"
    )
    import app.runtime as runtime

    runtime.settings.pricing_chain_id = settings.pricing_chain_id
    runtime.settings.pricing_signer_private_key = settings.pricing_signer_private_key
    return settings


def test_pricing_quote_persists_and_consumes(client, db_session, monkeypatch):
    settings = _configure_signer()
    _mock_fx(monkeypatch, price=1.5)
    _mock_streamer_price(monkeypatch, price=0.5)
    settings.max_stake_zen = 0.1
    settings.haircut_percent = 0.12
    settings.pricing_edge_percent = 0.05
    settings.ticket_size_wei = int(Decimal("1e17"))
    import app.runtime as runtime

    runtime.settings.max_stake_zen = settings.max_stake_zen
    runtime.settings.ticket_size_wei = settings.ticket_size_wei

    user = Account.create()
    payload = {
        "stake_zen": 0.1,
        "market_id": "evt-quote-test",
        "user_id": "user-123",
        "wallet_address": user.address,
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
    unauthorized_submit = client.post("/pricing/submit", json=submit_payload, headers={"X-Internal-Secret": ""})
    assert unauthorized_submit.status_code == 401
    submit_signature = Account.sign_message(
        encode_defunct(text=f"quote-submit:{quote_id}:{user.address.lower()}"),
        user._private_key,
    ).signature.hex()
    submit_response = client.post(
        "/pricing/submit",
        json=submit_payload,
        headers={"X-Internal-Secret": "", "X-Wallet-Signature": submit_signature},
    )
    assert submit_response.status_code == 200

    db_session.refresh(record)
    assert record.status == models.QuoteStatusEnum.CONSUMED.value

    unauth_state = client.get(f"/pricing/quotes/{quote_id}", headers={"X-Internal-Secret": ""})
    assert unauth_state.status_code == 400
    state_signature = Account.sign_message(
        encode_defunct(text=f"quote-state:{quote_id}:{user.address.lower()}"),
        user._private_key,
    ).signature.hex()
    wallet_state = client.get(
        f"/pricing/quotes/{quote_id}?wallet={user.address}",
        headers={"X-Internal-Secret": "", "X-Wallet-Signature": state_signature},
    )
    assert wallet_state.status_code == 200

    admin_response = client.get(f"/pricing/quotes/{quote_id}")
    assert admin_response.status_code == 200
    admin_body = admin_response.json()
    assert admin_body["status"] == models.QuoteStatusEnum.CONSUMED.value
