from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx


class _BaseDummyRedis:
    def ping(self):
        return True


class _DummyResponse:
    def raise_for_status(self):
        return None


class _AsyncClientSuccess:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False

    async def get(self, *args, **kwargs):
        return _DummyResponse()


def test_health_endpoint_reports_ok(client, monkeypatch):
    class DummyRedis(_BaseDummyRedis):
        def get(self, key):
            return b'{"markets_processed": 10}'

    monkeypatch.setattr("app.health.get_redis_client", lambda: DummyRedis())
    monkeypatch.setattr("app.health.httpx.AsyncClient", _AsyncClientSuccess)

    response = client.get("/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "ok"
    components = payload["components"]
    assert components["database"]["status"] == "ok"
    assert components["redis"]["status"] == "ok"
    assert components["worker"]["status"] == "ok"
    assert components["polymarket_api"]["status"] == "ok"


def test_health_endpoint_marks_worker_degraded_when_heartbeat_missing(client, monkeypatch):
    class DummyRedis(_BaseDummyRedis):
        def get(self, key):
            return None

    monkeypatch.setattr("app.health.get_redis_client", lambda: DummyRedis())
    monkeypatch.setattr("app.health.httpx.AsyncClient", _AsyncClientSuccess)

    response = client.get("/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "degraded"
    components = payload["components"]
    assert components["worker"]["status"] == "degraded"
    assert components["redis"]["status"] == "ok"
    assert components["polymarket_api"]["status"] == "ok"


def test_health_endpoint_handles_polymarket_timeout(client, monkeypatch):
    class DummyRedis(_BaseDummyRedis):
        def get(self, key):
            return b'{"markets_processed": 5}'

    class TimeoutAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

        async def get(self, *args, **kwargs):
            raise httpx.TimeoutException("upstream timeout")

    monkeypatch.setattr("app.health.get_redis_client", lambda: DummyRedis())
    monkeypatch.setattr("app.health.httpx.AsyncClient", TimeoutAsyncClient)

    response = client.get("/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "degraded"
    components = payload["components"]
    assert components["polymarket_api"]["status"] == "degraded"
    assert "timeout" in components["polymarket_api"]["detail"].lower()


def test_heartbeat_dashboard_reports_components(client):
    cache = client.app.cache_client
    now_iso = datetime.now(tz=UTC).isoformat()
    cache.set(
        "reveal_market_worker:heartbeat",
        json.dumps(
            {
                "service": "Reveal Market Worker",
                "component": "worker",
                "timestamp": now_iso,
                "markets_processed": 7,
                "markets_changed": 2,
                "resolutions_changed": 1,
                "latency_ms": 42.5,
            }
        ),
    )
    cache.set(
        "reveal_market_api:heartbeat",
        json.dumps(
            {
                "service": "Reveal Market API",
                "component": "api",
                "timestamp": now_iso,
                "metrics": {"total_requests": 15, "avg_latency_ms": 23.4},
            }
        ),
    )

    response = client.get("/health/heartbeats")
    assert response.status_code == 200
    payload = response.json()
    assert payload["worker"]["service"] == "Reveal Market Worker"
    assert payload["worker"]["metrics"]["markets_processed"] == 7
    assert payload["api"]["metrics"]["total_requests"] == 15


def test_heartbeat_dashboard_handles_missing_payload(client):
    cache = client.app.cache_client
    cache.delete("reveal_market_worker:heartbeat")
    cache.delete("reveal_market_api:heartbeat")

    response = client.get("/health/heartbeats")
    assert response.status_code == 200
    payload = response.json()
    assert payload["worker"] is None
    assert payload["api"] is None


def test_heartbeat_dashboard_marks_worker_stale(client, monkeypatch):
    monkeypatch.setattr("app.main.settings.worker_heartbeat_stale_seconds", 1, raising=False)
    cache = client.app.cache_client
    old = datetime.now(tz=UTC) - timedelta(minutes=5)
    cache.set(
        "reveal_market_worker:heartbeat",
        json.dumps(
            {
                "service": "Reveal Market Worker",
                "component": "worker",
                "timestamp": old.isoformat(),
                "markets_processed": 1,
            }
        ),
    )

    response = client.get("/health/heartbeats")
    assert response.status_code == 200
    payload = response.json()
    assert payload["worker"]["status"] == "degraded"


def test_heartbeat_dashboard_marks_api_stale(client, monkeypatch):
    monkeypatch.setattr("app.main.settings.api_heartbeat_ttl_seconds", 5, raising=False)
    cache = client.app.cache_client
    old = datetime.now(tz=UTC) - timedelta(minutes=10)
    cache.set(
        "reveal_market_api:heartbeat",
        json.dumps(
            {
                "service": "Reveal Market API",
                "component": "api",
                "timestamp": old.isoformat(),
                "metrics": {"total_requests": 5},
            }
        ),
    )

    response = client.get("/health/heartbeats")
    assert response.status_code == 200
    payload = response.json()
    assert payload["api"]["status"] == "degraded"
