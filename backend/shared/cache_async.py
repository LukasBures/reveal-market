from __future__ import annotations

import base64
import importlib
import importlib.util as importlib_util
import inspect
import json
import logging
import math
import random
import time
import zlib
from collections.abc import AsyncIterator, Awaitable, Mapping, Sequence
from typing import Any, Protocol, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

import shared.logging as shared_logging

from .cache_stats import CacheStats

logger = logging.getLogger("reveal_market.cache_async")

# Prometheus histogram for cache operation latency.
# Defensive import: prometheus_client is optional in some service contexts.
try:
    from prometheus_client import Histogram as _Histogram

    CACHE_OP_DURATION = _Histogram(
        "cache_operation_duration_seconds",
        "Redis cache operation latency",
        ["operation"],
        buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5),
    )
except Exception:  # pragma: no cover - optional dependency
    CACHE_OP_DURATION = None  # type: ignore[assignment]


def _observe_cache_op(operation: str, start: float) -> None:
    """Record cache operation latency if Prometheus is available."""
    if CACHE_OP_DURATION is not None:
        CACHE_OP_DURATION.labels(operation=operation).observe(time.monotonic() - start)


_TAG_PREFIX = "cache:tag:"
_SCHEMA_UNKNOWN_TAG = "schema:unknown"

# Maximum keys per MGET call. A single MGET with >500 keys can block Redis
# (single-threaded) for 20-40ms, starving all other clients including BRPOP
# queue operations. Chunk large key sets to keep each MGET under ~1ms.
_MGET_CHUNK_SIZE = 500


class _JsonLib(Protocol):
    def loads(self, payload: str | bytes) -> Any:
        raise NotImplementedError

    def dumps(self, payload: Any) -> bytes:
        raise NotImplementedError


_orjson_spec = importlib_util.find_spec("orjson")
_orjson_module = importlib.import_module("orjson") if _orjson_spec else None
orjson = cast(_JsonLib | None, _orjson_module)


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


# ---------------------------------------------------------------------------
# Transparent compression for large cache payloads
# ---------------------------------------------------------------------------
_COMPRESSION_THRESHOLD = 1024  # bytes — only compress payloads larger than 1KB
_COMPRESSED_MARKER = "zl:"  # prefix to identify compressed entries


def _json_dumps_compressed(payload: Any) -> str:
    """Serialize to JSON, optionally compressing large payloads."""

    raw = orjson.dumps(payload) if orjson is not None else json.dumps(payload).encode()
    if len(raw) < _COMPRESSION_THRESHOLD:
        return raw.decode() if isinstance(raw, bytes) else raw
    compressed = zlib.compress(raw, level=1)
    if len(compressed) >= len(raw) * 0.9:
        # Compression didn't help enough — skip it
        return raw.decode() if isinstance(raw, bytes) else raw
    return _COMPRESSED_MARKER + base64.b64encode(compressed).decode()


def _json_loads_compressed(payload: str | bytes) -> Any:
    """Deserialize JSON, transparently decompressing if needed."""

    if isinstance(payload, bytes):
        payload = payload.decode()
    if payload.startswith(_COMPRESSED_MARKER):
        compressed = base64.b64decode(payload[len(_COMPRESSED_MARKER) :])
        return _json_loads(zlib.decompress(compressed))
    return _json_loads(payload)


def jittered_ttl(base_ttl: int, jitter_pct: float = 0.1) -> int:
    """Add +/- jitter to TTL to prevent synchronized expiry (thundering herd)."""

    jitter = int(base_ttl * jitter_pct)
    if jitter <= 0:
        return max(1, base_ttl)
    return max(1, base_ttl + random.randint(-jitter, jitter))  # noqa: S311 - not cryptographic


def get_client(url: str) -> Redis | None:
    """Return an async Redis client connected to the provided URL."""

    try:
        return Redis.from_url(
            url,
            decode_responses=True,
            max_connections=20,
            socket_timeout=5.0,
            socket_connect_timeout=3.0,
            retry_on_timeout=True,
            health_check_interval=30,
        )
    except RedisError as exc:  # pragma: no cover - defensive
        shared_logging.log_event(
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

    _t0 = time.monotonic()
    stats = get_stats_client()
    if client is None:
        stats.record_miss()
        if logger.isEnabledFor(logging.DEBUG):
            shared_logging.log_event(
                logger,
                logging.DEBUG,
                event="cache.get.disabled",
                message="cache client unavailable, treating key as miss",
                key=key,
            )
        return None
    try:
        payload_raw = await client.get(key)
        _observe_cache_op("get", _t0)
    except RedisError as exc:  # pragma: no cover - defensive
        _observe_cache_op("get", _t0)
        shared_logging.log_event(
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
            shared_logging.log_event(
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
        shared_logging.log_event(
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
        data = _json_loads_compressed(payload)
        if logger.isEnabledFor(logging.DEBUG):
            shared_logging.log_event(
                logger,
                logging.DEBUG,
                event="cache.get.hit",
                message="cache hit",
                key=key,
                size=len(payload),
            )
        stats.record_hit()
        return data
    except (json.JSONDecodeError, TypeError, ValueError, zlib.error) as exc:
        shared_logging.log_event(
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
    """Fetch and JSON-decode multiple keys from Redis.

    Large key sets are automatically split into chunks of at most _MGET_CHUNK_SIZE
    to prevent a single MGET from blocking Redis (single-threaded) for tens of
    milliseconds and starving other clients such as BRPOP queue readers.
    """

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

    # Split into chunks to avoid blocking Redis with a single huge MGET.
    key_list = list(keys)
    if len(key_list) > _MGET_CHUNK_SIZE:
        for i in range(0, len(key_list), _MGET_CHUNK_SIZE):
            chunk_results = await get_json_many(client, key_list[i : i + _MGET_CHUNK_SIZE])
            results.update(chunk_results)
        return results

    try:
        payloads = await client.mget(key_list)
    except RedisError as exc:  # pragma: no cover - defensive
        shared_logging.log_event(
            logger,
            logging.WARNING,
            event="cache.mget.error",
            message="redis MGET failed",
            key_count=len(keys),
            error=str(exc),
        )
        get_stats_client().record_error()
        return results
    if payloads is None or len(payloads) != len(key_list):
        shared_logging.log_event(
            logger,
            logging.WARNING,
            event="cache.mget.length_mismatch",
            message="redis MGET returned unexpected number of payloads",
            expected=len(key_list),
            actual=0 if payloads is None else len(payloads),
        )
        get_stats_client().record_error()
        return results
    stats = get_stats_client()
    for key, payload_raw in zip(key_list, payloads, strict=True):
        if payload_raw is None:
            stats.record_miss()
            continue
        if isinstance(payload_raw, bytes):
            payload = payload_raw
        elif isinstance(payload_raw, str):
            payload = payload_raw.encode()
        else:
            shared_logging.log_event(
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
            data = _json_loads_compressed(payload)
            results[key] = data
            stats.record_hit()
        except (json.JSONDecodeError, TypeError, ValueError, zlib.error) as exc:
            shared_logging.log_event(
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
    """Serialize value as JSON and store it, compressing large payloads."""

    if client is None:
        if logger.isEnabledFor(logging.DEBUG):
            shared_logging.log_event(
                logger,
                logging.DEBUG,
                event="cache.set.disabled",
                message="cache client unavailable, skipping SET",
                key=key,
            )
        return
    _t0 = time.monotonic()
    try:
        payload = _json_dumps_compressed(value)
        if ttl_seconds is not None and ttl_seconds <= 0:
            if logger.isEnabledFor(logging.DEBUG):
                shared_logging.log_event(
                    logger,
                    logging.DEBUG,
                    event="cache.set.skip",
                    message="skipping cache set due to non-positive ttl",
                    key=key,
                    ttl_seconds=ttl_seconds,
                )
            return
        if ttl_seconds is not None:
            await client.set(key, payload, ex=jittered_ttl(ttl_seconds))
        else:
            await client.set(key, payload)
        _observe_cache_op("set", _t0)
        if logger.isEnabledFor(logging.DEBUG):
            shared_logging.log_event(
                logger,
                logging.DEBUG,
                event="cache.set",
                message="cache entry written",
                key=key,
                ttl_seconds=ttl_seconds,
                size=len(payload),
            )
    except (RedisError, TypeError) as exc:  # pragma: no cover - defensive
        _observe_cache_op("set", _t0)
        get_stats_client().record_error()
        shared_logging.log_event(
            logger,
            logging.WARNING,
            event="cache.set.error",
            message="redis SET failed",
            key=key,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Probabilistic Early Recomputation (PER) — cache stampede protection
# ---------------------------------------------------------------------------
_PER_TTL_BUFFER = 0.2  # Store with 20% extra TTL so key survives during refresh
_PER_BETA = 1.0  # Controls how aggressively early refresh triggers


class PERResult:
    """Result of a PER-aware cache read."""

    __slots__ = ("data", "should_refresh")

    def __init__(self, data: Any, should_refresh: bool) -> None:
        self.data = data
        self.should_refresh = should_refresh


async def set_json_per(client: Redis | None, key: str, value: Any, ttl_seconds: int) -> None:
    """Store a value with PER metadata for stampede-safe reads."""

    if client is None or ttl_seconds <= 0:
        return
    envelope = {
        "_v": value,
        "_t": time.time(),
        "_ttl": ttl_seconds,
    }
    # Store with buffered TTL so the key persists during early-refresh window
    storage_ttl = int(ttl_seconds * (1 + _PER_TTL_BUFFER))
    await set_json(client, key, envelope, storage_ttl)


async def get_json_per(client: Redis | None, key: str, beta: float = _PER_BETA) -> PERResult | None:
    """Fetch a PER-wrapped value; return data + whether the caller should refresh.

    Returns None on cache miss. On hit, ``should_refresh=True`` means this caller
    should trigger an async background refresh while still returning stale data.
    """

    raw = await get_json(client, key)
    if raw is None:
        return None
    # Support both PER-wrapped and plain values for backward compatibility
    if not isinstance(raw, dict) or "_v" not in raw or "_t" not in raw or "_ttl" not in raw:
        return PERResult(data=raw, should_refresh=False)
    data = raw["_v"]
    set_time = float(raw["_t"])
    original_ttl = float(raw["_ttl"])
    elapsed = time.time() - set_time
    remaining = original_ttl - elapsed
    # XFetch: remaining - beta * ln(random()) < 0 => should_refresh
    try:
        xfetch_delta = beta * math.log(random.random())  # noqa: S311 - not cryptographic
    except ValueError:
        xfetch_delta = 0.0
    should_refresh = (remaining + xfetch_delta) < 0
    return PERResult(data=data, should_refresh=should_refresh)


async def set_json_many(client: Redis | None, items: Mapping[str, Any], ttl_seconds: int | None = None) -> int:
    """Serialize and store multiple values, returning the count written."""

    if client is None:
        if logger.isEnabledFor(logging.DEBUG):
            shared_logging.log_event(
                logger,
                logging.DEBUG,
                event="cache.set_many.disabled",
                message="cache client unavailable, skipping multi-set",
                key_count=len(items),
            )
        return 0
    if not items:
        return 0
    if ttl_seconds is not None and ttl_seconds <= 0:
        if logger.isEnabledFor(logging.DEBUG):
            shared_logging.log_event(
                logger,
                logging.DEBUG,
                event="cache.set_many.skip",
                message="skipping cache set due to non-positive ttl",
                key_count=len(items),
                ttl_seconds=ttl_seconds,
            )
        return 0
    if not hasattr(client, "pipeline"):
        for key, value in items.items():
            await set_json(client, key, value, ttl_seconds)
        return len(items)
    try:
        pipe = client.pipeline(transaction=False)
        for key, value in items.items():
            payload = _json_dumps_compressed(value)
            if ttl_seconds is not None:
                pipe.set(key, payload, ex=jittered_ttl(ttl_seconds))
            else:
                pipe.set(key, payload)
        await pipe.execute()
        return len(items)
    except (RedisError, TypeError) as exc:  # pragma: no cover - defensive
        get_stats_client().record_error()
        shared_logging.log_event(
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
            shared_logging.log_event(
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
        shared_logging.log_event(
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
        shared_logging.log_event(
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

    async for key in client.scan_iter(match=pattern):  # type: ignore[union-attr]
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
            shared_logging.log_event(
                logger,
                logging.DEBUG,
                event="cache.tag.added",
                message="cache tag registered",
                tag=tag,
                key=key,
            )
    except RedisError as exc:  # pragma: no cover - defensive
        shared_logging.log_event(
            logger,
            logging.WARNING,
            event="cache.tag.attach_failed",
            message="failed to register cache tag",
            tag=tag,
            key=key,
            error=str(exc),
        )


async def add_tags(client: Redis | None, tags: Sequence[str], key: str) -> None:
    """Associate a cache key with multiple tags via a single pipeline flush."""

    if client is None or not tags:
        return
    if len(tags) == 1:
        await add_tag(client, tags[0], key)
        return
    if not hasattr(client, "pipeline"):
        for tag in tags:
            await add_tag(client, tag, key)
        return
    try:
        pipe = client.pipeline(transaction=False)
        for tag in tags:
            pipe.sadd(_tag_storage_key(tag), key)
        await pipe.execute()
    except RedisError as exc:
        shared_logging.log_event(
            logger,
            logging.WARNING,
            event="cache.tags.pipeline_failed",
            message="pipelined tag attach failed",
            tag_count=len(tags),
            key=key,
            error=str(exc),
        )


_INVALIDATE_TAG_LUA = """
local tag_key = KEYS[1]
local removed = 0
local cursor = "0"
repeat
    local result = redis.call('SSCAN', tag_key, cursor, 'COUNT', 512)
    cursor = result[1]
    local members = result[2]
    if #members > 0 then
        redis.call('UNLINK', unpack(members))
        removed = removed + #members
    end
until cursor == "0"
redis.call('UNLINK', tag_key)
return removed
"""


async def invalidate_tag(client: Redis | None, tag: str) -> int:
    """Atomically invalidate all cache keys associated with a tag and return the removal count.

    Uses a Lua script when available to ensure no keys are added between the
    scan and the delete.  Falls back to SSCAN + DELETE for clients that do not
    support ``EVAL`` (e.g. in-memory test doubles).
    """

    if client is None:
        return 0
    _t0 = time.monotonic()
    storage_key = _tag_storage_key(tag)
    try:
        if hasattr(client, "eval"):
            removed = await client.eval(_INVALIDATE_TAG_LUA, 1, storage_key)  # type: ignore[union-attr,misc]
            removed = int(removed) if removed else 0
        else:
            # Fallback: non-atomic SSCAN + DELETE for test doubles
            removed = 0
            iterator = client.sscan_iter(storage_key, count=512)  # type: ignore[union-attr]
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
        _observe_cache_op("invalidate", _t0)
        if logger.isEnabledFor(logging.DEBUG):
            shared_logging.log_event(
                logger,
                logging.DEBUG,
                event="cache.tag.invalidated",
                message="cache tag invalidated",
                tag=tag,
                keys=removed,
            )
        return removed
    except RedisError as exc:  # pragma: no cover - defensive
        _observe_cache_op("invalidate", _t0)
        shared_logging.log_event(
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
    """Compatibility helper for Redis calls that may be sync or async.

    Some Redis client methods are synchronous in certain configurations or
    library versions and asynchronous in others. This helper normalizes those
    differences by awaiting the result when it is awaitable and otherwise
    returning it directly. Use this only for known Redis operations that can be
    either sync or async, not as a general pattern for arbitrary code.
    """

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
        shared_logging.log_event(
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
