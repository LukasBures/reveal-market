from __future__ import annotations

import app.main as api_main
from app.rate_limit import RATE_LIMIT_COUNTER


def enable_rate_limit(monkeypatch, *, limit: int = 2, window: int = 60, whitelist: list[str] | None = None) -> None:
    monkeypatch.setattr(api_main.settings, "rate_limit_enabled", True, raising=False)
    monkeypatch.setattr(api_main.settings, "rate_limit_requests_per_window", limit, raising=False)
    monkeypatch.setattr(api_main.settings, "rate_limit_window_seconds", window, raising=False)
    monkeypatch.setattr(api_main.settings, "rate_limit_whitelist", whitelist or [], raising=False)
    api_main.rate_limiter.reset()


def test_rate_limit_blocks_after_threshold(client, monkeypatch):
    enable_rate_limit(monkeypatch, limit=2, window=60)

    response1 = client.get("/markets")
    response2 = client.get("/markets")
    response3 = client.get("/markets")

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

    response1 = client.get("/markets")
    response2 = client.get("/markets")

    assert response1.status_code == 200
    assert response2.status_code == 200
    assert "X-RateLimit-Limit" in response1.headers


def test_rate_limit_disabled_does_not_block(client, monkeypatch):
    monkeypatch.setattr(api_main.settings, "rate_limit_enabled", False, raising=False)
    api_main.rate_limiter.reset()

    responses = [client.get("/markets") for _ in range(3)]
    assert all(response.status_code == 200 for response in responses)


def test_rate_limit_metrics_increment(client, monkeypatch):
    enable_rate_limit(monkeypatch, limit=1, window=60)
    allowed_before = RATE_LIMIT_COUNTER.labels(outcome="allowed")._value.get()
    blocked_before = RATE_LIMIT_COUNTER.labels(outcome="blocked")._value.get()

    first = client.get("/markets")
    second = client.get("/markets")

    assert first.status_code == 200
    assert second.status_code == 429

    allowed_after = RATE_LIMIT_COUNTER.labels(outcome="allowed")._value.get()
    blocked_after = RATE_LIMIT_COUNTER.labels(outcome="blocked")._value.get()

    assert allowed_after - allowed_before == 1
    assert blocked_after - blocked_before == 1
