from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

try:
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover
    Redis = None  # type: ignore


class RedisLockManager:
    """Provides Redis-backed locks and idempotency claims with in-memory fallback."""

    def __init__(self, redis_client: Redis | None, lock_ttl_seconds: int, idempotency_ttl_seconds: int):
        self.redis = redis_client
        self.lock_ttl_seconds = lock_ttl_seconds
        self.idempotency_ttl_seconds = idempotency_ttl_seconds
        self._fallback_locks: dict[str, asyncio.Lock] = {}
        self._idempotency_cache: dict[str, float] = {}

    @asynccontextmanager
    async def lock(self, key: str) -> AsyncIterator[None]:
        if self.redis:
            token = str(time.time())
            try:
                acquired = await self.redis.set(f"lock:{key}", token, nx=True, ex=self.lock_ttl_seconds)
                if not acquired:
                    # Wait briefly then retry once to avoid thundering herds in tests/local
                    await asyncio.sleep(0.05)
                    acquired = await self.redis.set(f"lock:{key}", token, nx=True, ex=self.lock_ttl_seconds)
                if not acquired:
                    raise RuntimeError(f"Failed to acquire lock for {key}")
                try:
                    yield
                finally:
                    await self.redis.delete(f"lock:{key}")
                return
            except Exception as exc:
                # Fall back to process-local lock if Redis is unavailable.
                logger = logging.getLogger("reveal_market.hedger.locks")
                logger.warning("redis lock failed; using fallback lock", extra={"error": str(exc), "key": key})

        # Fallback to process-local locks
        lock = self._fallback_locks.setdefault(key, asyncio.Lock())
        async with lock:
            yield

    async def claim_idempotency(self, key: str) -> bool:
        """Return True if the key was claimed now; False if already seen."""

        if self.redis:
            return bool(await self.redis.set(f"idemp:{key}", "1", nx=True, ex=self.idempotency_ttl_seconds))

        now = time.time()
        # Purge expired entries
        expired = [k for k, exp in self._idempotency_cache.items() if exp < now]
        for k in expired:
            self._idempotency_cache.pop(k, None)

        if key in self._idempotency_cache:
            return False
        self._idempotency_cache[key] = now + self.idempotency_ttl_seconds
        return True
