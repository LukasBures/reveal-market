"""Live Redis integration tests for ``shared.cache_async``.

These tests exercise every optimization feature (compression, PER, pipelines,
Lua scripts, connection pooling, TTL jitter) against a real Redis 7 instance.
They are skipped automatically when Redis is not available.

Run with::

    cd backend/shared && uv run --project . --extra dev pytest tests/test_cache_async_live.py -v

Or via marker::

    cd backend/shared && uv run --project . --extra dev pytest -m live -v
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time

import pytest
from shared import cache_async
from shared.cache_async import (
    _COMPRESSION_THRESHOLD,
    _TAG_PREFIX,
    PERResult,
    add_tag,
    add_tags,
    delete,
    delete_prefix,
    get_json,
    get_json_many,
    get_json_per,
    get_schema_tag,
    get_stats_client,
    invalidate_tag,
    jittered_ttl,
    set_json,
    set_json_many,
    set_json_per,
)

pytestmark = pytest.mark.live


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _large_payload(n_items: int = 20, pad: int = 100) -> dict:
    """Build a dict whose JSON representation exceeds _COMPRESSION_THRESHOLD."""
    return {"items": [{"name": f"item_{i}", "description": "x" * pad} for i in range(n_items)]}


# ── Compression ───────────────────────────────────────────────────────────


class TestCompression:
    """Verify zlib compression for large payloads and passthrough for small ones."""

    async def test_small_payload_not_compressed(self, redis_client, raw_redis_client):
        small_data = {"key": "value", "number": 42}
        await set_json(redis_client, "test:small", small_data, ttl_seconds=60)

        raw_value = await raw_redis_client.get("test:small")
        assert raw_value is not None
        assert not raw_value.startswith(b"zl:"), "Small payload should not be compressed"
        parsed = json.loads(raw_value)
        assert parsed == small_data

    async def test_large_payload_compressed(self, redis_client, raw_redis_client):
        large_data = _large_payload()
        raw_json = json.dumps(large_data).encode()
        assert len(raw_json) > _COMPRESSION_THRESHOLD, "Test data must exceed threshold"

        await set_json(redis_client, "test:large", large_data, ttl_seconds=60)

        raw_value = await raw_redis_client.get("test:large")
        assert raw_value is not None
        assert raw_value.startswith(b"zl:"), "Large payload should have zl: marker"

    async def test_compressed_round_trip(self, redis_client):
        large_data = _large_payload(n_items=15, pad=200)
        await set_json(redis_client, "test:rt", large_data, ttl_seconds=60)
        result = await get_json(redis_client, "test:rt")
        assert result == large_data

    async def test_uncompressed_round_trip(self, redis_client):
        small_data = {"status": "ok"}
        await set_json(redis_client, "test:small:rt", small_data, ttl_seconds=60)
        result = await get_json(redis_client, "test:small:rt")
        assert result == small_data

    async def test_backward_compat_plain_json(self, redis_client):
        """Manually stored plain JSON should be readable by get_json()."""
        plain_json = '{"legacy": true, "version": 1}'
        await redis_client.set("test:legacy", plain_json, ex=60)
        result = await get_json(redis_client, "test:legacy")
        assert result == {"legacy": True, "version": 1}

    async def test_compression_skip_when_not_effective(self, redis_client, raw_redis_client):
        """Random-like data that doesn't compress well should be stored uncompressed."""
        random_payload = {"data": base64.b64encode(os.urandom(1500)).decode()}
        raw_check = json.dumps(random_payload).encode()
        compressed_check = __import__("zlib").compress(raw_check, level=1)
        if len(compressed_check) >= len(raw_check) * 0.9:
            await set_json(redis_client, "test:random", random_payload, ttl_seconds=60)
            raw_value = await raw_redis_client.get("test:random")
            assert raw_value is not None
            assert not raw_value.startswith(b"zl:")
        else:
            pytest.skip("Generated data compressed too well for this test case")


# ── PER (Probabilistic Early Recomputation) ───────────────────────────────


class TestPER:
    """Verify PER envelope storage, retrieval, and XFetch refresh logic."""

    async def test_set_get_per_round_trip(self, redis_client):
        data = {"market_id": "evt-123", "prices": [0.55, 0.45]}
        await set_json_per(redis_client, "test:per:rt", data, ttl_seconds=300)
        result = await get_json_per(redis_client, "test:per:rt")
        assert result is not None
        assert isinstance(result, PERResult)
        assert result.data == data

    async def test_fresh_per_entry_should_not_refresh(self, redis_client):
        """A just-written PER entry should almost certainly not trigger refresh."""
        data = {"fresh": True}
        await set_json_per(redis_client, "test:per:fresh", data, ttl_seconds=300)
        refresh_count = 0
        for _ in range(50):
            result = await get_json_per(redis_client, "test:per:fresh")
            assert result is not None
            if result.should_refresh:
                refresh_count += 1
        assert refresh_count == 0, f"Expected 0 refreshes for fresh entry, got {refresh_count}"

    async def test_nearly_expired_per_entry_should_refresh(self, redis_client):
        """A PER entry near expiry should trigger refresh with high probability."""
        data = {"stale": True}
        envelope = {"_v": data, "_t": time.time() - 299, "_ttl": 300}
        await set_json(redis_client, "test:per:stale", envelope, ttl_seconds=600)

        refresh_count = 0
        trials = 100
        for _ in range(trials):
            result = await get_json_per(redis_client, "test:per:stale")
            assert result is not None
            assert result.data == data
            if result.should_refresh:
                refresh_count += 1
        # With 1s remaining and beta=1.0, P(refresh) ~ 36.8% per trial.
        # Over 100 trials, P(< 10 refreshes) is astronomically small.
        assert refresh_count >= 10, f"Expected significant refreshes, got {refresh_count}/{trials}"

    async def test_plain_value_backward_compat(self, redis_client):
        """get_json_per on a non-PER value returns data with should_refresh=False."""
        plain = {"plain": "value"}
        await set_json(redis_client, "test:per:plain", plain, ttl_seconds=60)
        result = await get_json_per(redis_client, "test:per:plain")
        assert result is not None
        assert result.data == plain
        assert result.should_refresh is False

    async def test_per_miss_returns_none(self, redis_client):
        result = await get_json_per(redis_client, "test:per:nonexistent")
        assert result is None


# ── TTL Jittering ─────────────────────────────────────────────────────────


class TestJitteredTTL:
    """Verify TTL jitter stays within expected bounds."""

    def test_jittered_ttl_within_bounds(self):
        base = 300
        results = [jittered_ttl(base) for _ in range(1000)]
        assert all(270 <= t <= 330 for t in results), f"Out of range: min={min(results)}, max={max(results)}"
        assert len(set(results)) > 1, "Jitter should produce variation"

    def test_jittered_ttl_minimum_one(self):
        assert jittered_ttl(1) >= 1
        assert jittered_ttl(0) >= 1


# ── Pipeline Operations ──────────────────────────────────────────────────


class TestPipelineOperations:
    """Verify pipelined add_tags, set_json_many, and get_json_many."""

    async def test_add_tags_stores_all_memberships(self, redis_client):
        tags = ["tag:alpha", "tag:beta", "tag:gamma", "tag:delta", "tag:epsilon"]
        await add_tags(redis_client, tags, "my-cache-key")
        for tag in tags:
            members = await redis_client.smembers(f"{_TAG_PREFIX}{tag}")
            assert "my-cache-key" in members, f"Key missing from tag set for {tag}"

    async def test_add_tags_single_tag_fallback(self, redis_client):
        await add_tags(redis_client, ["solo-tag"], "key:solo")
        members = await redis_client.smembers(f"{_TAG_PREFIX}solo-tag")
        assert "key:solo" in members

    async def test_set_json_many_stores_all_items(self, redis_client):
        items = {f"batch:key:{i}": {"index": i, "data": f"value_{i}"} for i in range(15)}
        count = await set_json_many(redis_client, items, ttl_seconds=120)
        assert count == 15
        for key, expected in items.items():
            result = await get_json(redis_client, key)
            assert result == expected, f"Mismatch for {key}"

    async def test_set_json_many_empty_dict(self, redis_client):
        count = await set_json_many(redis_client, {}, ttl_seconds=60)
        assert count == 0

    async def test_get_json_many_mixed_keys(self, redis_client):
        await set_json(redis_client, "multi:a", {"val": "a"}, ttl_seconds=60)
        await set_json(redis_client, "multi:b", {"val": "b"}, ttl_seconds=60)
        results = await get_json_many(redis_client, ["multi:a", "multi:b", "multi:c"])
        assert results["multi:a"] == {"val": "a"}
        assert results["multi:b"] == {"val": "b"}
        assert "multi:c" not in results

    async def test_get_json_many_empty_keys(self, redis_client):
        results = await get_json_many(redis_client, [])
        assert results == {}

    async def test_get_json_many_with_compressed_values(self, redis_client):
        large_data = _large_payload(n_items=15, pad=200)
        await set_json(redis_client, "multi:compressed", large_data, ttl_seconds=60)
        await set_json(redis_client, "multi:small", {"tiny": True}, ttl_seconds=60)
        results = await get_json_many(redis_client, ["multi:compressed", "multi:small"])
        assert results["multi:compressed"] == large_data
        assert results["multi:small"] == {"tiny": True}


# ── Lua Tag Invalidation ─────────────────────────────────────────────────


class TestLuaTagInvalidation:
    """Verify the _INVALIDATE_TAG_LUA script via invalidate_tag()."""

    async def test_invalidate_removes_all_tagged_keys(self, redis_client):
        tag = "test:bulk-invalidation"
        keys = [f"item:{i}" for i in range(10)]
        for key in keys:
            await set_json(redis_client, key, {"id": key}, ttl_seconds=300)
            await add_tag(redis_client, tag, key)

        for key in keys:
            assert await get_json(redis_client, key) is not None

        removed = await invalidate_tag(redis_client, tag)
        assert removed == 10

        for key in keys:
            assert await get_json(redis_client, key) is None

        members = await redis_client.smembers(f"{_TAG_PREFIX}{tag}")
        assert len(members) == 0

    async def test_invalidate_empty_tag_returns_zero(self, redis_client):
        removed = await invalidate_tag(redis_client, "nonexistent:tag")
        assert removed == 0

    async def test_invalidate_tag_with_compressed_values(self, redis_client):
        tag = "test:compressed-invalidation"
        large_data = _large_payload(n_items=20, pad=200)
        await set_json(redis_client, "compressed:target", large_data, ttl_seconds=300)
        await add_tag(redis_client, tag, "compressed:target")

        removed = await invalidate_tag(redis_client, tag)
        assert removed == 1
        assert await get_json(redis_client, "compressed:target") is None

    async def test_invalidate_tag_idempotent(self, redis_client):
        tag = "test:idempotent"
        await set_json(redis_client, "idem:key", {"data": 1}, ttl_seconds=300)
        await add_tag(redis_client, tag, "idem:key")

        first = await invalidate_tag(redis_client, tag)
        assert first == 1
        second = await invalidate_tag(redis_client, tag)
        assert second == 0


# ── Lock Safety (Lua Compare-and-Delete) ──────────────────────────────────


class TestLockSafety:
    """Verify the Lua compare-and-delete pattern for distributed locks."""

    _LOCK_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

    async def test_release_with_correct_token_deletes_key(self, redis_client):
        lock_key = "lock:test:correct"
        token = "owner-abc-123"  # noqa: S105
        await redis_client.set(lock_key, token, ex=30, nx=True)
        result = await redis_client.eval(self._LOCK_RELEASE_LUA, 1, lock_key, token)
        assert result == 1
        assert await redis_client.get(lock_key) is None

    async def test_release_with_wrong_token_preserves_key(self, redis_client):
        lock_key = "lock:test:wrong"
        correct_token = "owner-real"  # noqa: S105
        await redis_client.set(lock_key, correct_token, ex=30, nx=True)
        result = await redis_client.eval(self._LOCK_RELEASE_LUA, 1, lock_key, "attacker-fake")
        assert result == 0
        remaining = await redis_client.get(lock_key)
        assert remaining == correct_token

    async def test_release_nonexistent_lock_returns_zero(self, redis_client):
        result = await redis_client.eval(self._LOCK_RELEASE_LUA, 1, "lock:ghost", "any-token")
        assert result == 0


# ── Connection Pool ───────────────────────────────────────────────────────


class TestConnectionPool:
    """Verify connection pooling behavior under concurrent load."""

    async def test_pool_limits_concurrent_connections(self, _redis_server):
        """With max_connections=2, excess concurrent requests raise ConnectionError."""
        from redis.asyncio import Redis
        from redis.exceptions import ConnectionError as RedisConnectionError

        client = Redis.from_url("redis://localhost:6379/15", decode_responses=True, max_connections=2)
        await client.flushdb()

        errors = 0

        async def write_and_read(i: int) -> bool:
            nonlocal errors
            try:
                await client.set(f"pool:key:{i}", f"value:{i}", ex=30)
                await client.get(f"pool:key:{i}")
                return True
            except RedisConnectionError:
                errors += 1
                return False

        results = await asyncio.gather(*[write_and_read(i) for i in range(10)])
        # Some should succeed (pool size=2), some may fail due to pool exhaustion.
        assert any(results), "At least some operations should succeed"
        assert errors > 0, "Pool limit should cause connection errors under high concurrency"
        await client.aclose()

    async def test_adequate_pool_handles_concurrent_operations(self, _redis_server):
        """With a sufficiently large pool, all concurrent operations succeed."""
        from redis.asyncio import Redis

        client = Redis.from_url("redis://localhost:6379/15", decode_responses=True, max_connections=20)
        await client.flushdb()

        async def write_and_read(i: int) -> bool:
            await client.set(f"pool:key:{i}", f"value:{i}", ex=30)
            val = await client.get(f"pool:key:{i}")
            return val == f"value:{i}"

        results = await asyncio.gather(*[write_and_read(i) for i in range(10)])
        assert all(results), "All operations should succeed with adequate pool"
        await client.aclose()

    async def test_get_client_returns_configured_client(self, _redis_server):
        client = cache_async.get_client("redis://localhost:6379/15")
        assert client is not None
        pong = await client.ping()
        assert pong is True
        await client.aclose()


# ── Schema Tag ────────────────────────────────────────────────────────────


class TestSchemaTag:
    async def test_schema_tag_returns_revision(self, redis_client):
        await redis_client.set("reveal_market:schema_version", "abc123")
        tag = await get_schema_tag(redis_client, "reveal_market:schema_version")
        assert tag == "schema:abc123"

    async def test_schema_tag_returns_unknown_when_missing(self, redis_client):
        tag = await get_schema_tag(redis_client, "reveal_market:schema_version")
        assert tag == "schema:unknown"


# ── Graceful Degradation ─────────────────────────────────────────────────


class TestGracefulDegradation:
    """Verify operations return safe defaults when Redis is unavailable."""

    async def test_get_json_none_client(self):
        assert await get_json(None, "any:key") is None

    async def test_set_json_none_client(self):
        await set_json(None, "any:key", {"data": 1}, ttl_seconds=60)

    async def test_set_json_many_none_client(self):
        assert await set_json_many(None, {"k": "v"}, ttl_seconds=60) == 0

    async def test_invalidate_tag_none_client(self):
        assert await invalidate_tag(None, "any:tag") == 0

    async def test_get_json_many_none_client(self):
        assert await get_json_many(None, ["k1", "k2"]) == {}

    async def test_get_json_per_none_client(self):
        assert await get_json_per(None, "any:key") is None

    async def test_set_json_per_none_client(self):
        await set_json_per(None, "any:key", {"data": 1}, ttl_seconds=60)

    async def test_add_tags_none_client(self):
        await add_tags(None, ["tag1", "tag2"], "key")

    async def test_get_schema_tag_none_client(self):
        assert await get_schema_tag(None, "some:key") == "schema:unknown"

    async def test_delete_none_client(self):
        await delete(None, "any:key")


# ── Deletion ──────────────────────────────────────────────────────────────


class TestDeletion:
    async def test_delete_removes_key(self, redis_client):
        await set_json(redis_client, "del:target", {"x": 1}, ttl_seconds=60)
        assert await get_json(redis_client, "del:target") is not None
        await delete(redis_client, "del:target")
        assert await get_json(redis_client, "del:target") is None

    async def test_delete_prefix_removes_matching_keys(self, redis_client):
        for i in range(5):
            await set_json(redis_client, f"pfx:group:{i}", {"i": i}, ttl_seconds=60)
        await set_json(redis_client, "other:key", {"keep": True}, ttl_seconds=60)

        await delete_prefix(redis_client, "pfx:group:")

        for i in range(5):
            assert await get_json(redis_client, f"pfx:group:{i}") is None
        assert await get_json(redis_client, "other:key") == {"keep": True}


# ── Full Flow Integration ─────────────────────────────────────────────────


class TestFullFlowIntegration:
    """End-to-end cache flows that mirror production usage patterns."""

    async def test_tag_based_cache_lifecycle(self, redis_client):
        """Write -> tag -> read -> invalidate -> verify miss."""
        market_data = {"event_id": "evt-flow-1", "title": "Flow Test", "status": "commit"}
        await set_json(redis_client, "market:evt-flow-1", market_data, ttl_seconds=300)
        await set_json(redis_client, "v1:markets:list:page1", {"event_ids": ["evt-flow-1"]}, ttl_seconds=300)

        await add_tag(redis_client, "markets:list", "v1:markets:list:page1")
        await add_tag(redis_client, "market:evt-flow-1", "market:evt-flow-1")
        await add_tags(redis_client, ["schema:rev42", "markets:list"], "v1:markets:list:page1")

        assert await get_json(redis_client, "market:evt-flow-1") == market_data
        assert await get_json(redis_client, "v1:markets:list:page1") == {"event_ids": ["evt-flow-1"]}

        removed = await invalidate_tag(redis_client, "markets:list")
        assert removed >= 1

        assert await get_json(redis_client, "v1:markets:list:page1") is None
        # Individual market record is tagged separately — should still exist.
        assert await get_json(redis_client, "market:evt-flow-1") == market_data

        removed = await invalidate_tag(redis_client, "market:evt-flow-1")
        assert removed == 1
        assert await get_json(redis_client, "market:evt-flow-1") is None

    async def test_per_cache_with_tag_invalidation(self, redis_client):
        """PER-wrapped entry + tag invalidation simulates the /events endpoint flow."""
        data = {"event_ids": ["evt-per-1", "evt-per-2"]}
        await set_json_per(redis_client, "v1:markets:list:per-test", data, ttl_seconds=300)
        await add_tags(redis_client, ["markets:list", "schema:rev99"], "v1:markets:list:per-test")

        result = await get_json_per(redis_client, "v1:markets:list:per-test")
        assert result is not None
        assert result.data == data
        assert result.should_refresh is False

        removed = await invalidate_tag(redis_client, "markets:list")
        assert removed >= 1

        assert await get_json_per(redis_client, "v1:markets:list:per-test") is None

    async def test_set_json_many_then_get_json_many_round_trip(self, redis_client):
        items = {f"batch:{i}": {"index": i, "label": f"item-{i}"} for i in range(10)}
        count = await set_json_many(redis_client, items, ttl_seconds=120)
        assert count == 10

        results = await get_json_many(redis_client, list(items.keys()))
        assert len(results) == 10
        for key, expected in items.items():
            assert results[key] == expected


# ── Cache Stats ───────────────────────────────────────────────────────────


class TestCacheStats:
    async def test_stats_accumulate_across_operations(self, redis_client):
        stats = get_stats_client()
        initial = stats.snapshot()

        await set_json(redis_client, "stats:key", {"v": 1}, ttl_seconds=60)
        await get_json(redis_client, "stats:key")  # hit
        await get_json(redis_client, "stats:missing")  # miss

        after = stats.snapshot()
        assert after["hits"] >= initial["hits"] + 1
        assert after["misses"] >= initial["misses"] + 1
