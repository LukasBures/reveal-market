from __future__ import annotations

import math


def test_pricing_quote_success(client):
    response = client.post("/pricing/quote", json={"stake_zen": 10, "zen_usd": 0.2})
    assert response.status_code == 200
    payload = response.json()
    assert math.isclose(payload["displayed_odds_multiplier"], 0.97, rel_tol=1e-6)
    assert math.isclose(payload["rake_zen"], 0.2, rel_tol=1e-6)
    assert math.isclose(payload["refund_zen"], 9.8, rel_tol=1e-6)
    assert math.isclose(payload["hedge_usdc"], 1.76, rel_tol=1e-6)
    assert math.isclose(payload["total_monetisation"], 0.17, rel_tol=1e-6)


def test_pricing_quote_requires_fx_price(client):
    response = client.post("/pricing/quote", json={"stake_zen": 5})
    assert response.status_code == 503
