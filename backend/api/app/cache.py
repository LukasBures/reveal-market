from __future__ import annotations

from functools import lru_cache

from redis import Redis

from .config import get_settings


@lru_cache(maxsize=1)
def get_redis_client() -> Redis:
    """Return a cached Redis client for lightweight health checks and caching."""
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)
