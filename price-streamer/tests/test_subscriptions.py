from __future__ import annotations

from app.subscriptions import SubscriptionManager


def test_subscription_manager_payloads_and_limits():
    manager = SubscriptionManager(max_items=2)
    manager.add_assets(["a1", "a2", "a3"])
    # Respects max_items cap.
    assert manager.build_clob_subscribe() == '{"assets_ids": ["a1", "a2"], "type": "market"}'

    manager.add_rtds_topic("crypto_prices", "update", "zenusdt")
    manager.add_rtds_topic("crypto_prices", "update", "btcusdt")
    manager.add_rtds_topic("crypto_prices", "update", "ethusdt")  # capped at 2
    payload = manager.build_rtds_subscribe()
    assert "crypto_prices" in payload
    # Should only have two topics due to max_items cap.
    assert payload.count("crypto_prices") == 2
