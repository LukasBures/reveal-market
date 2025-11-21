from __future__ import annotations

import pytest
from app.locks import RedisLockManager


@pytest.mark.asyncio
async def test_idempotency_manager_fallback_memory():
    mgr = RedisLockManager(redis_client=None, lock_ttl_seconds=1, idempotency_ttl_seconds=60)
    assert await mgr.claim_idempotency("k1") is True
    assert await mgr.claim_idempotency("k1") is False


@pytest.mark.asyncio
async def test_fallback_lock_prevents_concurrent_sections():
    mgr = RedisLockManager(redis_client=None, lock_ttl_seconds=1, idempotency_ttl_seconds=60)
    entered = []

    async def critical():
        async with mgr.lock("resource"):
            entered.append(1)

    await critical()
    assert entered == [1]
