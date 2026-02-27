from __future__ import annotations

import asyncio

import app.server as api_main
from app.rate_limit import RATE_LIMIT_COUNTER
from app.routes import pricing as pricing_module


def enable_rate_limit(
    monkeypatch,
    *,
    limit: int = 2,
    window: int = 60,
    whitelist: list[str] | None = None,
    trusted_proxies: list[str] | None = None,
) -> None:
    monkeypatch.setattr(api_main.settings, "rate_limit_enabled", True, raising=False)
    monkeypatch.setattr(api_main.settings, "rate_limit_requests_per_window", limit, raising=False)
    monkeypatch.setattr(api_main.settings, "rate_limit_window_seconds", window, raising=False)
    monkeypatch.setattr(api_main.settings, "rate_limit_whitelist", whitelist or [], raising=False)
    monkeypatch.setattr(api_main.settings, "rate_limit_trusted_proxies", trusted_proxies or [], raising=False)
    asyncio.run(api_main.rate_limiter.reset())


def test_rate_limit_blocks_after_threshold(client, monkeypatch):
    enable_rate_limit(monkeypatch, limit=2, window=60)

    response1 = client.get("/events")
    response2 = client.get("/events")
    response3 = client.get("/events")

    assert response1.status_code == 200
    assert response2.status_code == 200
    assert response1.headers["X-RateLimit-Limit"] == "2"
    assert response3.status_code == 429
    assert response3.json()["detail"] == "rate_limit_exceeded"
    assert response3.headers["X-RateLimit-Limit"] == "2"
    assert response3.headers["X-RateLimit-Remaining"] == "0"
    assert "Retry-After" in response3.headers


def test_rate_limit_whitelist_allows_requests(client, monkeypatch):
    enable_rate_limit(monkeypatch, limit=1, window=60, whitelist=["127.0.0.1"])

    response1 = client.get("/events")
    response2 = client.get("/events")

    assert response1.status_code == 200
    assert response2.status_code == 200
    assert "X-RateLimit-Limit" in response1.headers


def test_rate_limit_disabled_does_not_block(client, monkeypatch):
    monkeypatch.setattr(api_main.settings, "rate_limit_enabled", False, raising=False)
    asyncio.run(api_main.rate_limiter.reset())

    responses = [client.get("/events") for _ in range(3)]
    assert all(response.status_code == 200 for response in responses)


def test_rate_limit_metrics_increment(client, monkeypatch):
    enable_rate_limit(monkeypatch, limit=1, window=60)
    allowed_before = RATE_LIMIT_COUNTER.labels(outcome="allowed")._value.get()
    blocked_before = RATE_LIMIT_COUNTER.labels(outcome="blocked")._value.get()

    first = client.get("/events")
    second = client.get("/events")

    assert first.status_code == 200
    assert second.status_code == 429

    allowed_after = RATE_LIMIT_COUNTER.labels(outcome="allowed")._value.get()
    blocked_after = RATE_LIMIT_COUNTER.labels(outcome="blocked")._value.get()

    assert allowed_after - allowed_before == 1
    assert blocked_after - blocked_before == 1


def test_rate_limit_trusted_proxy_uses_forwarded_for(client, monkeypatch):
    enable_rate_limit(monkeypatch, limit=1, window=60, trusted_proxies=["testclient"])

    headers_a = {"X-Forwarded-For": "203.0.113.1"}
    headers_b = {"X-Forwarded-For": "203.0.113.1"}
    headers_c = {"X-Forwarded-For": "203.0.113.2"}

    assert client.get("/events", headers=headers_a).status_code == 200
    assert client.get("/events", headers=headers_b).status_code == 429
    assert client.get("/events", headers=headers_c).status_code == 200


def test_rate_limit_untrusted_proxy_ignores_forwarded_for(client, monkeypatch):
    enable_rate_limit(monkeypatch, limit=1, window=60, trusted_proxies=[])

    headers_a = {"X-Forwarded-For": "203.0.113.10"}
    headers_b = {"X-Forwarded-For": "203.0.113.11"}

    assert client.get("/events", headers=headers_a).status_code == 200
    assert client.get("/events", headers=headers_b).status_code == 429


def test_preview_rate_limit_blocks_after_threshold(client, monkeypatch):
    """The /pricing/preview endpoint enforces its own per-IP rate limit."""
    monkeypatch.setattr(pricing_module, "_PREVIEW_RL_LIMIT", 3)
    monkeypatch.setattr(pricing_module, "_preview_rl_buckets", {})

    preview_payload = {
        "stake_zen": "1.0",
        "market_id": "test-market",
        "wallet_address": "0x" + "a" * 40,
        "outcome_id": 0,
    }
    statuses = []
    for _ in range(4):
        resp = client.post("/pricing/preview", json=preview_payload)
        statuses.append(resp.status_code)

    # First 3 requests pass the rate limiter (may fail later in handler, e.g. 400/503)
    assert all(s != 429 for s in statuses[:3])
    # The 4th request is blocked by the preview rate limiter
    assert statuses[3] == 429
