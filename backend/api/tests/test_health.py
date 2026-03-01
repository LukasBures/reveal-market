from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
from app.config import get_settings
from eth_account import Account
from pydantic import SecretStr


class _BaseDummyRedis:
    async def ping(self):
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


def _configure_signer(settings):
    settings.pricing_chain_id = 1
    settings.pricing_signer_private_key = SecretStr(
        "0x59c6995e998f97a5a004497e5a61829cb0d9bf5f7f19f6cbe9a6a5e4f6b9f9f5"
    )
    settings.rpc_url = "http://localhost:8545"
    settings.environment = "test"
    settings.health_cache_ttl_seconds = 0
    settings.health_deep_cache_ttl_seconds = 0
    return settings


def test_health_endpoint_reports_ok(client, monkeypatch):
    class DummyRedis(_BaseDummyRedis):
        async def get(self, key):
            return b'{"markets_processed": 10}'

    settings = _configure_signer(get_settings())
    signer_address = Account.from_key(settings.pricing_signer_private_key.get_secret_value()).address
    monkeypatch.setenv("PRICING_SIGNER_ADDRESS", signer_address)
    settings.cors_allow_origins = ["https://example.com"]

    monkeypatch.setattr("app.health.get_redis_client", lambda: DummyRedis())
    monkeypatch.setattr("app.health.httpx.AsyncClient", _AsyncClientSuccess)
    monkeypatch.setattr("app.health.get_settings", lambda: settings)

    response = client.get("/healthz/deep")
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
        async def get(self, key):
            return None

    settings = _configure_signer(get_settings())
    signer_address = Account.from_key(settings.pricing_signer_private_key.get_secret_value()).address
    monkeypatch.setenv("PRICING_SIGNER_ADDRESS", signer_address)
    monkeypatch.setattr("app.health.get_settings", lambda: settings)
    monkeypatch.setattr("app.health.get_redis_client", lambda: DummyRedis())
    monkeypatch.setattr("app.health.httpx.AsyncClient", _AsyncClientSuccess)

    response = client.get("/healthz/deep")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "degraded"
    components = payload["components"]
    assert components["worker"]["status"] == "degraded"
    assert components["redis"]["status"] == "ok"
    assert components["polymarket_api"]["status"] == "ok"


def test_health_endpoint_handles_polymarket_timeout(client, monkeypatch):
    class DummyRedis(_BaseDummyRedis):
        async def get(self, key):
            return b'{"markets_processed": 5}'

    settings = _configure_signer(get_settings())
    signer_address = Account.from_key(settings.pricing_signer_private_key.get_secret_value()).address
    monkeypatch.setenv("PRICING_SIGNER_ADDRESS", signer_address)
    monkeypatch.setattr("app.health.get_settings", lambda: settings)

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

    response = client.get("/healthz/deep")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "degraded"
    components = payload["components"]
    assert components["polymarket_api"]["status"] == "degraded"
    assert "timeout" in components["polymarket_api"]["detail"].lower()


def test_heartbeat_dashboard_reports_components(client, monkeypatch):
    cache = client.app.cache_client
    now_iso = datetime.now(tz=UTC).isoformat()
    monkeypatch.setattr("app.routes.meta.settings.internal_api_secret", SecretStr("secret"), raising=False)
    asyncio.run(
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
    )
    asyncio.run(
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
    )

    response = client.get("/healthz/heartbeats", headers={"X-Internal-Secret": "secret"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["worker"]["service"] == "Reveal Market Worker"
    assert payload["worker"]["metrics"]["markets_processed"] == 7
    assert payload["api"]["metrics"]["total_requests"] == 15


def test_heartbeat_dashboard_handles_missing_payload(client, monkeypatch):
    cache = client.app.cache_client
    asyncio.run(cache.delete("reveal_market_worker:heartbeat"))
    asyncio.run(cache.delete("reveal_market_api:heartbeat"))

    monkeypatch.setattr("app.routes.meta.settings.internal_api_secret", SecretStr("secret"), raising=False)
    response = client.get("/healthz/heartbeats", headers={"X-Internal-Secret": "secret"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["worker"] is None
    assert payload["api"] is None


def test_heartbeat_summary_is_public(client):
    cache = client.app.cache_client
    now_iso = datetime.now(tz=UTC).isoformat()
    asyncio.run(
        cache.set(
            "reveal_market_worker:heartbeat",
            json.dumps(
                {
                    "service": "Reveal Market Worker",
                    "component": "worker",
                    "timestamp": now_iso,
                    "markets_processed": 11,
                }
            ),
        )
    )
    asyncio.run(
        cache.set(
            "reveal_market_api:heartbeat",
            json.dumps(
                {
                    "service": "Reveal Market API",
                    "component": "api",
                    "timestamp": now_iso,
                    "metrics": {"total_requests": 21, "avg_latency_ms": 18.2},
                }
            ),
        )
    )

    response = client.get("/healthz/heartbeats/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["worker"]["status"] == "ok"
    assert payload["api"]["status"] == "ok"
    assert payload["worker"]["age_seconds"] is not None
    assert payload["api"]["age_seconds"] is not None


def test_heartbeat_summary_degrades_when_payload_missing(client):
    cache = client.app.cache_client
    asyncio.run(cache.delete("reveal_market_worker:heartbeat"))
    asyncio.run(cache.delete("reveal_market_api:heartbeat"))

    response = client.get("/healthz/heartbeats/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["worker"]["status"] == "degraded"
    assert payload["worker"]["detail"] == "heartbeat_missing"
    assert payload["api"]["status"] == "degraded"
    assert payload["api"]["detail"] == "heartbeat_missing"


def test_heartbeat_dashboard_marks_worker_stale(client, monkeypatch):
    monkeypatch.setattr("app.server.settings.worker_heartbeat_stale_seconds", 1, raising=False)
    cache = client.app.cache_client
    old = datetime.now(tz=UTC) - timedelta(minutes=5)
    monkeypatch.setattr("app.routes.meta.settings.internal_api_secret", SecretStr("secret"), raising=False)
    asyncio.run(
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
    )

    response = client.get("/healthz/heartbeats", headers={"X-Internal-Secret": "secret"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["worker"]["status"] == "degraded"


def test_heartbeat_dashboard_marks_api_stale(client, monkeypatch):
    monkeypatch.setattr("app.server.settings.api_heartbeat_ttl_seconds", 5, raising=False)
    cache = client.app.cache_client
    old = datetime.now(tz=UTC) - timedelta(minutes=10)
    monkeypatch.setattr("app.routes.meta.settings.internal_api_secret", SecretStr("secret"), raising=False)
    asyncio.run(
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
    )

    response = client.get("/healthz/heartbeats", headers={"X-Internal-Secret": "secret"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["api"]["status"] == "degraded"


def test_readiness_and_liveness_endpoints(client, monkeypatch):
    settings = _configure_signer(get_settings())
    signer_address = Account.from_key(settings.pricing_signer_private_key.get_secret_value()).address
    monkeypatch.setenv("PRICING_SIGNER_ADDRESS", signer_address)
    monkeypatch.setattr("app.health.get_settings", lambda: settings)
    monkeypatch.setattr("app.health.httpx.AsyncClient", _AsyncClientSuccess)

    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["service"] == settings.app_name

    live = client.get("/live")
    assert live.status_code == 200
    assert live.json()["status"] == "ok"
