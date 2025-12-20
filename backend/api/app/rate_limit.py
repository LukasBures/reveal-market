"""Async rate limiting primitives and middleware.

The limiter prefers Redis for distributed counting but gracefully falls back to
an in-memory lock-protected counter when Redis is unavailable so the API
continues to function under partial outages.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
from typing import Any, cast

from fastapi import Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError
from shared.logging import log_event
from shared.metrics import Counter as RM_Counter
from starlette.status import HTTP_429_TOO_MANY_REQUESTS

from app.config import Settings

logger = logging.getLogger("reveal_market.api.rate_limit")
RATE_LIMIT_COUNTER = RM_Counter("rate_limit_events_total", "Rate limit decisions", ["outcome"])
_RATE_LIMIT_LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
else
  local ttl = redis.call('TTL', KEYS[1])
  if ttl < 0 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
  end
end
return {current, redis.call('TTL', KEYS[1])}
"""


@dataclass
class RateLimitResult:
    """Normalized view of a rate limit decision."""

    allowed: bool
    limit: int
    remaining: int
    reset_at: float

    @property
    def retry_after_seconds(self) -> int:
        return max(int(self.reset_at - time.time()), 0)


class RateLimiter:
    """Async-friendly rate limiter that supports Redis and in-process fallbacks."""

    def __init__(
        self,
        settings: Settings | Callable[[], Settings],
        cache_provider: Callable[[], Awaitable[Redis | None] | Redis | None],
        *,
        prefix: str = "ratelimit",
    ):
        if callable(settings):
            self._settings_provider = settings
        else:
            self._settings_provider = lambda: settings
        self.cache_provider = cache_provider
        self.prefix = prefix
        self._memory_state: dict[str, tuple[int, float]] = {}
        self._memory_lock = asyncio.Lock()

    @property
    def settings(self) -> Settings:
        return self._settings_provider()

    async def reset(self, identifier: str | None = None) -> None:
        """Reset counters for a single identifier or wipe everything in-memory."""

        async with self._memory_lock:
            if identifier is None:
                self._memory_state.clear()
            else:
                self._memory_state.pop(identifier, None)

    async def evaluate(self, identifier: str) -> RateLimitResult:
        """
        Evaluate the current request and return the remaining allowance.

        Redis is used when available so multiple API workers can share state;
        otherwise we default to an in-memory counter to avoid hard failures.
        """

        limit = max(int(self.settings.rate_limit_requests_per_window), 1)
        window = max(int(self.settings.rate_limit_window_seconds), 1)
        client_raw = self.cache_provider()
        if inspect.isawaitable(client_raw):
            client = await cast(Awaitable[Redis | None], client_raw)
        else:
            client = cast(Redis | None, client_raw)
        if client is not None and hasattr(client, "pipeline"):
            try:
                return await self._evaluate_redis(client, identifier, limit, window)
            except (RedisError, OSError, RuntimeError) as exc:  # pragma: no cover - defensive fallback
                log_event(
                    logger,
                    logging.WARNING,
                    event="rate_limit.redis_error",
                    message="redis rate limit evaluation failed, falling back to memory",
                    error=str(exc),
                )
        return await self._evaluate_memory(identifier, limit, window)

    async def _evaluate_memory(self, identifier: str, limit: int, window: int) -> RateLimitResult:
        """In-memory counter used as a best-effort fallback when Redis is down."""

        now = time.time()
        async with self._memory_lock:
            count, expires_at = self._memory_state.get(identifier, (0, 0.0))
            if expires_at <= now:
                count = 0
                expires_at = now + window
            count += 1
            self._memory_state[identifier] = (count, expires_at)
            remaining = max(limit - count, 0)
        reset_at = expires_at
        allowed = count <= limit
        return RateLimitResult(allowed=allowed, limit=limit, remaining=remaining, reset_at=reset_at)

    async def _evaluate_redis(self, client: Redis, identifier: str, limit: int, window: int) -> RateLimitResult:
        """Use a Lua script for atomic increment + TTL handling inside Redis."""

        key = f"{self.prefix}:{identifier}"
        try:
            eval_result = await cast(Awaitable[Any], client.eval(_RATE_LIMIT_LUA, 1, key, window))  # type: ignore[arg-type]
            result = cast(tuple[int | str | bytes | None, int | str | bytes | None], eval_result)
            count, ttl = result
        except RedisError as exc:
            log_event(
                logger,
                logging.WARNING,
                event="rate_limit.redis_eval_error",
                message="redis rate limit evaluation failed, falling back to memory",
                error=str(exc),
            )
            return await self._evaluate_memory(identifier, limit, window)
        count_int = int(count) if count is not None else 0
        ttl_value_raw = ttl if ttl is not None else window
        ttl_value = int(ttl_value_raw)
        if ttl_value < 0:
            ttl_value = window
        remaining = max(limit - count_int, 0)
        reset_at = time.time() + ttl_value
        allowed = count_int <= limit
        return RateLimitResult(allowed=allowed, limit=limit, remaining=remaining, reset_at=reset_at)


class RateLimitMiddleware:
    """Starlette middleware that enforces the RateLimiter on every HTTP request."""

    def __init__(self, app, *, settings: Settings | Callable[[], Settings], limiter: RateLimiter):
        self.app = app
        if callable(settings):
            self._settings_provider = settings
        else:
            self._settings_provider = lambda: settings
        self.limiter = limiter

    @property
    def settings(self) -> Settings:
        return self._settings_provider()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)

        if not self.settings.rate_limit_enabled:
            await self.app(scope, receive, send)
            return

        identifier = self._extract_identifier(request) or "anonymous"

        if self._is_whitelisted(identifier):
            allowance = self._build_headers(self._default_allowance())
            await self._call_with_headers(scope, receive, send, allowance)
            return

        result = await self.limiter.evaluate(identifier)
        headers = self._build_headers(result)
        if not result.allowed:
            log_event(
                logger,
                logging.WARNING,
                event="rate_limit.blocked",
                message="rate limit exceeded",
                client=identifier,
                limit=result.limit,
                remaining=result.remaining,
            )
            RATE_LIMIT_COUNTER.labels(outcome="blocked").inc()
            headers["Retry-After"] = str(result.retry_after_seconds)
            response = JSONResponse(
                {"detail": "rate_limit_exceeded"}, status_code=HTTP_429_TOO_MANY_REQUESTS, headers=headers
            )
            await response(scope, receive, send)
            return

        RATE_LIMIT_COUNTER.labels(outcome="allowed").inc()
        await self._call_with_headers(scope, receive, send, headers)

    def _extract_identifier(self, request: Request) -> str | None:
        forwarded = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")
        candidate = None
        client_host = request.client.host if request.client else None
        if forwarded and client_host and self._is_trusted_proxy(client_host):
            candidate = forwarded.split(",")[0].strip()
        elif client_host:
            candidate = client_host
        if not candidate:
            return None
        normalized = candidate.lower()
        if normalized in {"localhost", "testclient"}:
            return "127.0.0.1"
        return normalized

    def _is_trusted_proxy(self, client_host: str) -> bool:
        proxies = [entry for entry in self.settings.rate_limit_trusted_proxies if entry]
        if not proxies:
            return False
        normalized_host = client_host.lower()
        if normalized_host == "localhost":
            normalized_host = "127.0.0.1"
        for proxy in proxies:
            entry = proxy.strip().lower()
            if not entry:
                continue
            if entry == "*":
                return True
            if entry == "localhost":
                entry = "127.0.0.1"
            if "/" in entry:
                try:
                    if ip_address(normalized_host) in ip_network(entry, strict=False):
                        return True
                except ValueError:
                    continue
            elif normalized_host == entry:
                return True
        return False

    def _is_whitelisted(self, identifier: str) -> bool:
        whitelist = {item.strip().lower() for item in self.settings.rate_limit_whitelist if item}
        return identifier in whitelist

    def _default_allowance(self) -> RateLimitResult:
        limit = max(int(self.settings.rate_limit_requests_per_window), 1)
        window = max(int(self.settings.rate_limit_window_seconds), 1)
        reset_at = time.time() + window
        return RateLimitResult(allowed=True, limit=limit, remaining=limit, reset_at=reset_at)

    @staticmethod
    def _build_headers(result: RateLimitResult) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(result.limit),
            "X-RateLimit-Remaining": str(max(result.remaining, 0)),
            "X-RateLimit-Reset": str(int(result.reset_at)),
        }

    async def _call_with_headers(self, scope, receive, send, headers: dict[str, str]) -> None:
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                header_items = list(message.get("headers") or [])
                for key, value in headers.items():
                    header_items.append((key.lower().encode("latin-1"), value.encode("latin-1")))
                message["headers"] = header_items
            await send(message)

        await self.app(scope, receive, send_wrapper)
