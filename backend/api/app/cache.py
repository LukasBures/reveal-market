"""Lightweight Redis helper used for health checks and caching."""

from __future__ import annotations

from redis.asyncio import Redis

from .config import get_settings

_redis_client: Redis | None = None


def get_redis_client() -> Redis | None:
    """Return a cached async Redis client for health checks and caching."""

    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client
