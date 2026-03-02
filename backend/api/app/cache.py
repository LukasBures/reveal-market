"""Lightweight Redis helper used for health checks and caching."""

from __future__ import annotations

import inspect
import logging
import threading

from redis.asyncio import Redis
from shared.logging import log_event

from .config import get_settings

_redis_client: Redis | None = None
_redis_client_lock = threading.Lock()
logger = logging.getLogger("reveal_market.api.cache")


def get_redis_client() -> Redis | None:
    """Return a cached async Redis client for health checks and caching."""

    global _redis_client
    with _redis_client_lock:
        if _redis_client is None:
            settings = get_settings()
            _redis_client = Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                max_connections=5,
                socket_timeout=5.0,
                socket_connect_timeout=3.0,
                retry_on_timeout=True,
                health_check_interval=30,
            )
        return _redis_client


async def close_redis_client() -> None:
    """Close the cached Redis client used for health checks."""

    global _redis_client
    with _redis_client_lock:
        client = _redis_client
        _redis_client = None
    if client is None:
        return
    try:
        close_result = client.close()
        if inspect.isawaitable(close_result):
            await close_result
    except Exception as exc:
        log_event(
            logger,
            logging.DEBUG,
            event="cache.health.close_failed",
            message="failed to close health redis client",
            error=str(exc),
        )
    try:
        disconnect_result = client.connection_pool.disconnect()
        if inspect.isawaitable(disconnect_result):
            await disconnect_result
    except Exception as exc:
        log_event(
            logger,
            logging.DEBUG,
            event="cache.health.disconnect_failed",
            message="failed to disconnect health redis connection pool",
            error=str(exc),
        )
