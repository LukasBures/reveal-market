from __future__ import annotations

import pytest
from app import runtime as runtime_module
from app.services import cache_client as cache_client_service


class _FakePool:
    async def disconnect(self):
        return None


class _FakeRedis:
    def __init__(self):
        self.connection_pool = _FakePool()
        self.closed = False

    async def ping(self):
        return True

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_get_blocking_cache_client_uses_longer_socket_timeout(monkeypatch):
    created: list[dict[str, float | int]] = []

    def _fake_get_client(url: str, **kwargs):
        created.append({"url": url, **kwargs})
        return _FakeRedis()

    monkeypatch.setattr(cache_client_service, "get_client", _fake_get_client)
    monkeypatch.setattr(runtime_module.settings, "redis_url", "redis://cache", raising=False)
    monkeypatch.setattr(runtime_module.settings, "cache_connect_retries", 1, raising=False)
    monkeypatch.setattr(runtime_module.settings, "cache_connect_retry_delay_seconds", 0.0, raising=False)
    monkeypatch.setattr(runtime_module, "cache_client", None, raising=False)
    monkeypatch.setattr(runtime_module, "blocking_cache_client", None, raising=False)

    client = await cache_client_service.get_blocking_cache_client(read_timeout_seconds=5)

    assert client is not None
    assert len(created) == 1
    assert created[0]["url"] == "redis://cache"
    assert created[0]["max_connections"] == 4
    assert created[0]["socket_timeout"] == 10.0

    await cache_client_service.close_cache_client()
