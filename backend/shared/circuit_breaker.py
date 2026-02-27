from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from shared.logging import log_event


@dataclass(frozen=True)
class CircuitBreakerConfig:
    key_prefix: str
    failure_threshold: int = 10
    window_seconds: int = 60
    cooldown_seconds: int = 90


class CircuitBreaker:
    """Lightweight Redis-backed circuit breaker with in-process fallback."""

    def __init__(self, redis_client: Any | None, config: CircuitBreakerConfig, logger):
        self._redis = redis_client
        self._config = config
        self._logger = logger
        self._lock = asyncio.Lock()
        self._local_state: dict[str, tuple[int, float]] = {}
        self._local_open_until: dict[str, float] = {}

    def _failure_key(self, name: str) -> str:
        return f"{self._config.key_prefix}:{name}:fail"

    def _open_key(self, name: str) -> str:
        return f"{self._config.key_prefix}:{name}:open_until"

    async def is_open(self, name: str) -> bool:
        async with self._lock:
            now = time.monotonic()
            if name in self._local_open_until and self._local_open_until[name] > now:
                return True
            if self._redis is None:
                return False
            try:
                value = await self._redis.get(self._open_key(name))
                if value is None:
                    return False
                open_until = float(value)
                if open_until > now:
                    self._local_open_until[name] = open_until
                    return True
            except Exception as exc:
                log_event(
                    self._logger,
                    level=logging.WARNING,
                    event="circuit.redis_read_failed",
                    message="failed to read circuit state",
                    name=name,
                    error=str(exc),
                )
            return False

    async def record_success(self, name: str) -> None:
        async with self._lock:
            self._local_state.pop(name, None)
            self._local_open_until.pop(name, None)
            if self._redis is None:
                return
            try:
                await self._redis.delete(self._failure_key(name), self._open_key(name))
            except Exception as exc:
                log_event(
                    self._logger,
                    level=logging.DEBUG,
                    event="circuit.redis_clear_failed",
                    message="failed to clear circuit state",
                    name=name,
                    error=str(exc),
                )

    async def record_failure(self, name: str) -> bool:
        """Record a failure. Returns True if circuit is opened by this call."""

        async with self._lock:
            now = time.monotonic()
            threshold = self._config.failure_threshold
            window = max(self._config.window_seconds, 1)
            cooldown = max(self._config.cooldown_seconds, 1)
            if self._redis is None:
                count, started = self._local_state.get(name, (0, now))
                if now - started > window:
                    count, started = 0, now
                count += 1
                self._local_state[name] = (count, started)
                if count >= threshold:
                    self._local_open_until[name] = now + cooldown
                    return True
                return False

            try:
                key = self._failure_key(name)
                count = await self._redis.incr(key)
                if count == 1:
                    await self._redis.expire(key, window)
                if count >= threshold:
                    open_until = now + cooldown
                    await self._redis.set(self._open_key(name), str(open_until), ex=cooldown)
                    self._local_open_until[name] = open_until
                    return True
            except Exception as exc:
                log_event(
                    self._logger,
                    level=logging.WARNING,
                    event="circuit.redis_write_failed",
                    message="failed to record circuit failure",
                    name=name,
                    error=str(exc),
                )
            return False
