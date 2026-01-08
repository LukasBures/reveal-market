from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Mapping, Sequence
from threading import Lock
from typing import Any, Protocol, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from .logging import log_event

logger = logging.getLogger("reveal_market.cache_async")

_TAG_PREFIX = "cache:tag:"
_SCHEMA_UNKNOWN_TAG = "schema:unknown"


class _JsonLib(Protocol):
    def loads(self, payload: str | bytes) -> Any: ...

    def dumps(self, payload: Any) -> bytes: ...


_orjson_spec = importlib.util.find_spec("orjson")
_orjson_module = importlib.import_module("orjson") if _orjson_spec else None
orjson = cast(_JsonLib | None, _orjson_module)


class CacheStats:
    def __init__(self):
        self._lock = Lock()
        self.hits = 0
        self.misses = 0
        self.errors = 0

    def record_hit(self) -> None:
        with self._lock:
            self.hits += 1

    def record_miss(self) -> None:
        with self._lock:
            self.misses += 1

    def record_error(self) -> None:
        with self._lock:
            self.errors += 1

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return {
                "hits": float(self.hits),
                "misses": float(self.misses),
                "errors": float(self.errors),
            }


_stats = CacheStats()


def get_stats_client() -> CacheStats:
    """Return the cache stats accumulator."""

    return _stats


def _json_loads(payload: str | bytes) -> Any:
    if orjson is not None:
        return orjson.loads(payload)
    return json.loads(payload)


def _json_dumps(payload: Any) -> str:
    if orjson is not None:
        return orjson.dumps(payload).decode()
    return json.dumps(payload)


def get_client(url: str) -> Redis | None:
    """Return an async Redis client connected to the provided URL."""

    try:
        return Redis.from_url(url, decode_responses=True)
    except RedisError as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="cache.connection_failed",
            message="failed to connect to redis",
            error=str(exc),
        )
        get_stats_client().record_error()
        return None


async def get_json(client: Redis | None, key: str) -> Any:
    """Fetch and JSON-decode the given key from Redis."""

    stats = get_stats_client()
    if client is None:
        stats.record_miss()
        if logger.isEnabledFor(logging.DEBUG):
            log_event(
                logger,
                logging.DEBUG,
                event="cache.get.disabled",
                message="cache client unavailable, treating key as miss",
                key=key,
            )
        return None
    try:
        payload_raw = await client.get(key)
    except RedisError as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="cache.get.error",
            message="redis GET failed",
            key=key,
            error=str(exc),
        )
        stats.record_error()
        return None
    if payload_raw is None:
        stats.record_miss()
        if logger.isEnabledFor(logging.DEBUG):
            log_event(
                logger,
                logging.DEBUG,
                event="cache.get.miss",
                message="cache miss",
                key=key,
            )
        return None
    if isinstance(payload_raw, bytes):
        payload = payload_raw
    elif isinstance(payload_raw, str):
        payload = payload_raw.encode()
    else:
        log_event(
            logger,
            logging.WARNING,
            event="cache.get.invalid_type",
            message="redis GET returned unexpected type",
            key=key,
            value_type=type(payload_raw).__name__,
        )
        stats.record_error()
        return None
    try:
        data = _json_loads(payload)
        if logger.isEnabledFor(logging.DEBUG):
            log_event(
                logger,
                logging.DEBUG,
                event="cache.get.hit",
                message="cache hit",
                key=key,
                size=len(payload),
            )
        stats.record_hit()
        return data
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        log_event(
            logger,
            logging.WARNING,
            event="cache.decode.error",
            message="redis payload was not valid JSON",
            key=key,
            error=str(exc),
        )
        stats.record_error()
        return None


async def get_json_many(client: Redis | None, keys: Sequence[str]) -> dict[str, Any]:
    """Fetch and JSON-decode multiple keys from Redis."""

    results: dict[str, Any] = {}
    if not keys:
        return results
    if client is None:
        stats = get_stats_client()
        for _ in keys:
            stats.record_miss()
        return results
    if not hasattr(client, "mget"):
        for key in keys:
            value = await get_json(client, key)
            if value is not None:
                results[key] = value
        return results
    try:
        payloads = await client.mget(list(keys))
    except RedisError as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="cache.mget.error",
            message="redis MGET failed",
            key_count=len(keys),
            error=str(exc),
        )
        get_stats_client().record_error()
        return results
    stats = get_stats_client()
    for key, payload_raw in zip(keys, payloads, strict=False):
        if payload_raw is None:
            stats.record_miss()
            continue
        if isinstance(payload_raw, bytes):
            payload = payload_raw
        elif isinstance(payload_raw, str):
            payload = payload_raw.encode()
        else:
            log_event(
                logger,
                logging.WARNING,
                event="cache.mget.invalid_type",
                message="redis MGET returned unexpected type",
                key=key,
                value_type=type(payload_raw).__name__,
            )
            stats.record_error()
            continue
        try:
            data = _json_loads(payload)
            results[key] = data
            stats.record_hit()
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            log_event(
                logger,
                logging.WARNING,
                event="cache.mget.decode_error",
                message="redis payload was not valid JSON",
                key=key,
                error=str(exc),
            )
            stats.record_error()
    return results


async def set_json(client: Redis | None, key: str, value: Any, ttl_seconds: int | None = None) -> None:
    """Serialize value as JSON and store it."""

    if client is None:
        if logger.isEnabledFor(logging.DEBUG):
            log_event(
                logger,
                logging.DEBUG,
                event="cache.set.disabled",
                message="cache client unavailable, skipping SET",
                key=key,
            )
        return
    try:
        payload = _json_dumps(value)
        if ttl_seconds:
            await client.set(key, payload, ex=ttl_seconds)
        else:
            await client.set(key, payload)
        if logger.isEnabledFor(logging.DEBUG):
            log_event(
                logger,
                logging.DEBUG,
                event="cache.set",
                message="cache entry written",
                key=key,
                ttl_seconds=ttl_seconds,
                size=len(payload),
            )
    except (RedisError, TypeError) as exc:  # pragma: no cover - defensive
        get_stats_client().record_error()
        log_event(
            logger,
            logging.WARNING,
            event="cache.set.error",
            message="redis SET failed",
            key=key,
            error=str(exc),
        )


async def set_json_many(client: Redis | None, items: Mapping[str, Any], ttl_seconds: int | None = None) -> int:
    """Serialize and store multiple values, returning the count written."""

    if client is None:
        if logger.isEnabledFor(logging.DEBUG):
            log_event(
                logger,
                logging.DEBUG,
                event="cache.set_many.disabled",
                message="cache client unavailable, skipping multi-set",
                key_count=len(items),
            )
        return 0
    if not items:
        return 0
    if not hasattr(client, "pipeline"):
        for key, value in items.items():
            await set_json(client, key, value, ttl_seconds)
        return len(items)
    try:
        pipe = client.pipeline()
        for key, value in items.items():
            payload = _json_dumps(value)
            if ttl_seconds:
                pipe.set(key, payload, ex=ttl_seconds)
            else:
                pipe.set(key, payload)
        await pipe.execute()
        return len(items)
    except (RedisError, TypeError) as exc:  # pragma: no cover - defensive
        get_stats_client().record_error()
        log_event(
            logger,
            logging.WARNING,
            event="cache.set_many.error",
            message="redis pipeline SET failed",
            key_count=len(items),
            error=str(exc),
        )
        return 0


async def delete(client: Redis | None, key: str) -> None:
    """Delete the given key if present."""

    if client is None:
        if logger.isEnabledFor(logging.DEBUG):
            log_event(
                logger,
                logging.DEBUG,
                event="cache.delete.disabled",
                message="cache client unavailable, skipping DELETE",
                key=key,
            )
        return
    try:
        await client.delete(key)
    except RedisError as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="cache.delete.error",
            message="redis DELETE failed",
            key=key,
            error=str(exc),
        )
        get_stats_client().record_error()


async def delete_prefix(client: Redis | None, prefix: str) -> None:
    """Delete all keys matching the specified prefix."""

    if client is None:
        return
    pattern = f"{prefix}*"
    try:
        async for key in iter_scan(client, pattern):
            await _maybe_await(client.delete(key))
    except RedisError as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="cache.delete_prefix.error",
            message="redis prefix deletion failed",
            prefix=prefix,
            error=str(exc),
        )
        get_stats_client().record_error()


async def iter_scan(client: Redis, pattern: str) -> AsyncIterator[str]:
    """Iterate over keys matching pattern."""

    iterator = cast(AsyncIterator[str], client.scan_iter(match=pattern))
    async for key in iterator:
        yield key


def _tag_storage_key(tag: str) -> str:
    return f"{_TAG_PREFIX}{tag}"


async def add_tag(client: Redis | None, tag: str, key: str) -> None:
    """Associate a cache key with a tag for selective invalidation."""

    if client is None:
        return
    try:
        await _maybe_await(client.sadd(_tag_storage_key(tag), key))
        if logger.isEnabledFor(logging.DEBUG):
            log_event(
                logger,
                logging.DEBUG,
                event="cache.tag.added",
                message="cache tag registered",
                tag=tag,
                key=key,
            )
    except RedisError as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="cache.tag.attach_failed",
            message="failed to register cache tag",
            tag=tag,
            key=key,
            error=str(exc),
        )


async def add_tags(client: Redis | None, tags: Sequence[str], key: str) -> None:
    """Associate a cache key with multiple tags."""

    for tag in tags:
        await add_tag(client, tag, key)


async def invalidate_tag(client: Redis | None, tag: str) -> int:
    """Invalidate all cache keys associated with a tag and return the removal count."""

    if client is None:
        return 0
    storage_key = _tag_storage_key(tag)
    removed = 0
    try:
        iterator = cast(AsyncIterator[str], client.sscan_iter(storage_key, count=512))
        batch: list[str] = []
        async for member in iterator:
            if not member:
                continue
            batch.append(member)
            if len(batch) >= 512:
                await _maybe_await(client.delete(*batch))
                removed += len(batch)
                batch.clear()
        if batch:
            await _maybe_await(client.delete(*batch))
            removed += len(batch)
        await _maybe_await(client.delete(storage_key))
        if logger.isEnabledFor(logging.DEBUG):
            log_event(
                logger,
                logging.DEBUG,
                event="cache.tag.invalidated",
                message="cache tag invalidated",
                tag=tag,
                keys=removed,
            )
        return removed
    except RedisError as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="cache.tag.invalidate_failed",
            message="failed to invalidate cache tag",
            tag=tag,
            error=str(exc),
        )
        get_stats_client().record_error()
        return 0


async def _maybe_await(result: Awaitable[Any] | Any) -> Any:
    """Await a result when possible; passthrough otherwise."""

    if inspect.isawaitable(result):
        return await cast(Awaitable[Any], result)
    return result


async def get_schema_tag(client: Redis | None, schema_version_key: str) -> str:
    """Return the cache tag that represents the current schema revision."""

    if client is None:
        return _SCHEMA_UNKNOWN_TAG
    try:
        revision = await client.get(schema_version_key)
    except RedisError as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="cache.schema_tag.error",
            message="failed to read schema version key from redis",
            error=str(exc),
        )
        return _SCHEMA_UNKNOWN_TAG
    if isinstance(revision, str) and revision:
        return f"schema:{revision}"
    return _SCHEMA_UNKNOWN_TAG
