"""Concurrent request tests for the API."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient


class _InMemoryCache:
    """Minimal async cache used by tests (mirrors conftest.InMemoryCache)."""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> Any:
        return self.store.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None, nx: bool | None = None) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.store.pop(key, None)


def _wire_app(test_database, monkeypatch):
    """Bind the test app to a test database session and in-memory cache."""
    import app.runtime as runtime
    import app.server as api_main
    from app.database import get_session

    _, testing_async_session, _ = test_database

    async def override_get_session():
        async with testing_async_session() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    app_instance = api_main.app
    app_instance.dependency_overrides[get_session] = override_get_session
    cache = _InMemoryCache()
    app_instance.cache_client = cache  # type: ignore[attr-defined]
    api_main.cache_client = cache  # type: ignore[attr-defined]
    runtime.cache_client = cache  # type: ignore[attr-defined]
    app_instance.state.cache_client = cache  # type: ignore[attr-defined]

    monkeypatch.setattr("app.server.run_startup_tasks", lambda: None, raising=False)
    monkeypatch.setattr("app.tasks.run_startup_tasks", lambda: None, raising=False)
    monkeypatch.setattr("app.server.stop_background_tasks", lambda: None, raising=False)
    monkeypatch.setattr("app.tasks.stop_background_tasks", lambda: None, raising=False)

    return app_instance


@pytest.mark.slow
async def test_concurrent_get_markets(test_database, monkeypatch):
    """10 concurrent GET /events should all return 200."""
    app_instance = _wire_app(test_database, monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        responses = await asyncio.gather(*(client.get("/events") for _ in range(10)))
    assert all(r.status_code == 200 for r in responses), [r.status_code for r in responses]


@pytest.mark.slow
async def test_concurrent_pricing_preview_rate_limit(test_database, monkeypatch):
    """10 concurrent POST /pricing/preview beyond limit should see 429s."""
    import app.routes.pricing as pricing_mod

    monkeypatch.setattr(pricing_mod, "_PREVIEW_RL_LIMIT", 3)
    monkeypatch.setattr(pricing_mod, "_preview_rl_buckets", {})

    app_instance = _wire_app(test_database, monkeypatch)
    body = {
        "stake_zen": 0.1,
        "wallet_address": "0x" + "1" * 40,
        "market_address": "0x" + "2" * 40,
        "outcome_id": 0,
    }
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
        responses = await asyncio.gather(*(client.post("/pricing/preview", json=body) for _ in range(10)))
    status_codes = [r.status_code for r in responses]
    assert status_codes.count(429) >= 7, f"Expected at least 7 rate-limited responses, got {status_codes}"
