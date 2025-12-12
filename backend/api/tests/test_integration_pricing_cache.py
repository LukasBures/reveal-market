from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import app.server as api_main
import pytest
from app import models
from app.schemas import FxQuoteResponse
from eth_account import Account


def test_quote_issue_and_submit_with_caps_and_fx(client, monkeypatch, db_session):
    # Configure signer and caps
    signer = Account.create()
    user = Account.create()
    monkeypatch.setattr(api_main.settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(api_main.settings, "pricing_signer_private_key", signer._private_key.hex(), raising=False)
    monkeypatch.setattr(api_main.settings, "max_user_stake_per_market_zen", 15.0, raising=False)
    monkeypatch.setattr(api_main.settings, "max_market_stake_zen", 20.0, raising=False)
    monkeypatch.setattr(api_main.settings, "max_stake_zen", 20.0, raising=False)

    # Stable FX
    async def _fx_quote(*_args, **_kwargs):
        return FxQuoteResponse(zen_usd=Decimal("10"), stale=False, received_at=None)

    monkeypatch.setattr("app.routes.pricing.fetch_fx_quote", _fx_quote)

    # Issue quote
    quote_payload = {
        "stake_zen": 5,
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
    assert quote["stake_wei"] > 0

    # Submit quote (should succeed)
    submit_resp = client.post("/pricing/submit", json={"quote": quote})
    assert submit_resp.status_code == 200
    assert submit_resp.json()["valid"] is True

    # Issue another quote that exceeds caps (market cap 20 -> already consumed 10)
    quote_payload["stake_zen"] = 15
    quote_resp2 = client.post("/pricing/quote", json=quote_payload)
    assert quote_resp2.status_code == 400
    detail = quote_resp2.json()["detail"]
    if isinstance(detail, str):
        assert "cap" in detail.lower()
    else:
        assert detail.get("error") in {"user_market_cap_exceeded", "market_cap_exceeded", "stake_above_cap"}


def test_quote_expires_and_sweeper_marks_expired(client, monkeypatch, db_session):
    signer = Account.create()
    user = Account.create()
    monkeypatch.setattr(api_main.settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(api_main.settings, "pricing_signer_private_key", signer._private_key.hex(), raising=False)
    monkeypatch.setattr(api_main.settings, "pricing_quote_ttl_seconds", 1, raising=False)
    monkeypatch.setattr(api_main.settings, "quote_expiry_sweep_interval_seconds", 1, raising=False)
    monkeypatch.setattr(api_main.settings, "max_stake_zen", 10.0, raising=False)

    async def _fx_quote(*_args, **_kwargs):
        return FxQuoteResponse(zen_usd=Decimal("5"), stale=False, received_at=None)

    monkeypatch.setattr("app.routes.pricing.fetch_fx_quote", _fx_quote)

    payload = {
        "stake_zen": 1,
        "wallet_address": user.address,
        "market_address": "0x1111111111111111111111111111111111111111",
        "outcome_id": 0,
        "market_id": "mkt-2",
        "user_id": "user-2",
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
    monkeypatch.setattr(api_main.settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(api_main.settings, "pricing_signer_private_key", signer._private_key.hex(), raising=False)
    monkeypatch.setattr(api_main.settings, "max_stake_zen", 0.1, raising=False)
    monkeypatch.setattr(api_main.settings, "max_user_stake_per_market_zen", 0.15, raising=False)
    monkeypatch.setattr(api_main.settings, "max_market_stake_zen", 0.2, raising=False)
    now_ts = datetime.now(tz=UTC)

    async def _fx_quote_cap(*_args, **_kwargs):
        return FxQuoteResponse(zen_usd=Decimal("10"), stale=False, received_at=now_ts)

    monkeypatch.setattr("app.routes.pricing.fetch_fx_quote", _fx_quote_cap)

    base_payload = {
        "stake_zen": 0.1,
        "wallet_address": user.address,
        "market_address": "0x1111111111111111111111111111111111111111",
        "outcome_id": 1,
        "market_id": "cap-mkt",
        "user_id": "user-cap-1",
    }

    # At-cap bet should succeed and surface remaining limits.
    first_quote = client.post("/pricing/quote", json=base_payload)
    assert first_quote.status_code == 200, first_quote.json()
    data = first_quote.json()
    assert data["remaining_user_stake_zen"] == pytest.approx(0.05)
    assert data["remaining_market_stake_zen"] == pytest.approx(0.1)

    # Above per-bet cap should be rejected with structured error.
    over_bet = dict(base_payload, stake_zen=0.11, user_id="user-cap-2", wallet_address=other_user.address)
    resp = client.post("/pricing/quote", json=over_bet)
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "stake_above_cap"

    # Exceed user cap should error and include remaining_user_stake_zen.
    user_over = dict(base_payload, stake_zen=0.06)
    resp_user = client.post("/pricing/quote", json=user_over)
    assert resp_user.status_code == 400
    detail = resp_user.json()["detail"]
    assert detail["error"] == "user_market_cap_exceeded"
    assert detail["remaining_user_stake_zen"] == pytest.approx(0.05)

    # Another user places a valid bet, pushing market totals near the cap.
    valid_other = dict(base_payload, stake_zen=0.08, user_id="user-cap-2b", wallet_address=other_user.address)
    resp_valid_other = client.post("/pricing/quote", json=valid_other)
    assert resp_valid_other.status_code == 200, resp_valid_other.json()

    # Market cap breach with different user.
    market_over = dict(base_payload, stake_zen=0.05, user_id="user-cap-3", wallet_address=other_user.address)
    resp_market = client.post("/pricing/quote", json=market_over)
    assert resp_market.status_code == 400
    m_detail = resp_market.json()["detail"]
    assert m_detail["error"] == "market_cap_exceeded"
    assert m_detail["remaining_market_stake_zen"] == pytest.approx(0.02)
