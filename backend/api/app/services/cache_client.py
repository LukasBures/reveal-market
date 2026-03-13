"""Shared Redis client helper for the API service.

Connections are established lazily with retries and cached globally to avoid
reconnecting on every request.
"""

from __future__ import annotations

import asyncio
import inspect
import logging

import httpx
from redis.asyncio import Redis
from redis.exceptions import RedisError
from shared.cache_async import get_client
from shared.logging import log_event

from app import runtime

_BLOCKING_CACHE_MAX_CONNECTIONS = 4


async def _connect_cache_with_retry(
    *,
    max_connections: int = 20,
    socket_timeout: float = 5.0,
) -> Redis | None:
    """Attempt to connect to Redis with bounded retries and optional delays."""

    attempts = max(1, runtime.settings.cache_connect_retries)
    delay = max(0.0, runtime.settings.cache_connect_retry_delay_seconds)
    for attempt in range(1, attempts + 1):
        client = get_client(
            runtime.settings.redis_url,
            max_connections=max_connections,
            socket_timeout=socket_timeout,
        )
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
            await _close_cache_client_instance(client)
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


async def _close_cache_client_instance(client: Redis) -> None:
    try:
        close_result = client.close()
        if inspect.isawaitable(close_result):
            await close_result
    except Exception as exc:  # pragma: no cover - defensive cleanup
        log_event(
            runtime.logger,
            logging.DEBUG,
            event="cache.close.failed",
            message="failed to close redis client",
            error=str(exc),
        )
    try:
        disconnect_result = client.connection_pool.disconnect()
        if inspect.isawaitable(disconnect_result):
            await disconnect_result
    except Exception as exc:  # pragma: no cover - defensive cleanup
        log_event(
            runtime.logger,
            logging.DEBUG,
            event="cache.pool.disconnect_failed",
            message="failed to disconnect redis connection pool",
            error=str(exc),
        )


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


async def get_blocking_cache_client(*, read_timeout_seconds: float) -> Redis | None:
    """Return a Redis client sized for blocking queue reads like BRPOP."""

    if runtime.blocking_cache_client is not None:
        return runtime.blocking_cache_client
    async with runtime.blocking_cache_lock:
        if runtime.blocking_cache_client is None:
            runtime.blocking_cache_client = await _connect_cache_with_retry(
                max_connections=_BLOCKING_CACHE_MAX_CONNECTIONS,
                socket_timeout=max(float(read_timeout_seconds) + 2.0, 10.0),
            )
    return runtime.blocking_cache_client


async def close_cache_client() -> None:
    """Close the shared Redis client if present."""

    async with runtime.cache_lock:
        client = runtime.cache_client
        runtime.cache_client = None
    async with runtime.blocking_cache_lock:
        blocking_client = runtime.blocking_cache_client
        runtime.blocking_cache_client = None
    if client is not None:
        await _close_cache_client_instance(client)
    if blocking_client is not None and blocking_client is not client:
        await _close_cache_client_instance(blocking_client)


def _build_http_timeout(timeout_seconds: float | None) -> httpx.Timeout:
    settings = runtime.settings
    total = float(timeout_seconds or settings.fx_timeout_seconds)
    return httpx.Timeout(
        total,
        connect=settings.fx_connect_timeout_seconds,
        read=settings.fx_read_timeout_seconds,
        write=settings.fx_write_timeout_seconds,
        pool=settings.fx_pool_timeout_seconds,
    )


def _build_http_limits() -> httpx.Limits:
    settings = runtime.settings
    return httpx.Limits(
        max_connections=settings.fx_max_connections,
        max_keepalive_connections=settings.fx_max_keepalive_connections,
    )


async def get_http_client(timeout_seconds: float | None = None) -> httpx.AsyncClient:
    """Return a shared AsyncClient for outbound HTTP calls."""

    timeout = _build_http_timeout(timeout_seconds)
    limits = _build_http_limits()
    timeout_key = getattr(timeout, "total", None) or (timeout_seconds or runtime.settings.fx_timeout_seconds)
    async with runtime.shared_http_lock:
        client = runtime.shared_http_clients.get(timeout_key)
        if client is not None and getattr(client, "is_closed", False):
            await client.aclose()
            runtime.shared_http_clients.pop(timeout_key, None)
            client = None
        if client is None:
            client = httpx.AsyncClient(timeout=timeout, limits=limits)
            runtime.shared_http_clients[timeout_key] = client
        return client


async def close_http_clients() -> None:
    """Close all shared outbound HTTP clients."""

    async with runtime.shared_http_lock:
        clients = list(runtime.shared_http_clients.values())
        runtime.shared_http_clients.clear()
    for client in clients:
        try:
            await client.aclose()
        except Exception as exc:  # pragma: no cover - defensive cleanup
            log_event(
                runtime.logger,
                logging.DEBUG,
                event="http_client.close_failed",
                message="failed to close shared http client",
                error=str(exc),
            )
