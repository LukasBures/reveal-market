from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from fastapi import Request
from fastapi.responses import JSONResponse
from redis import Redis
from shared.logging import log_event
from shared.metrics import Counter as RM_Counter
from starlette.status import HTTP_429_TOO_MANY_REQUESTS

from app.config import Settings

logger = logging.getLogger("reveal_market.api.rate_limit")
RATE_LIMIT_COUNTER = RM_Counter("rate_limit_events_total", "Rate limit decisions", ["outcome"])


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_at: float

    @property
    def retry_after_seconds(self) -> int:
        return max(int(self.reset_at - time.time()), 0)


class RateLimiter:
    def __init__(
        self,
        settings: Settings | Callable[[], Settings],
        cache_provider: Callable[[], Redis | None],
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
        self._memory_lock = Lock()

    @property
    def settings(self) -> Settings:
        return self._settings_provider()

    def reset(self, identifier: str | None = None) -> None:
        with self._memory_lock:
            if identifier is None:
                self._memory_state.clear()
            else:
                self._memory_state.pop(identifier, None)

    def evaluate(self, identifier: str) -> RateLimitResult:
        limit = max(int(self.settings.rate_limit_requests_per_window), 1)
        window = max(int(self.settings.rate_limit_window_seconds), 1)
        client = self.cache_provider()
        if client is not None and hasattr(client, "pipeline"):
            try:
                return self._evaluate_redis(client, identifier, limit, window)
            except Exception as exc:  # pragma: no cover - defensive fallback
                log_event(
                    logger,
                    logging.WARNING,
                    event="rate_limit.redis_error",
                    message="redis rate limit evaluation failed, falling back to memory",
                    error=str(exc),
                )
        return self._evaluate_memory(identifier, limit, window)

    def _evaluate_memory(self, identifier: str, limit: int, window: int) -> RateLimitResult:
        now = time.time()
        with self._memory_lock:
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

    def _evaluate_redis(self, client: Redis, identifier: str, limit: int, window: int) -> RateLimitResult:
        key = f"{self.prefix}:{identifier}"
        pipeline = client.pipeline()
        pipeline.incr(key, 1)
        pipeline.ttl(key)
        count, ttl = pipeline.execute()
        if ttl is None or ttl < 0:
            client.expire(key, window)
            ttl = window
        remaining = max(limit - int(count), 0)
        reset_at = time.time() + ttl
        allowed = int(count) <= limit
        return RateLimitResult(allowed=allowed, limit=limit, remaining=remaining, reset_at=reset_at)


class RateLimitMiddleware:
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

        result = self.limiter.evaluate(identifier)
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

    @staticmethod
    def _extract_identifier(request: Request) -> str | None:
        forwarded = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")
        candidate = None
        if forwarded:
            candidate = forwarded.split(",")[0].strip()
        elif request.client and request.client.host:
            candidate = request.client.host
        if not candidate:
            return None
        normalized = candidate.lower()
        if normalized in {"localhost", "testclient"}:
            return "127.0.0.1"
        return normalized

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
