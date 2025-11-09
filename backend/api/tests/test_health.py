from __future__ import annotations

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
