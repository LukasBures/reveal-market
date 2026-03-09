from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import app.server as api_main
import pytest
from app import models
from app.schemas import FxQuoteResponse
from eth_account import Account


def test_quote_issue_and_submit_returns_signed_payload(client, monkeypatch, db_session):
    signer = Account.create()
    user = Account.create()
    monkeypatch.setattr(api_main.settings, "pricing_chain_id", 26514, raising=False)
    monkeypatch.setattr(api_main.settings, "pricing_signer_private_key", signer._private_key.hex(), raising=False)
    monkeypatch.setattr(api_main.settings, "max_stake_zen", 10.0, raising=False)
    monkeypatch.setattr(api_main.settings, "haircut_percent", 0.12, raising=False)
    monkeypatch.setattr(api_main.settings, "pricing_edge_percent", 0.05, raising=False)
    monkeypatch.setattr(api_main.settings, "ticket_size_wei", int(Decimal("1e17")), raising=False)

    async def _fx_quote(*_args, **_kwargs):
        return FxQuoteResponse(zen_usd=Decimal("10"), stale=False, received_at=None)

    monkeypatch.setattr("app.routes.pricing.fetch_fx_quote", _fx_quote)

    async def _streamer_price(*_args, **_kwargs):
        return Decimal("0.5")

    monkeypatch.setattr("app.routes.pricing._fetch_streamer_price", _streamer_price)

    payload = {
        "stake_zen": 0.1,
        "wallet_address": user.address,
        "market_address": "0x1111111111111111111111111111111111111111",
        "outcome_id": 0,
        "market_id": "mkt-simple",
    }

    quote_resp = client.post("/pricing/quote", json=payload)
    assert quote_resp.status_code == 200, quote_resp.text
    quote = quote_resp.json()
    assert quote["quote_id"]
    assert quote["signature"]
    assert quote["signer"].lower() == signer.address.lower()
    assert quote["payout_zen"] > 0
    assert quote["stake_wei"] == int(Decimal("1e17"))

    submit_resp = client.post("/pricing/submit", json={"quote": quote})
    assert submit_resp.status_code == 200, submit_resp.text
    assert submit_resp.json()["valid"] is True

    record = db_session.get(models.Quote, quote["quote_id"])
    assert record is not None
    assert record.status == models.QuoteStatusEnum.CONSUMED.value


def test_quote_expires_and_sweeper_marks_expired(client, monkeypatch, db_session):
    signer = Account.create()
    user = Account.create()
    monkeypatch.setattr(api_main.settings, "pricing_chain_id", 26514, raising=False)
    monkeypatch.setattr(api_main.settings, "pricing_signer_private_key", signer._private_key.hex(), raising=False)
    monkeypatch.setattr(api_main.settings, "pricing_quote_ttl_seconds", 1, raising=False)
    monkeypatch.setattr(api_main.settings, "quote_expiry_sweep_interval_seconds", 1, raising=False)
    monkeypatch.setattr(api_main.settings, "max_stake_zen", 10.0, raising=False)
    monkeypatch.setattr(api_main.settings, "haircut_percent", 0.12, raising=False)
    monkeypatch.setattr(api_main.settings, "pricing_edge_percent", 0.05, raising=False)
    monkeypatch.setattr(api_main.settings, "ticket_size_wei", int(Decimal("1e17")), raising=False)

    async def _fx_quote(*_args, **_kwargs):
        return FxQuoteResponse(zen_usd=Decimal("5"), stale=False, received_at=None)

    monkeypatch.setattr("app.routes.pricing.fetch_fx_quote", _fx_quote)

    async def _streamer_price(*_args, **_kwargs):
        return Decimal("0.5")

    monkeypatch.setattr("app.routes.pricing._fetch_streamer_price", _streamer_price)

    payload = {
        "stake_zen": 0.1,
        "wallet_address": user.address,
        "market_address": "0x1111111111111111111111111111111111111111",
        "outcome_id": 0,
        "market_id": "mkt-2",
    }
    quote = client.post("/pricing/quote", json=payload).json()
    assert quote["quote_id"]

    # Force expiry without waiting in real time.
    record = db_session.get(models.Quote, quote["quote_id"])
    assert record is not None
    record.expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
    db_session.add(record)
    db_session.commit()

    asyncio.run(api_main._quote_sweeper_loop(run_once=True))
    db_session.refresh(record)
    assert record.status == models.QuoteStatusEnum.EXPIRED.value

    submit = client.post("/pricing/submit", json={"quote": quote})
    assert submit.status_code == 400
    assert "expired" in submit.json()["detail"]


def test_cap_edges_enforced_and_reported(client, monkeypatch):
    signer = Account.create()
    user = Account.create()
    other_user = Account.create()
    monkeypatch.setattr(api_main.settings, "pricing_chain_id", 26514, raising=False)
    monkeypatch.setattr(api_main.settings, "pricing_signer_private_key", signer._private_key.hex(), raising=False)
    monkeypatch.setattr(api_main.settings, "max_stake_zen", 0.1, raising=False)
    monkeypatch.setattr(api_main.settings, "max_user_stake_per_market_zen", 0.15, raising=False)
    monkeypatch.setattr(api_main.settings, "max_market_stake_zen", 0.2, raising=False)
    monkeypatch.setattr(api_main.settings, "haircut_percent", 0.12, raising=False)
    monkeypatch.setattr(api_main.settings, "pricing_edge_percent", 0.05, raising=False)
    monkeypatch.setattr(api_main.settings, "ticket_size_wei", int(Decimal("1e17")), raising=False)
    now_ts = datetime.now(tz=UTC)

    async def _fx_quote_cap(*_args, **_kwargs):
        return FxQuoteResponse(zen_usd=Decimal("10"), stale=False, received_at=now_ts)

    monkeypatch.setattr("app.routes.pricing.fetch_fx_quote", _fx_quote_cap)

    async def _streamer_price(*_args, **_kwargs):
        return Decimal("0.5")

    monkeypatch.setattr("app.routes.pricing._fetch_streamer_price", _streamer_price)

    base_payload = {
        "stake_zen": 0.1,
        "wallet_address": user.address,
        "market_address": "0x1111111111111111111111111111111111111111",
        "outcome_id": 1,
        "market_id": "cap-mkt",
    }

    # At-cap bet should succeed and surface remaining limits.
    first_quote = client.post("/pricing/quote", json=base_payload)
    assert first_quote.status_code == 200, first_quote.json()
    data = first_quote.json()
    assert data["remaining_user_stake_zen"] == pytest.approx(0.05)
    assert data["remaining_market_stake_zen"] == pytest.approx(0.1)

    # Exceed user cap with another ticket should error and include remaining_user_stake_zen.
    user_over = dict(base_payload, stake_zen=0.1)
    resp_user = client.post("/pricing/quote", json=user_over)
    assert resp_user.status_code == 400
    detail = resp_user.json()["detail"]
    assert detail["error"] == "user_market_cap_exceeded"
    assert detail["remaining_user_stake_zen"] == pytest.approx(0.05)

    # Another user places a valid bet, reaching the market cap.
    valid_other = dict(base_payload, stake_zen=0.1, wallet_address=other_user.address)
    resp_valid_other = client.post("/pricing/quote", json=valid_other)
    assert resp_valid_other.status_code == 200, resp_valid_other.json()

    # Market cap breach with different user.
    market_over = dict(base_payload, stake_zen=0.1, wallet_address=other_user.address)
    resp_market = client.post("/pricing/quote", json=market_over)
    assert resp_market.status_code == 400
    m_detail = resp_market.json()["detail"]
    assert m_detail["error"] == "market_cap_exceeded"
    assert m_detail["remaining_market_stake_zen"] == pytest.approx(0.0)
