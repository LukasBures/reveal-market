from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Sequence

from redis import Redis
from redis.exceptions import RedisError

from .logging import log_event

logger = logging.getLogger("reveal_market.cache")

_TAG_PREFIX = "cache:tag:"
_SCHEMA_UNKNOWN_TAG = "schema:unknown"


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
        return None


def get_json(client: Redis | None, key: str) -> Any:
    """Fetch and JSON-decode the given key from Redis."""

    if client is None:
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
        return None
    if payload is None:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        log_event(
            logger,
            logging.WARNING,
            event="cache.decode.error",
            message="redis payload was not valid JSON",
            key=key,
        )
        return None


def set_json(client: Redis | None, key: str, value: Any, ttl_seconds: int | None = None) -> None:
    """Serialize value as JSON and store it."""

    if client is None:
        return
    try:
        payload = json.dumps(value)
        if ttl_seconds:
            client.set(key, payload, ex=ttl_seconds)
        else:
            client.set(key, payload)
    except (RedisError, TypeError) as exc:  # pragma: no cover - defensive
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


def invalidate_tag(client: Redis | None, tag: str) -> list[str]:
    """Invalidate all cache keys associated with a tag."""

    if client is None:
        return []
    storage_key = _tag_storage_key(tag)
    try:
        members = list(client.smembers(storage_key))
        if members:
            client.delete(*members)
        client.delete(storage_key)
        return members
    except RedisError as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="cache.tag.invalidate_failed",
            message="failed to invalidate cache tag",
            tag=tag,
            error=str(exc),
        )
        return []


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
