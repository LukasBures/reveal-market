from __future__ import annotations

from decimal import Decimal
from time import sleep

import app.main as api_main
from eth_account import Account


def test_quote_issue_and_submit_with_caps_and_fx(client, monkeypatch, db_session):
    # Configure signer and caps
    signer = Account.create()
    user = Account.create()
    monkeypatch.setattr(api_main.settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(api_main.settings, "pricing_signer_private_key", signer._private_key.hex(), raising=False)
    monkeypatch.setattr(api_main.settings, "max_user_stake_per_market_zen", 15.0, raising=False)
    monkeypatch.setattr(api_main.settings, "max_market_stake_zen", 20.0, raising=False)

    # Stable FX
    monkeypatch.setattr("app.main.fetch_fx_price_sync", lambda *a, **k: (Decimal("10"), False))

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
    assert "cap" in quote_resp2.json()["detail"].lower()


def test_quote_expires_and_sweeper_marks_expired(client, monkeypatch):
    signer = Account.create()
    user = Account.create()
    monkeypatch.setattr(api_main.settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(api_main.settings, "pricing_signer_private_key", signer._private_key.hex(), raising=False)
    monkeypatch.setattr(api_main.settings, "pricing_quote_ttl_seconds", 1, raising=False)
    monkeypatch.setattr(api_main.settings, "quote_expiry_sweep_interval_seconds", 1, raising=False)
    monkeypatch.setattr("app.main.fetch_fx_price_sync", lambda *a, **k: (Decimal("5"), False))

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

    # Let it expire
    sleep(1.2)
    # Trigger sweeper loop once
    api_main._quote_sweeper_loop(api_main._quote_sweeper_stop_event or api_main.Event(), run_once=True)

    submit = client.post("/pricing/submit", json={"quote": quote})
    assert submit.status_code == 400
    assert "expired" in submit.json()["detail"]
