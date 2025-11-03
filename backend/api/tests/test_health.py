from __future__ import annotations


def test_health_endpoint_reports_ok(client, monkeypatch):
    class DummyRedis:
        def ping(self):
            return True

    class DummyResponse:
        def raise_for_status(self):
            return None

    class DummyAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

        async def get(self, *args, **kwargs):
            return DummyResponse()

    monkeypatch.setattr("app.health.get_redis_client", lambda: DummyRedis())
    monkeypatch.setattr("app.health.httpx.AsyncClient", DummyAsyncClient)

    response = client.get("/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "ok"
    components = payload["components"]
    assert components["database"]["status"] == "ok"
    assert components["redis"]["status"] == "ok"
    assert components["polymarket_api"]["status"] == "ok"
