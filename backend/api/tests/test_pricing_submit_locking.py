from __future__ import annotations

from decimal import Decimal

from app.schemas import FxQuoteResponse
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession


def _configure_signer(monkeypatch):
    import app.runtime as runtime

    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "pricing_signer_private_key", SecretStr("0x" + "2" * 64), raising=False)
    monkeypatch.setattr(settings, "max_stake_zen", 1, raising=False)
    monkeypatch.setattr(settings, "max_user_stake_per_market_zen", 10, raising=False)
    monkeypatch.setattr(settings, "max_market_stake_zen", 100, raising=False)
    monkeypatch.setattr(settings, "haircut_percent", 0.12, raising=False)
    monkeypatch.setattr(settings, "pricing_edge_percent", 0.05, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", int(Decimal("1e17")), raising=False)

    return settings


def _mock_fx(monkeypatch, price: Decimal = Decimal("10")) -> None:
    async def _fx_quote(*_args, **_kwargs):
        return FxQuoteResponse(zen_usd=price, stale=False, received_at=None)

    monkeypatch.setattr("app.routes.pricing.fetch_fx_quote", _fx_quote)
    monkeypatch.setattr("app.pricing.fetch_fx_quote", _fx_quote)
    monkeypatch.setattr("app.routes.pricing._fetch_streamer_price", _streamer_price)


async def _streamer_price(*_args, **_kwargs):
    return Decimal("0.5")


def _issue_quote(client):
    payload = {
        "stake_zen": 0.1,
        "market_id": "evt-lock-test",
        "user_id": "user-lock",
        "wallet_address": "0x00000000000000000000000000000000000000aa",
        "market_address": "0x00000000000000000000000000000000000000bb",
        "outcome_id": 0,
    }
    response = client.post("/pricing/quote", json=payload)
    assert response.status_code == 200, response.json()
    return response.json()


def test_pricing_submit_double_consumption_rejected(client, monkeypatch):
    _configure_signer(monkeypatch)
    _mock_fx(monkeypatch)

    quote = _issue_quote(client)
    submit_payload = {"quote": quote}
    assert client.post("/pricing/submit", json=submit_payload).status_code == 200

    second = client.post("/pricing/submit", json=submit_payload)
    assert second.status_code == 409


def test_pricing_submit_uses_row_lock(client, monkeypatch):
    _configure_signer(monkeypatch)
    _mock_fx(monkeypatch)

    quote = _issue_quote(client)
    for_update_seen = {"value": False}
    original_execute = AsyncSession.execute

    async def execute_with_flag(self, statement, *args, **kwargs):
        if getattr(statement, "_for_update_arg", None) is not None:
            for_update_seen["value"] = True
        return await original_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", execute_with_flag, raising=False)

    submit_payload = {"quote": quote}
    response = client.post("/pricing/submit", json=submit_payload)
    assert response.status_code == 200, response.text
    assert for_update_seen["value"] is True


def test_pricing_submit_rejects_market_id_mismatch(client, monkeypatch):
    _configure_signer(monkeypatch)
    _mock_fx(monkeypatch)

    quote = _issue_quote(client)
    quote["market_id"] = "tampered-market"
    response = client.post("/pricing/submit", json={"quote": quote})
    assert response.status_code == 400
    assert response.json()["detail"] == "Quote market id mismatch"
