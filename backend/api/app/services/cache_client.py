"""Shared Redis client helper for the API service.

Connections are established lazily with retries and cached globally to avoid
reconnecting on every request.
"""

from __future__ import annotations

import asyncio
import logging

from app import runtime
from redis.asyncio import Redis
from redis.exceptions import RedisError
from shared.cache_async import get_client
from shared.logging import log_event


async def _connect_cache_with_retry() -> Redis | None:
    """Attempt to connect to Redis with bounded retries and optional delays."""

    attempts = max(1, runtime.settings.cache_connect_retries)
    delay = max(0.0, runtime.settings.cache_connect_retry_delay_seconds)
    for attempt in range(1, attempts + 1):
        client = get_client(runtime.settings.redis_url)
        if client is None:
            if attempt < attempts and delay:
                await asyncio.sleep(delay)
            continue
        try:
            await client.ping()
        except RedisError as exc:  # pragma: no cover - network flake
            log_event(
                runtime.logger,
                logging.WARNING,
                event="cache.connect.ping_failed",
                message="redis ping failed, will retry",
                attempt=attempt,
                error=str(exc),
            )
            if attempt < attempts and delay:
                await asyncio.sleep(delay)
            continue
        log_event(
            runtime.logger,
            logging.INFO,
            event="cache.connect.established",
            message="connected to redis",
            attempt=attempt,
        )
        return client
    log_event(
        runtime.logger,
        logging.WARNING,
        event="cache.connect.unavailable",
        message="redis unavailable after retries, continuing without cache",
        attempts=attempts,
    )
    return None


async def get_cache_client() -> Redis | None:
    """Return the shared Redis client, populating it on first call."""

    if runtime.cache_client is not None:
        return runtime.cache_client
    async with runtime.cache_lock:
        if runtime.cache_client is None:
            runtime.cache_client = await _connect_cache_with_retry()
            if runtime.cache_client is not None:
                try:
                    import app.server as api_server  # lazy import to avoid cycles

                    api_server.cache_client = runtime.cache_client
                except Exception as exc:  # pragma: no cover - defensive
                    log_event(
                        runtime.logger,
                        logging.DEBUG,
                        event="cache.connect.cache_set_failed",
                        message="failed to propagate cache client to api server",
                        error=str(exc),
                    )
    return runtime.cache_client
