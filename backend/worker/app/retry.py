"""Redis-backed retry state helpers for backoff and recovery."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable
from typing import Any

from redis.asyncio import Redis
from shared.logging import log_event


def _now() -> float:
    return time.time()


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def failure_key(prefix: str, market_id: int | str) -> str:
    return f"{prefix}:{market_id}"


def _is_awaitable(value: Any) -> bool:
    try:
        return isinstance(value, Awaitable)
    except TypeError:
        return False


async def _resolve_awaitable(value: Awaitable[Any] | Any) -> Any:
    if _is_awaitable(value):
        return await value
    return value


async def should_attempt(redis_client: Redis | None, key: str) -> bool:
    if redis_client is None:
        return True
    try:
        state = await _resolve_awaitable(redis_client.hgetall(key))
    except Exception:
        return True
    next_ts = _to_float(state.get("next_ts"), 0.0)
    return _now() >= next_ts


async def record_failure(
    redis_client: Redis | None,
    key: str,
    *,
    base_seconds: int,
    max_seconds: int,
    max_attempts: int,
    logger,
    event: str,
    message: str,
    reason: str | None = None,
) -> tuple[int, float] | None:
    if redis_client is None:
        return None
    try:
        state = await _resolve_awaitable(redis_client.hgetall(key))
        attempts = _to_int(state.get("attempts"), 0) + 1
        backoff = min(base_seconds * (2 ** max(attempts - 1, 0)), max_seconds)
        if attempts >= max_attempts:
            backoff = max_seconds
        next_ts = _now() + backoff
        await _resolve_awaitable(
            redis_client.hset(
                key,
                mapping={
                    "attempts": str(attempts),
                    "next_ts": str(next_ts),
                    "last_error": reason or "",
                    "updated_at": str(_now()),
                },
            )
        )
        await _resolve_awaitable(redis_client.expire(key, max_seconds * 4))
        log_event(
            logger,
            logging.INFO,
            event=event,
            message=message,
            attempts=attempts,
            next_retry_seconds=int(backoff),
            reason=reason,
            retry_key=key,
        )
        return attempts, next_ts
    except Exception:
        return None


async def clear_failure(redis_client: Redis | None, key: str) -> None:
    if redis_client is None:
        return
    try:
        await _resolve_awaitable(redis_client.delete(key))
    except Exception:
        return
