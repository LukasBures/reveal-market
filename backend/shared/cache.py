from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from threading import Lock
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from .logging import log_event

logger = logging.getLogger("reveal_market.cache")

_TAG_PREFIX = "cache:tag:"
_SCHEMA_UNKNOWN_TAG = "schema:unknown"


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


def get_client(url: str) -> Redis | None:
    """Return a Redis client connected to the provided URL."""

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


def get_json(client: Redis | None, key: str) -> Any:
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
        payload = client.get(key)
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
    if payload is None:
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
    try:
        data = json.loads(payload)
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
    except json.JSONDecodeError:
        log_event(
            logger,
            logging.WARNING,
            event="cache.decode.error",
            message="redis payload was not valid JSON",
            key=key,
        )
        stats.record_error()
        return None


def set_json(client: Redis | None, key: str, value: Any, ttl_seconds: int | None = None) -> None:
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
        payload = json.dumps(value)
        if ttl_seconds:
            client.set(key, payload, ex=ttl_seconds)
        else:
            client.set(key, payload)
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


def delete(client: Redis | None, key: str) -> None:
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
        client.delete(key)
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


def delete_prefix(client: Redis | None, prefix: str) -> None:
    """Delete all keys matching the specified prefix."""

    if client is None:
        return
    pattern = f"{prefix}*"
    try:
        for key in list(iter_scan(client, pattern)):
            client.delete(key)
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


def iter_scan(client: Redis, pattern: str) -> Iterable[str]:
    """Iterate over keys matching pattern."""

    return client.scan_iter(match=pattern)


def _tag_storage_key(tag: str) -> str:
    return f"{_TAG_PREFIX}{tag}"


def add_tag(client: Redis | None, tag: str, key: str) -> None:
    """Associate a cache key with a tag for selective invalidation."""

    if client is None:
        return
    try:
        client.sadd(_tag_storage_key(tag), key)
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


def add_tags(client: Redis | None, tags: Sequence[str], key: str) -> None:
    """Associate a cache key with multiple tags."""

    for tag in tags:
        add_tag(client, tag, key)


def invalidate_tag(client: Redis | None, tag: str) -> int:
    """Invalidate all cache keys associated with a tag and return the removal count."""

    if client is None:
        return 0
    storage_key = _tag_storage_key(tag)
    removed = 0
    try:
        scan_iter = getattr(client, "sscan_iter", None)
        iterator = scan_iter(storage_key, count=512) if callable(scan_iter) else iter(client.smembers(storage_key))
        unlink = getattr(client, "unlink", None)
        delete_fn = unlink if callable(unlink) else client.delete
        batch: list[str] = []
        for member in iterator:
            if not member:
                continue
            batch.append(member)
            if len(batch) >= 512:
                delete_fn(*batch)
                removed += len(batch)
                batch.clear()
        if batch:
            delete_fn(*batch)
            removed += len(batch)
        client.delete(storage_key)
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


def get_schema_tag(client: Redis | None, schema_version_key: str) -> str:
    """Return the cache tag that represents the current schema revision."""

    if client is None:
        return _SCHEMA_UNKNOWN_TAG
    try:
        revision = client.get(schema_version_key)
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
