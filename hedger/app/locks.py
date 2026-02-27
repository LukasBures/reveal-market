from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import cast

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
        self._release_script = (
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
        )

    @asynccontextmanager
    async def lock(self, key: str) -> AsyncIterator[None]:
        if self.redis:
            token = uuid.uuid4().hex
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
                    try:
                        result = self.redis.eval(self._release_script, 1, f"lock:{key}", token)
                        await cast(Awaitable[object], result)
                    except Exception as exc:
                        logger = logging.getLogger("reveal_market.hedger.locks")
                        logger.warning(
                            "redis lock release failed",
                            extra={"error": str(exc), "key": key},
                        )
                return
            except Exception as exc:
                # Fall back to process-local lock if Redis is unavailable.
                logger = logging.getLogger("reveal_market.hedger.locks")
                logger.warning("redis lock failed; using fallback lock", extra={"error": str(exc), "key": key})

        # Fallback to process-local locks — evict stale entries when too many accumulate
        if len(self._fallback_locks) >= self._MAX_FALLBACK_LOCKS:
            unlocked = [k for k, v in self._fallback_locks.items() if not v.locked()]
            for evict_key in unlocked[: len(unlocked) // 2]:
                self._fallback_locks.pop(evict_key, None)
        lock = self._fallback_locks.setdefault(key, asyncio.Lock())
        async with lock:
            yield

    _MAX_FALLBACK_LOCKS = 1000
    _MAX_IDEMPOTENCY_ENTRIES = 10000

    async def claim_idempotency(self, key: str) -> bool:
        """Return True if the key was claimed now; False if already seen."""

        if self.redis:
            return bool(await self.redis.set(f"idemp:{key}", "1", nx=True, ex=self.idempotency_ttl_seconds))

        now = time.time()
        # Purge expired entries
        expired = [k for k, exp in self._idempotency_cache.items() if exp < now]
        for k in expired:
            self._idempotency_cache.pop(k, None)

        # Evict oldest entries if cache exceeds max size
        if len(self._idempotency_cache) >= self._MAX_IDEMPOTENCY_ENTRIES:
            sorted_keys = sorted(self._idempotency_cache, key=self._idempotency_cache.get)  # type: ignore[arg-type]
            for evict_key in sorted_keys[: len(self._idempotency_cache) - self._MAX_IDEMPOTENCY_ENTRIES + 1]:
                self._idempotency_cache.pop(evict_key, None)

        if key in self._idempotency_cache:
            return False
        self._idempotency_cache[key] = now + self.idempotency_ttl_seconds
        return True
