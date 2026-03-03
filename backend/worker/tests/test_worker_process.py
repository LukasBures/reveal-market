from __future__ import annotations

# ruff: noqa: S101
import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import app.database as db
import app.market_sync as market_sync
import app.prime as prime
import app.proofs as proofs
import app.runtime as runtime_module
import app.service as worker_service
import httpx
import pytest
from app.polymarket import MarketPayload, build_filters_from_settings
from app.prover_client import SettlementProofResponse
from app.schema import SchemaSyncResult
from prometheus_client import REGISTRY
from pydantic import SecretStr
from shared import cache_async as shared_cache
from shared import models as shared_models
from shared.cache_keys import markets_list_cache_key, suggest_cache_key
from shared.merkle import build_merkle_root_and_paths
from shared.models import Base, Market, Settlement
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker


# Local helper to stand in for test_sync_market (keeps this test self contained)
def create_in_memory_db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, future=True)
    return engine, session_factory


async def create_async_in_memory_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, future=True, expire_on_commit=False)
    return engine, session_factory


class DummySession:
    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    def expunge_all(self) -> None:
        return None


@contextlib.asynccontextmanager
async def dummy_session_scope():
    yield DummySession()


async def async_none(*_args: Any, **_kwargs: Any) -> None:
    return None


async def async_zero(*_args: Any, **_kwargs: Any) -> int:
    return 0


class DummyRedis:
    def __init__(self):
        self.store: dict[str, Any] = {}
        self.last_set: dict[str, Any] | None = None
        self._ttls: dict[str, int | None] = {}

    async def set(self, key: str, value: Any, ex: int | None = None, nx: bool = False):
        if nx and key in self.store:
            return False
        self.store[key] = value
        self.last_set = {"key": key, "value": value, "ttl": ex}
        self._ttls[key] = ex
        return True

    async def get(self, key: str):
        return self.store.get(key)

    async def delete(self, *keys: str):
        for key in keys:
            self.store.pop(key, None)

    async def scan_iter(self, match: str):
        prefix = match[:-1] if match.endswith("*") else match
        for key in list(self.store.keys()):
            if key.startswith(prefix):
                yield key

    async def sscan_iter(self, key: str, count: int | None = None):
        members = self.store.get(key, set())
        if isinstance(members, set):
            for member in members:
                yield member

    async def sadd(self, key: str, value: str):
        bucket = self.store.setdefault(key, set())
        if not isinstance(bucket, set):
            bucket = set()
            self.store[key] = bucket
        before = len(bucket)
        bucket.add(value)
        return 1 if len(bucket) > before else 0

    async def srem(self, key: str, value: str):
        bucket = self.store.get(key)
        if isinstance(bucket, set) and value in bucket:
            bucket.remove(value)
            return 1
        return 0

    async def smembers(self, key: str):
        members = self.store.get(key)
        if isinstance(members, set):
            return set(members)
        return set()

    async def ttl(self, key: str):
        ttl = self._ttls.get(key)
        if ttl is None:
            return -1
        return ttl

    async def expire(self, key: str, ttl_seconds: int):
        if key not in self.store:
            return 0
        self._ttls[key] = int(ttl_seconds)
        return 1

    async def lpush(self, key: str, value: Any):
        queue = self.store.setdefault(key, [])
        if not isinstance(queue, list):
            queue = []
            self.store[key] = queue
        queue.insert(0, value)

    async def rpush(self, key: str, value: Any):
        queue = self.store.setdefault(key, [])
        if not isinstance(queue, list):
            queue = []
            self.store[key] = queue
        queue.append(value)
        return len(queue)

    async def brpop(self, keys, timeout: int | None = None):
        key = keys[0] if keys else None
        if key is None:
            return None
        queue = self.store.get(key, [])
        if not queue:
            return None
        value = queue.pop()
        return key, value

    async def lpop(self, key: str):
        queue = self.store.get(key, [])
        if not isinstance(queue, list) or not queue:
            return None
        return queue.pop(0)

    async def llen(self, key: str) -> int:
        queue = self.store.get(key, [])
        return len(queue) if isinstance(queue, list) else 0

    async def lindex(self, key: str, index: int):
        queue = self.store.get(key, [])
        if not isinstance(queue, list):
            return None
        try:
            return queue[index]
        except IndexError:
            return None

    async def eval(self, script: str, numkeys: int, *args):
        if numkeys == 2:
            queue_key, dedupe_key = args[0], args[1]
            # Proof queue script enforces max depth before enqueueing.
            if "LLEN" in script:
                max_depth = int(args[2])
                job_id = args[3]
                payload = args[4]
                depth = await self.llen(queue_key)
                if depth >= max_depth:
                    return 0
                added = await self.sadd(dedupe_key, job_id)
                if added == 0:
                    return -1
                await self.rpush(queue_key, payload)
                return 1
            # Settlement queue script atomically SADD+RPUSH+EXPIRE.
            job_id = args[2]
            payload = args[3]
            ttl_seconds = int(args[4])
            added = await self.sadd(dedupe_key, job_id)
            if added == 0:
                return 0
            await self.rpush(queue_key, payload)
            await self.expire(dedupe_key, ttl_seconds)
            return 1
        if numkeys == 1:
            key = args[0]
            # Tag invalidation script: numkeys=1, no additional ARGV
            if len(args) == 1:
                members = list(self.store.get(key, set()) or set()) if isinstance(self.store.get(key), set) else []
                for member in members:
                    self.store.pop(member, None)
                self.store.pop(key, None)
                return len(members)
            # Lock release script: numkeys=1, ARGV=[expected_value]
            expected_value = args[1]
            current_value = await self.get(key)
            if current_value == expected_value:
                await self.delete(key)
                return 1
            return 0
        raise RuntimeError("unsupported numkeys")

    async def clear(self):
        self.store.clear()
        self.last_set = None
        self._ttls.clear()


class _CounterRecorder:
    def __init__(self, target: dict[str, Any]):
        self.target = target

    def inc(self, amount: float = 1.0):
        self.target["amount"] += amount


class DummyCounter:
    def __init__(self):
        self.records: list[dict[str, Any]] = []

    def labels(self, **labels):
        record = {"labels": labels, "amount": 0}
        self.records.append(record)
        return _CounterRecorder(record)


class _GaugeSetter:
    def __init__(self, target: dict[str, Any]):
        self.target = target

    def set(self, value: float):
        self.target["value"] = value


class DummyGauge:
    def __init__(self):
        self.records: list[dict[str, Any]] = []

    def labels(self, **labels):
        record = {"labels": labels, "value": None}
        self.records.append(record)
        return _GaugeSetter(record)

    def last_value(self) -> float | None:
        return self.records[-1]["value"] if self.records else None


async def _cancel_task(task: asyncio.Task) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        # Expected when stopping background tasks in tests.
        return


@pytest.mark.asyncio
async def test_fetch_markets_from_polymarket_builds_expected_filters(monkeypatch):
    captured: dict[str, Any] = {}

    class DummyClient:
        async def fetch_events_markets(self, **kwargs):
            captured.update(kwargs)
            return []

    monkeypatch.setattr(runtime_module, "polymarket_client", DummyClient(), raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_page_size", 25, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_order", "updatedAt", raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_sort_ascending", False, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_only_open_markets", True, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_active_filter", True, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_archived_filter", False, raising=False)

    markets = await runtime_module.polymarket_client.fetch_events_markets(
        page_size=runtime_module.settings.polymarket_page_size,
        order=runtime_module.settings.polymarket_order,
        ascending=runtime_module.settings.polymarket_sort_ascending,
        closed=False if runtime_module.settings.polymarket_only_open_markets is True else None,
        extra_params=build_filters_from_settings(runtime_module.settings),
    )

    assert markets == []
    assert captured["page_size"] == 25
    assert captured["order"] == "updatedAt"
    assert captured["ascending"] is False
    assert captured["closed"] is False
    extra = captured["extra_params"]
    assert extra["active"] == "true"
    assert extra["archived"] == "false"


@pytest.mark.asyncio
async def test_fetch_markets_from_polymarket_prefers_events_when_enabled(monkeypatch):
    calls: dict[str, Any] = {"events": 0, "markets": 0}

    class DummyClient:
        async def fetch_events_markets(self, **kwargs):
            calls["events"] += 1
            calls["kwargs"] = kwargs
            return []

        async def fetch_markets(self, **_kwargs):
            calls["markets"] += 1
            return []

    monkeypatch.setattr(runtime_module, "polymarket_client", DummyClient(), raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_sync_max_attempts", 1, raising=False)

    markets = await runtime_module.polymarket_client.fetch_events_markets(
        page_size=runtime_module.settings.polymarket_page_size,
        order=runtime_module.settings.polymarket_order,
        ascending=runtime_module.settings.polymarket_sort_ascending,
        closed=False if runtime_module.settings.polymarket_only_open_markets is True else None,
        extra_params=build_filters_from_settings(runtime_module.settings),
    )

    assert markets == []
    assert calls["events"] == 1
    assert calls["markets"] == 0
    assert calls["kwargs"]["order"] == runtime_module.settings.polymarket_order


@pytest.mark.asyncio
async def test_process_once_persists_markets_and_emits_heartbeat(monkeypatch, caplog):
    engine, session_factory = await create_async_in_memory_db()
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", session_factory, raising=False)
    monkeypatch.setattr(runtime_module.settings, "run_migrations_on_startup", False, raising=False)

    sample_markets = [
        MarketPayload(
            event_id="evt-1",
            title="First",
            slug="first",
            category="sports",
            metadata_uri=None,
            oracle="polymarket",
            status="commit",
            outcomes=["Yes", "No"],
            outcome_prices=[0.4, 0.6],
        ),
        MarketPayload(
            event_id="evt-2",
            title="Second",
            slug="second",
            category="news",
            metadata_uri=None,
            oracle="polymarket",
            status="commit",
            outcomes=["Up", "Down"],
            outcome_prices=[0.55, 0.45],
        ),
    ]

    async def _fake_paginated(self, **_kwargs):
        yield sample_markets

    monkeypatch.setattr(
        runtime_module,
        "polymarket_client",
        type(
            "DummyClient", (), {"fetch_events_paginated": _fake_paginated, "fetch_markets_paginated": _fake_paginated}
        )(),
        raising=False,
    )

    dummy = DummyRedis()
    invalidated_tags: list[str] = []

    async def fake_invalidate(_, tag: str):
        invalidated_tags.append(tag)
        return 1

    monkeypatch.setattr(shared_cache, "invalidate_tag", fake_invalidate, raising=False)
    caplog.set_level(logging.DEBUG, logger="reveal_market.worker")

    category_before = (
        REGISTRY.get_sample_value(
            "worker_cache_invalidations_total",
            labels={"type": "category"},
        )
        or 0
    )
    stats = await worker_service.process_once(dummy)
    assert stats["markets_processed"] == len(sample_markets)
    assert stats["markets_changed"] == len(sample_markets)
    assert stats["resolutions_changed"] == 0
    assert stats["categories_changed"] == 2
    assert stats["cache_invalidations"] >= 0

    async with session_factory() as session:
        stored = (await session.execute(select(Market))).scalars().all()
        assert len(stored) == 2

    assert dummy.last_set is not None
    assert dummy.last_set["key"].startswith("reveal_market_worker")
    assert dummy.last_set["ttl"] > 0
    heartbeat = json.loads(dummy.last_set["value"])
    assert heartbeat["markets_processed"] == len(sample_markets)
    assert heartbeat["markets_created"] == stats["markets_created"]
    assert heartbeat["cache_invalidations"] == stats["cache_invalidations"]
    assert all(not key.startswith("markets:") for key in dummy.store.keys())
    assert {"market:evt-1", "market:evt-2", "markets:stats", "category:trending"}.issubset(set(invalidated_tags))

    events = [record.event for record in caplog.records if hasattr(record, "event")]
    assert "worker.persist.batch" in events
    assert "worker.cache.invalidate" in events
    category_after = (
        REGISTRY.get_sample_value(
            "worker_cache_invalidations_total",
            labels={"type": "category"},
        )
        or 0
    )
    assert category_after == category_before + 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_process_once_publishes_schema_revision(monkeypatch):
    """Ensure schema revisions are broadcast to Redis and tagged caches are invalidated."""

    dummy = DummyRedis()
    schema_state = SchemaSyncResult(
        changed=True,
        previous_revision="0002_resolutions",
        current_revision="0003_schema_versions",
    )

    async def fake_schema():
        return schema_state

    async def fake_sync(_redis_client=None):
        return market_sync.SyncSummary(), 0, 0, 0.0

    monkeypatch.setattr(worker_service, "ensure_schema", fake_schema, raising=False)
    monkeypatch.setattr(worker_service, "_sync_polymarket_feed", fake_sync, raising=False)

    async def _no_proofs(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(worker_service, "run_prover_jobs", _no_proofs, raising=False)

    invalidated: list[str] = []

    async def fake_invalidate(redis_client, tag: str):
        invalidated.append(tag)
        return 0

    monkeypatch.setattr(shared_cache, "invalidate_tag", fake_invalidate, raising=False)

    stats = await worker_service.process_once(dummy)
    assert stats["markets_processed"] == 0
    assert stats["markets_changed"] == 0
    assert stats["resolutions_changed"] == 0
    assert dummy.store.get(runtime_module.settings.schema_version_key) == schema_state.current_revision
    assert "schema:unknown" in invalidated
    assert f"schema:{schema_state.previous_revision}" in invalidated


@pytest.mark.asyncio
async def test_process_once_enqueues_backfill_proof_jobs(monkeypatch):
    dummy = DummyRedis()
    summary = market_sync.SyncSummary()
    schema_state = SchemaSyncResult(
        changed=False,
        previous_revision=None,
        current_revision="0001_revision",
    )

    async def fake_schema():
        return schema_state

    async def fake_sync(_redis_client=None):
        return summary, 0, 0, 0.0

    async def fake_enqueue(*_args, **_kwargs):
        return 0

    class DummyReport:
        total = 0

    async def fake_invalidate(*_args, **_kwargs):
        return DummyReport()

    called = {"value": False}

    async def fake_backfill(_redis_client=None):
        called["value"] = True
        return 0

    monkeypatch.setattr(worker_service, "ensure_schema", fake_schema, raising=False)
    monkeypatch.setattr(worker_service, "_sync_polymarket_feed", fake_sync, raising=False)
    monkeypatch.setattr(worker_service, "enqueue_proof_jobs", fake_enqueue, raising=False)
    monkeypatch.setattr(worker_service, "_enqueue_backfill_proof_jobs", fake_backfill, raising=False)
    monkeypatch.setattr(worker_service, "invalidate_cache_tags", fake_invalidate, raising=False)

    await worker_service.process_once(dummy)

    assert called["value"] is True


@pytest.mark.asyncio
async def test_process_once_handles_polymarket_failures(monkeypatch, caplog):
    dummy = DummyRedis()
    schema_state = SchemaSyncResult(
        changed=False,
        previous_revision=None,
        current_revision="0004_latest_revision",
    )

    published_stats: dict[str, Any] = {}

    async def fake_publish(_redis, stats):
        published_stats.update(stats)

    async def fake_schema():
        return schema_state

    async def fail_sync(_redis_client=None):
        raise RuntimeError("connect refused")

    monkeypatch.setattr(worker_service, "ensure_schema", fake_schema, raising=False)
    monkeypatch.setattr(worker_service, "_sync_polymarket_feed", fail_sync, raising=False)
    monkeypatch.setattr(worker_service, "publish_heartbeat", fake_publish, raising=False)

    caplog.set_level(logging.WARNING, logger="reveal_market.worker")
    stats = await worker_service.process_once(dummy)

    assert stats["markets_processed"] == 0
    assert stats == published_stats
    assert dummy.store.get(runtime_module.settings.schema_version_key) == schema_state.current_revision
    events = [getattr(record, "event", None) for record in caplog.records]
    assert "worker.sync.skipped" in events


@pytest.mark.asyncio
async def test_prime_markets_cache_stores_payload(monkeypatch):
    dummy = DummyRedis()
    payload = [
        {
            "event_id": "evt-123",
            "title": "First",
            "category": "news",
            "oracle": "polymarket",
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/events"
        assert request.url.params["limit"] == "7"
        assert request.url.params["order_by"] == "volume"
        return httpx.Response(status_code=200, json=payload)

    transport = httpx.MockTransport(handler)

    monkeypatch.setattr(runtime_module.settings, "api_base_url", "http://api:8000", raising=False)
    monkeypatch.setattr(runtime_module.settings, "markets_cache_limit", 7, raising=False)
    monkeypatch.setattr(runtime_module.settings, "markets_cache_offset", 0, raising=False)
    monkeypatch.setattr(runtime_module.settings, "markets_cache_order_by", "volume", raising=False)
    monkeypatch.setattr(runtime_module.settings, "markets_cache_prime_pages", 2, raising=False)
    monkeypatch.setattr(runtime_module.settings, "markets_cache_ttl_seconds", 45, raising=False)
    monkeypatch.setattr(runtime_module.settings, "cache_prime_timeout_seconds", 2.0, raising=False)
    monkeypatch.setattr(runtime_module.settings, "prime_markets_cache_enabled", True, raising=False)

    summary = await prime.prime_markets_cache(dummy, transport=transport)
    assert summary["status"] == "primed"
    assert summary["result_count"] == len(payload)
    assert summary["pages"]
    first_page = summary["pages"][0]
    cache_key = markets_list_cache_key(None, None, None, None, 7, 0, order_by="volume")
    assert first_page["cache_key"] == cache_key
    assert cache_key in dummy.store
    assert 30 <= dummy._ttls[cache_key] <= 50
    cached = json.loads(dummy.store[cache_key])
    assert cached == payload


@pytest.mark.asyncio
async def test_record_batch_stats_publishes_metrics(monkeypatch):
    dummy = DummyRedis()
    monkeypatch.setattr(runtime_module.settings, "batch_stats_key", "worker:batch_stats", raising=False)
    monkeypatch.setattr(runtime_module.settings, "batch_stats_ttl_seconds", 300, raising=False)
    stats = {
        "markets_processed": 12,
        "markets_changed": 4,
        "resolutions_changed": 1,
        "categories_changed": 2,
        "latency_ms": 55.2,
    }
    prime_stats = {"status": "primed", "cache_key": "markets:list:*"}

    await worker_service.record_batch_stats(dummy, stats, prime_stats)

    assert dummy.last_set is not None
    assert dummy.last_set["key"] == "worker:batch_stats"
    assert 250 <= dummy.last_set["ttl"] <= 350
    payload = json.loads(dummy.last_set["value"])
    assert payload["markets_processed"] == 12
    assert payload["markets_changed"] == 4
    assert payload["resolutions_changed"] == 1
    assert payload["categories_changed"] == 2
    assert payload["prime"] == prime_stats


@pytest.mark.asyncio
async def test_publish_heartbeat_includes_flags():
    dummy = DummyRedis()
    stats = {
        "markets_processed": 2,
        "markets_changed": 1,
        "resolutions_changed": 1,
        "latency_ms": 12.3,
        "markets_created": 1,
        "markets_updated": 1,
        "markets_deleted": 0,
        "proofs_generated": 0,
        "cache_invalidations": 0,
        "resolution_gaps": 0,
        "market_errors": 0,
        "polymarket_ok": True,
        "redis_available": True,
    }

    await worker_service.publish_heartbeat(dummy, stats)

    assert dummy.last_set is not None
    payload = json.loads(dummy.last_set["value"])
    assert payload["polymarket_ok"] is True
    assert payload["redis_available"] is True
    assert payload["markets_processed"] == 2


def test_cleanup_resolved_markets_removes_expired(monkeypatch):
    engine, session_factory = create_in_memory_db()
    try:
        expired = Market(
            event_id="evt-old",
            title="Old market",
            category="Sports",
            oracle="0xold",
            status="settled",
            resolved_at=datetime.now(UTC) - timedelta(days=2),
        )
        recent = Market(
            event_id="evt-new",
            title="Fresh market",
            category="News",
            oracle="0xnew",
            status="settled",
            resolved_at=datetime.now(UTC),
        )
        with session_factory() as session:
            session.add_all([expired, recent])
            session.commit()

        monkeypatch.setattr(runtime_module.settings, "resolved_retention_seconds", 60 * 60, raising=False)

        with session_factory() as session:
            outcome = market_sync.cleanup_resolved_markets(session, now=datetime.now(UTC))
            session.commit()

        assert outcome.events == {"evt-old"}
        assert "sports" in {slug for slug in outcome.categories if slug}
        assert outcome.deleted_rows == 0
        assert outcome.eligible_rows == 1
        assert outcome.dry_run is True

        with session_factory() as session:
            remaining = session.execute(select(Market.event_id)).scalars().all()
            assert set(remaining) == {"evt-old", "evt-new"}
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_prime_featured_views_prefetches_categories_and_suggestions(monkeypatch):
    dummy = DummyRedis()
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if "/events/suggest" in request.url.path:
            key = suggest_cache_key("Alpha query", runtime_module.settings.suggest_cache_limit)
            dummy._ttls[key] = 30
        return httpx.Response(status_code=200, json=[])

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(runtime_module.settings, "api_base_url", "http://api:8000", raising=False)
    monkeypatch.setattr(runtime_module.settings, "featured_categories", ["Politics"], raising=False)
    monkeypatch.setattr(runtime_module.settings, "featured_suggest_queries", ["Alpha query"], raising=False)
    monkeypatch.setattr(runtime_module.settings, "category_cache_limit", 7, raising=False)
    monkeypatch.setattr(runtime_module.settings, "suggest_cache_limit", 4, raising=False)

    summary = await prime.prime_featured_views(dummy, transport=transport)

    assert summary["categories_primed"] == 1
    assert summary["suggestions_primed"] == 1
    assert summary["suggestion_ttls"]["Alpha query"] == 30
    assert any("/categories/Politics" in url and "limit=7" in url for url in requests)
    assert any("/events/suggest" in url and "limit=4" in url for url in requests)


def _fetch_counter(outcome: str) -> float:
    value = REGISTRY.get_sample_value("worker_polymarket_fetch_total", {"outcome": outcome})
    return value or 0.0


@pytest.mark.asyncio
async def test_fetch_markets_from_polymarket_counts_success(monkeypatch):
    payload = MarketPayload(
        event_id="evt-success",
        title="OK",
        category="sports",
        oracle="polymarket",
        status="commit",
    )

    async def _fake_events_paginated(self, **_kwargs):
        yield [payload]

    async def fake_collect(session, page, redis_client, summary):
        for item in page:
            summary.changed_events.add(item.event_id)
        summary.markets_created += len(page)
        summary.proof_jobs = []
        return summary

    monkeypatch.setattr(worker_service, "session_scope", dummy_session_scope, raising=False)
    monkeypatch.setattr(worker_service, "collect_market_changes_with_summary", fake_collect, raising=False)
    monkeypatch.setattr(worker_service, "apply_retention_cleanup_async", async_none, raising=False)
    monkeypatch.setattr(worker_service, "backfill_missing_resolutions_async", async_zero, raising=False)
    monkeypatch.setattr(worker_service, "log_resolution_gaps_async", async_zero, raising=False)
    monkeypatch.setattr(worker_service, "backfill_market_addresses", async_zero, raising=False)
    monkeypatch.setattr(worker_service, "backfill_market_params", async_zero, raising=False)
    monkeypatch.setattr(worker_service, "_enqueue_backfill_proof_jobs", async_zero, raising=False)
    monkeypatch.setattr(
        runtime_module,
        "polymarket_client",
        type(
            "Dummy",
            (),
            {
                "fetch_events_paginated": _fake_events_paginated,
                "fetch_markets_paginated": _fake_events_paginated,
            },
        )(),
        raising=False,
    )
    monkeypatch.setattr(runtime_module.settings, "polymarket_sync_max_attempts", 1, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_sync_retry_backoff_seconds", 0, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_sync_retry_backoff_max_seconds", 0, raising=False)
    dummy_redis = DummyRedis()
    before = _fetch_counter("success")

    summary, total, gap_count, latency_ms = await worker_service._sync_polymarket_feed(dummy_redis)

    assert total == 1
    assert summary.markets_created == 1
    assert summary.changed_events_total + len(summary.changed_events) == 1
    assert gap_count == 0
    assert latency_ms >= 0
    assert _fetch_counter("success") == before + 1


@pytest.mark.asyncio
async def test_fetch_markets_stops_on_updated_at_cutoff(monkeypatch):
    ts_new = datetime(2026, 1, 3, tzinfo=UTC)
    ts_old = datetime(2026, 1, 1, tzinfo=UTC)
    payload_new = MarketPayload(event_id="evt-new", title="New", source_updated_at=ts_new)
    payload_old = MarketPayload(event_id="evt-old", title="Old", source_updated_at=ts_old)

    async def _fake_events_paginated(self, **_kwargs):
        yield [payload_new]
        yield [payload_old]
        yield [MarketPayload(event_id="evt-too-old", title="Too old", source_updated_at=ts_old)]

    async def fake_collect(session, page, redis_client, summary):
        summary.markets_created += len(page)
        return summary

    monkeypatch.setattr(worker_service, "session_scope", dummy_session_scope, raising=False)
    monkeypatch.setattr(worker_service, "collect_market_changes_with_summary", fake_collect, raising=False)
    monkeypatch.setattr(worker_service, "apply_retention_cleanup_async", async_none, raising=False)
    monkeypatch.setattr(worker_service, "backfill_missing_resolutions_async", async_zero, raising=False)
    monkeypatch.setattr(worker_service, "log_resolution_gaps_async", async_zero, raising=False)
    monkeypatch.setattr(worker_service, "backfill_market_addresses", async_zero, raising=False)
    monkeypatch.setattr(worker_service, "backfill_market_params", async_zero, raising=False)
    monkeypatch.setattr(
        runtime_module,
        "polymarket_client",
        type(
            "Dummy",
            (),
            {
                "fetch_events_paginated": _fake_events_paginated,
                "fetch_markets_paginated": _fake_events_paginated,
            },
        )(),
        raising=False,
    )
    monkeypatch.setattr(runtime_module.settings, "polymarket_order", "updatedAt", raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_sort_ascending", False, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_updated_at_cutoff_enabled", True, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_updated_at_cutoff_grace_seconds", 0, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_sync_max_attempts", 1, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_sync_retry_backoff_seconds", 0, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_sync_retry_backoff_max_seconds", 0, raising=False)
    dummy_redis = DummyRedis()
    dummy_redis.store[runtime_module.settings.polymarket_updated_at_cutoff_key] = str(
        datetime(2026, 1, 2, tzinfo=UTC).timestamp()
    )

    summary, total, _, _ = await worker_service._sync_polymarket_feed(dummy_redis)

    assert total == 2
    assert summary.markets_created == 2
    assert dummy_redis.store[runtime_module.settings.polymarket_updated_at_cutoff_key] == str(ts_new.timestamp())


@pytest.mark.asyncio
async def test_fetch_markets_from_polymarket_counts_errors(monkeypatch):
    async def always_fail(self, **_kwargs):
        # Keep this an async generator while never yielding pages.
        if False:  # pragma: no cover - empty by design
            yield []
        raise RuntimeError("fatal failure")

    async def fake_collect(session, page, redis_client, summary):
        return summary

    monkeypatch.setattr(worker_service, "session_scope", dummy_session_scope, raising=False)
    monkeypatch.setattr(worker_service, "collect_market_changes_with_summary", fake_collect, raising=False)
    monkeypatch.setattr(worker_service, "apply_retention_cleanup_async", async_none, raising=False)
    monkeypatch.setattr(worker_service, "backfill_missing_resolutions_async", async_zero, raising=False)
    monkeypatch.setattr(worker_service, "log_resolution_gaps_async", async_zero, raising=False)
    monkeypatch.setattr(worker_service, "backfill_market_addresses", async_zero, raising=False)
    monkeypatch.setattr(worker_service, "backfill_market_params", async_zero, raising=False)
    monkeypatch.setattr(
        runtime_module,
        "polymarket_client",
        type(
            "Dummy",
            (),
            {
                "fetch_events_paginated": always_fail,
                "fetch_markets_paginated": always_fail,
            },
        )(),
        raising=False,
    )
    monkeypatch.setattr(runtime_module.settings, "polymarket_sync_max_attempts", 1, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_sync_retry_backoff_seconds", 0, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_sync_retry_backoff_max_seconds", 0, raising=False)

    dummy_redis = DummyRedis()
    before = _fetch_counter("error")
    with pytest.raises(RuntimeError):
        await worker_service._sync_polymarket_feed(dummy_redis)
    assert _fetch_counter("error") == before + 1


@pytest.mark.asyncio
async def test_fetch_markets_from_polymarket_retries(monkeypatch):
    payload = MarketPayload(
        event_id="evt-retry",
        title="Retry",
        category="sports",
        oracle="polymarket",
        status="commit",
    )

    attempts = {"count": 0}

    async def flaky_fetch(self, **_kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary failure")
        yield [payload]

    async def fake_collect(session, page, redis_client, summary):
        for item in page:
            summary.changed_events.add(item.event_id)
        summary.markets_created += len(page)
        summary.proof_jobs = []
        return summary

    monkeypatch.setattr(worker_service, "session_scope", dummy_session_scope, raising=False)
    monkeypatch.setattr(worker_service, "collect_market_changes_with_summary", fake_collect, raising=False)
    monkeypatch.setattr(worker_service, "apply_retention_cleanup_async", async_none, raising=False)
    monkeypatch.setattr(worker_service, "backfill_missing_resolutions_async", async_zero, raising=False)
    monkeypatch.setattr(worker_service, "log_resolution_gaps_async", async_zero, raising=False)
    monkeypatch.setattr(worker_service, "backfill_market_addresses", async_zero, raising=False)
    monkeypatch.setattr(worker_service, "backfill_market_params", async_zero, raising=False)
    monkeypatch.setattr(
        runtime_module,
        "polymarket_client",
        type(
            "Dummy",
            (),
            {
                "fetch_events_paginated": flaky_fetch,
                "fetch_markets_paginated": flaky_fetch,
            },
        )(),
        raising=False,
    )
    monkeypatch.setattr(runtime_module.settings, "polymarket_sync_max_attempts", 2, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_sync_retry_backoff_seconds", 0, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_sync_retry_backoff_max_seconds", 0, raising=False)

    dummy_redis = DummyRedis()
    before_success = _fetch_counter("success")
    summary, total, gap_count, _ = await worker_service._sync_polymarket_feed(dummy_redis)

    assert attempts["count"] == 2
    assert total == 1
    assert summary.markets_created == 1
    assert summary.changed_events_total + len(summary.changed_events) == 1
    assert gap_count == 0
    assert _fetch_counter("success") == before_success + 1


@pytest.mark.asyncio
async def test_publish_heartbeat_retries_on_failure(monkeypatch):
    class FlakyRedis:
        def __init__(self):
            self.calls = 0
            self.payloads: list[str] = []

        async def set(self, key, value, ex=None):
            self.calls += 1
            if self.calls < 2:
                raise RuntimeError("redis unavailable")
            self.payloads.append(value)
            return True

    redis_client = FlakyRedis()
    monkeypatch.setattr(runtime_module.settings, "heartbeat_max_retries", 3, raising=False)
    monkeypatch.setattr(runtime_module.settings, "heartbeat_retry_backoff_seconds", 0, raising=False)
    monkeypatch.setattr(runtime_module.settings, "heartbeat_retry_backoff_max_seconds", 0, raising=False)
    monkeypatch.setattr(asyncio, "sleep", lambda *_args, **_kwargs: None, raising=False)

    await worker_service.publish_heartbeat(redis_client, {"markets_processed": 5})
    assert redis_client.calls == 2
    assert json.loads(redis_client.payloads[-1])["markets_processed"] == 5


@pytest.mark.asyncio
async def test_publish_heartbeat_logs_after_exhausting_retries(monkeypatch, caplog):
    class BrokenRedis:
        def __init__(self):
            self.calls = 0

        async def set(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("still down")

    redis_client = BrokenRedis()
    monkeypatch.setattr(runtime_module.settings, "heartbeat_max_retries", 2, raising=False)
    monkeypatch.setattr(runtime_module.settings, "heartbeat_retry_backoff_seconds", 0, raising=False)
    monkeypatch.setattr(runtime_module.settings, "heartbeat_retry_backoff_max_seconds", 0, raising=False)
    monkeypatch.setattr(asyncio, "sleep", lambda *_args, **_kwargs: None, raising=False)

    with caplog.at_level(logging.WARNING):
        await worker_service.publish_heartbeat(redis_client, {"markets_processed": 1})

    assert redis_client.calls == 2
    assert any("failed to publish worker heartbeat" in record.message for record in caplog.records)


def test_cleanup_resolved_markets_respects_dry_run(monkeypatch):
    engine, session_factory = create_in_memory_db()
    try:
        market = Market(
            event_id="evt-dry",
            title="Dry run",
            category="Crypto",
            oracle="0xdry",
            status="settled",
            resolved_at=datetime.now(UTC) - timedelta(days=2),
        )
        with session_factory() as session:
            session.add(market)
            session.commit()

        with session_factory() as session:
            outcome = market_sync.cleanup_resolved_markets(
                session,
                dry_run=True,
                now=datetime.now(UTC),
            )
            session.commit()

        assert outcome.deleted_rows == 0
        assert outcome.eligible_rows == 1
        assert outcome.dry_run is True
        with session_factory() as session:
            remaining = session.execute(select(Market.event_id)).scalars().all()
            assert remaining == ["evt-dry"]
    finally:
        engine.dispose()


def test_cleanup_resolved_markets_handles_timezone_offsets(monkeypatch):
    engine, session_factory = create_in_memory_db()
    try:
        offset_zone = timezone(timedelta(hours=-5))
        market = Market(
            event_id="evt-tz",
            title="Offset market",
            category="Politics",
            oracle="0xtz",
            status="settled",
            resolved_at=datetime(2024, 3, 10, 1, 30, tzinfo=offset_zone),
        )
        with session_factory() as session:
            session.add(market)
            session.commit()

        monkeypatch.setattr(runtime_module.settings, "resolved_retention_seconds", 60 * 60, raising=False)
        reference = datetime(2024, 3, 10, 7, 0, tzinfo=UTC)
        with session_factory() as session:
            outcome = market_sync.cleanup_resolved_markets(session, now=reference)
            session.commit()

        assert outcome.deleted_rows == 0
        assert outcome.eligible_rows == 1
        assert outcome.dry_run is True
        with session_factory() as session:
            remaining = session.execute(select(Market.event_id)).scalars().all()
            assert remaining == ["evt-tz"]
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_maybe_generate_settlement_proof(monkeypatch):
    class FakeProver:
        def __init__(self):
            self.called_with = None

        async def generate_settlement_proof(self, request):
            self.called_with = request
            return SettlementProofResponse(
                proof="0xdead",
                public_signals=["1"],
                circuit_hash="0xabc",
                generated_at=datetime.now(UTC),
                prover_version="test",
                request_id="req-1",
            )

    fake_prover = FakeProver()
    monkeypatch.setattr(runtime_module, "PROVER_CLIENT", fake_prover, raising=False)

    engine, session_factory = await create_async_in_memory_db()
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", session_factory, raising=False)

    leaf_hex = "0x" + "02" * 32
    root_bytes, _ = build_merkle_root_and_paths([bytes.fromhex(leaf_hex[2:])])

    async with session_factory() as session:
        market_row = Market(id=1, event_id="evt-proof", title="Proof Market", oracle="polymarket")
        session.add(market_row)
        await session.flush()
        session.add(
            shared_models.Commitment(
                id=1,
                market_id=market_row.id,
                user_address="0x1",
                outcome_id=0,
                amount_wei=1,
                payout_wei=1,
                salt="0x1",
                ticket_hash=leaf_hex,
                leaf=leaf_hex,
                leaf_index=0,
            )
        )
        session.add(
            Settlement(
                id=1,
                market_id=market_row.id,
                merkle_root="0x" + root_bytes.hex(),
                commitments_count=1,
                pool_total_yes=1,
                pool_total_no=0,
                total_escrow=1,
                total_liability=1,
                rake_bps=0,
                winning_outcome_id=0,
                circuit_hash="0xabc",
            )
        )
        await session.commit()

    redis_client = DummyRedis()
    market_payload = MarketPayload(
        event_id="evt-proof",
        title="Proof Market",
        outcomes=["Yes", "No"],
        outcome_prices=[0.6, 0.4],
    )
    market_snapshot = {
        "market_id": 1,
        "event_id": "evt-proof",
        "market_address": "0xabc",
        "condition_id": "0xabc",
        "commitments_root": "0x" + root_bytes.hex(),
        "tickets": [
            {
                "user": "0x1",
                "outcomeId": "0",
                "amount": "1",
                "payout": "1",
                "salt": "0x1",
                "ticketHash": leaf_hex,
                "leaf": leaf_hex,
                "merklePath": [],
                "merkleIndex": 0,
            }
        ],
        "pool_totals": ["1", "0"],
        "total_escrow": "1",
        "total_liability": "1",
        "rake_bps": 0,
        "winning_outcome_id": 0,
        "circuit_hash": "0xabc",
    }
    try:
        assert await proofs.maybe_generate_settlement_proof(
            redis_client,
            market_snapshot=market_snapshot,
            market_payload=market_payload,
            condition_id="0xabc",
        )
        assert fake_prover.called_with is not None
        assert redis_client.last_set is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_maybe_generate_settlement_proof_rejects_circuit_hash_mismatch(monkeypatch):
    class FakeProver:
        def __init__(self):
            self.called_with = None
            self.health_calls = 0

        async def fetch_health(self):
            self.health_calls += 1
            return {"circuit_hash": "0xdef"}

        async def generate_settlement_proof(self, request):
            self.called_with = request
            return SettlementProofResponse(
                proof="0xdead",
                public_signals=["1"],
                circuit_hash="0xdef",
                generated_at=datetime.now(UTC),
                prover_version="test",
                request_id="req-1",
            )

    fake_prover = FakeProver()
    monkeypatch.setattr(runtime_module, "PROVER_CLIENT", fake_prover, raising=False)
    proofs._PROVER_CIRCUIT_CACHE["value"] = None
    proofs._PROVER_CIRCUIT_CACHE["expires_at"] = 0.0

    engine, session_factory = await create_async_in_memory_db()
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", session_factory, raising=False)

    leaf_hex = "0x" + "02" * 32
    root_bytes, _ = build_merkle_root_and_paths([bytes.fromhex(leaf_hex[2:])])

    async with session_factory() as session:
        market_row = Market(id=2, event_id="evt-proof-mismatch", title="Proof Market", oracle="polymarket")
        session.add(market_row)
        await session.flush()
        session.add(
            shared_models.Commitment(
                id=2,
                market_id=market_row.id,
                user_address="0x1",
                outcome_id=0,
                amount_wei=1,
                payout_wei=1,
                salt="0x1",
                ticket_hash=leaf_hex,
                leaf=leaf_hex,
                leaf_index=0,
            )
        )
        session.add(
            Settlement(
                id=2,
                market_id=market_row.id,
                merkle_root="0x" + root_bytes.hex(),
                commitments_count=1,
                pool_total_yes=1,
                pool_total_no=0,
                total_escrow=1,
                total_liability=1,
                rake_bps=0,
                winning_outcome_id=0,
                circuit_hash="0xabc",
            )
        )
        await session.commit()

    redis_client = DummyRedis()
    market_payload = MarketPayload(
        event_id="evt-proof-mismatch",
        title="Proof Market",
        outcomes=["Yes", "No"],
        outcome_prices=[0.6, 0.4],
    )
    market_snapshot = {
        "market_id": 2,
        "event_id": "evt-proof-mismatch",
        "market_address": "0xabc",
        "condition_id": "0xabc",
        "commitments_root": "0x" + root_bytes.hex(),
        "tickets": [
            {
                "user": "0x1",
                "outcomeId": "0",
                "amount": "1",
                "payout": "1",
                "salt": "0x1",
                "ticketHash": leaf_hex,
                "leaf": leaf_hex,
                "merklePath": [],
                "merkleIndex": 0,
            }
        ],
        "pool_totals": ["1", "0"],
        "total_escrow": "1",
        "total_liability": "1",
        "rake_bps": 0,
        "winning_outcome_id": 0,
        "circuit_hash": "0xabc",
    }
    try:
        assert (
            await proofs.maybe_generate_settlement_proof(
                redis_client,
                market_snapshot=market_snapshot,
                market_payload=market_payload,
                condition_id="0xabc",
            )
            is False
        )
        assert fake_prover.called_with is None
        async with session_factory() as session:
            settlement = (
                await session.execute(select(shared_models.Settlement).where(shared_models.Settlement.id == 2))
            ).scalar_one()
            assert settlement.proof_status == shared_models.SettlementProofStatus.FAILED.value
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_enqueue_proof_jobs_dedupes(monkeypatch):
    redis_client = DummyRedis()
    monkeypatch.setattr(proofs, "PROOF_QUEUE_DEPTH_GAUGE", DummyGauge())
    summary = market_sync.SyncSummary()
    market_payload = MarketPayload(
        event_id="evt-proof",
        title="Proofable",
        slug="proofable",
        category="news",
        metadata_uri=None,
        oracle="polymarket",
        status="commit",
        outcomes=["Yes", "No"],
        outcome_prices=[0.5, 0.5],
    )
    summary.proof_jobs.append(({"id": 1, "event_id": "evt-proof"}, market_payload, "0xabc"))
    first = await proofs.enqueue_proof_jobs(redis_client, summary)
    second = await proofs.enqueue_proof_jobs(redis_client, summary)
    assert first == 1
    assert second == 0
    assert await redis_client.llen(runtime_module.settings.proof_queue_key) == 1


@pytest.mark.asyncio
async def test_enqueue_settlement_job_uses_atomic_eval(monkeypatch):
    redis_client = DummyRedis()
    monkeypatch.setattr(proofs, "SETTLEMENT_QUEUE_DEPTH_GAUGE", DummyGauge())
    monkeypatch.setattr(runtime_module.settings, "settlement_queue_dedupe_ttl_seconds", 120, raising=False)

    first = await proofs.enqueue_settlement_job(redis_client, market_id="evt-settle")
    second = await proofs.enqueue_settlement_job(redis_client, market_id="evt-settle")

    assert first == 1
    assert second == 0
    queue_key = runtime_module.settings.settlement_queue_key
    dedupe_key = runtime_module.settings.settlement_queue_dedupe_key
    assert await redis_client.llen(queue_key) == 1
    assert "settle:evt-settle" in await redis_client.smembers(dedupe_key)
    assert await redis_client.ttl(dedupe_key) == 120


@pytest.mark.asyncio
async def test_acquire_sync_lease_respects_existing(monkeypatch):
    redis_client = DummyRedis()
    # Simulate existing lease so NX fails
    await redis_client.set(runtime_module.settings.polymarket_sync_lease_key, "holder")
    acquired = await worker_service._acquire_sync_lease(redis_client)
    assert acquired is None


@pytest.mark.asyncio
async def test_acquire_lock_batches_lease_respects_existing(monkeypatch):
    redis_client = DummyRedis()
    monkeypatch.setattr(runtime_module.settings, "lock_batches_lease_key", "worker:lock-batches:lease", raising=False)
    await redis_client.set(runtime_module.settings.lock_batches_lease_key, "holder")
    acquired = await worker_service._acquire_lock_batches_lease(redis_client)
    assert acquired is None


@pytest.mark.asyncio
async def test_sync_polymarket_feed_skips_when_lease_held(monkeypatch):
    redis_client = DummyRedis()
    await redis_client.set(runtime_module.settings.polymarket_sync_lease_key, "holder")

    # Ensure fetch loop would fail if executed to catch accidental runs
    class DummyClient:
        async def fetch_events_paginated(self, **kwargs):
            raise AssertionError("fetch should be skipped due to lease")

    monkeypatch.setattr(runtime_module, "polymarket_client", DummyClient(), raising=False)

    summary, total, gaps, latency = await worker_service._sync_polymarket_feed(redis_client)
    assert total == 0
    assert gaps == 0
    assert summary.markets_created == 0


@pytest.mark.asyncio
async def test_process_once_enqueues_and_worker_processes_proofs(monkeypatch, caplog):
    # Set up runtime settings
    monkeypatch.setattr(runtime_module.settings, "run_migrations_on_startup", False, raising=False)
    monkeypatch.setattr(runtime_module, "PROVER_CLIENT", object(), raising=False)
    monkeypatch.setattr(runtime_module.settings, "proof_queue_poll_seconds", 0.01, raising=False)
    monkeypatch.setattr(runtime_module.settings, "settlement_queue_poll_seconds", 0.01, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_sync_lease_failure_cooldown_seconds", 0, raising=False)
    monkeypatch.setattr(worker_service, "_LAST_SYNC_LEASE_FAILURE_TS", None, raising=False)

    # In-memory DB
    engine, session_factory = await create_async_in_memory_db()
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", session_factory, raising=False)

    # Seed a resolved market + settlement so proof jobs are enqueued.
    async with session_factory() as session:
        market_row = Market(
            event_id="evt-proof-queue",
            title="Existing proof market",
            slug="proof-queue-market",
            category="news",
            oracle="polymarket",
            status="settled",
            resolution_status="final",
            resolved_at=datetime.now(UTC),
        )
        session.add(market_row)
        await session.flush()
        session.add(Settlement(id=1, market_id=market_row.id, proof_status="none", submission_status="none"))
        await session.commit()

    # Fake market payload from Gamma
    sample_markets = [
        MarketPayload(
            event_id="evt-proof-queue",
            title="Proof Queue Market",
            slug="proof-queue-market",
            category="news",
            metadata_uri=None,
            oracle="polymarket",
            status="commit",
            outcomes=["Yes", "No"],
            outcome_prices=[0.55, 0.45],
        )
    ]

    async def _fake_paginated(self, **_kwargs):
        yield sample_markets

    monkeypatch.setattr(
        runtime_module,
        "polymarket_client",
        type(
            "DummyClient", (), {"fetch_events_paginated": _fake_paginated, "fetch_markets_paginated": _fake_paginated}
        )(),
        raising=False,
    )

    # Redis + gauges
    redis_client = DummyRedis()
    gauge = DummyGauge()
    monkeypatch.setattr(proofs, "PROOF_QUEUE_DEPTH_GAUGE", gauge)

    called = {"maybe_generate": 0, "settlements": 0}

    async def fake_generate(redis_client=None, market_snapshot=None, market_payload=None, condition_id=None):
        called["maybe_generate"] += 1
        return True

    async def fake_settlements(summary, redis_client=None, market_id=None):
        called["settlements"] += 1
        return 0

    monkeypatch.setattr(proofs, "maybe_generate_settlement_proof", fake_generate)
    monkeypatch.setattr(proofs, "run_settlement_jobs", fake_settlements)

    # Run a single tick which should enqueue, then let the background workers drain
    proof_worker_task = asyncio.create_task(worker_service.run_proof_queue_worker(redis_client))
    settlement_worker_task = asyncio.create_task(worker_service.run_settlement_queue_worker(redis_client))
    stats = await worker_service.process_once(redis_client)
    await asyncio.sleep(0.05)
    async with session_factory() as session:
        market_row = (await session.execute(select(Market).where(Market.event_id == "evt-proof-queue"))).scalar_one()
        snapshot = {
            "id": market_row.id,
            "event_id": market_row.event_id,
            "market_address": market_row.market_address,
            "condition_id": market_row.condition_id,
        }
    manual_summary = market_sync.SyncSummary()
    manual_summary.proof_jobs.append((snapshot, sample_markets[0], None))
    await proofs.enqueue_proof_jobs(redis_client, manual_summary)
    await asyncio.sleep(0.1)
    await _cancel_task(proof_worker_task)
    await _cancel_task(settlement_worker_task)

    assert stats["markets_processed"] == 1
    assert await redis_client.llen(runtime_module.settings.proof_queue_key) == 0
    assert called["maybe_generate"] >= 1
    assert called["settlements"] >= 1
    assert settlement_worker_task.done()


@pytest.mark.asyncio
async def test_settlement_queue_skips_without_signer(monkeypatch):
    redis_client = DummyRedis()
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_enabled", True, raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_base_url", "http://relayer:8088", raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_key", "relayer:queue", raising=False)

    engine, session_factory = await create_async_in_memory_db()
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", session_factory, raising=False)

    async with session_factory() as session:
        market = Market(
            event_id="evt-relayer",
            title="Relayer Market",
            category="sports",
            oracle="polymarket",
            status="settled",
            resolution_status="final",
            market_address="0x0000000000000000000000000000000000000001",
            resolved_at=datetime.now(UTC),
        )
        session.add(market)
        await session.flush()
        settlement = Settlement(
            id=1,
            market_id=market.id,
            proof_status="generated",
            submission_status="none",
            merkle_root="0x1234",
            winning_outcome_id=1,
            commitments_count=2,
        )
        session.add(settlement)
        commit_row = shared_models.Commitment(
            market_id=market.id,
            user_address="0xabc",
            outcome_id=1,
            amount_wei=10,
            payout_wei=10,
            salt="0x01",
            ticket_hash="0xticket",
            leaf="0x10",
            leaf_index=0,
        )
        session.add(commit_row)
        await session.flush()
        session.add(
            shared_models.CommitmentMerklePath(
                commitment_id=commit_row.id,
                level=0,
                sibling_hash="0x20",
            )
        )
        await session.commit()

    temp_summary = market_sync.SyncSummary()
    submitted = await worker_service.run_settlement_jobs(temp_summary, redis_client)

    queue_items = redis_client.store.get(runtime_module.settings.relayer_queue_key)
    assert not queue_items, "relayer queue should remain empty without settlement signer"
    assert submitted == 0

    async with session_factory() as session:
        db_settlement = (
            await session.execute(
                select(shared_models.Settlement).where(shared_models.Settlement.market_id == market.id)
            )
        ).scalar_one()
        assert db_settlement.submission_status == shared_models.SettlementSubmissionStatus.NONE.value


@pytest.mark.asyncio
async def test_settlement_queue_skips_without_rpc(monkeypatch):
    redis_client = DummyRedis()
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_enabled", True, raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_base_url", "http://relayer:8088", raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_key", "relayer:queue", raising=False)
    monkeypatch.setattr(
        runtime_module.settings,
        "settlement_signer_private_key",
        SecretStr("0x" + "1" * 64),
        raising=False,
    )
    monkeypatch.setattr(runtime_module.settings, "rpc_url", None, raising=False)
    monkeypatch.setattr(runtime_module.settings, "settlement_rpc_url", None, raising=False)

    engine, session_factory = await create_async_in_memory_db()
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", session_factory, raising=False)

    async with session_factory() as session:
        market = Market(
            event_id="evt-relayer-missing",
            title="Relayer Missing",
            category="sports",
            oracle="polymarket",
            status="settled",
            resolution_status="final",
            market_address="0x0000000000000000000000000000000000000002",
            resolved_at=datetime.now(UTC),
        )
        session.add(market)
        await session.flush()
        settlement = Settlement(
            id=2,
            market_id=market.id,
            proof_status="generated",
            submission_status="none",
            merkle_root="0x1234",
            winning_outcome_id=1,
            commitments_count=2,
        )
        session.add(settlement)
        commit_row = shared_models.Commitment(
            market_id=market.id,
            user_address="0xdef",
            outcome_id=1,
            amount_wei=10,
            payout_wei=10,
            salt="0x01",
            ticket_hash="0xticket-missing",
            leaf="0x10",
            leaf_index=None,
        )
        session.add(commit_row)
        await session.commit()

    temp_summary = market_sync.SyncSummary()
    submitted = await worker_service.run_settlement_jobs(temp_summary, redis_client)

    queue_items = redis_client.store.get(runtime_module.settings.relayer_queue_key)
    assert not queue_items, "relayer queue should remain empty without RPC"
    assert submitted == 0


@pytest.mark.asyncio
async def test_proof_queue_worker_processes_jobs(monkeypatch):
    redis_client = DummyRedis()
    gauge = DummyGauge()
    monkeypatch.setattr(proofs, "PROOF_QUEUE_DEPTH_GAUGE", gauge)
    settlement_gauge = DummyGauge()
    monkeypatch.setattr(proofs, "SETTLEMENT_QUEUE_DEPTH_GAUGE", settlement_gauge)
    monkeypatch.setattr(proofs, "PROOF_QUEUE_OVERFLOW_COUNTER", DummyCounter())

    # Fake maybe_generate_settlement_proof to just mark a call
    called = {"count": 0}

    async def fake_generate(redis_client=None, market_snapshot=None, market_payload=None, condition_id=None):
        called["count"] += 1
        return True

    monkeypatch.setattr(proofs, "maybe_generate_settlement_proof", fake_generate)

    # Avoid on-chain settlement calls in this path
    async def fake_settlements(summary, redis_client=None, market_id=None):
        return 0

    monkeypatch.setattr(proofs, "run_settlement_jobs", fake_settlements)

    queue_key = runtime_module.settings.proof_queue_key
    job = {
        "job_id": "job-1",
        "market_snapshot": {"id": 1, "event_id": "evt-proof"},
        "market_payload": MarketPayload(
            event_id="evt-proof",
            title="Proofable",
            slug="proofable",
            category="news",
            metadata_uri=None,
            oracle="polymarket",
            status="commit",
            outcomes=["Yes", "No"],
            outcome_prices=[0.5, 0.5],
        ).model_dump(),
        "condition_id": "0xabc",
    }
    await redis_client.rpush(queue_key, json.dumps(job))
    worker_task = asyncio.create_task(proofs.run_proof_queue_worker(redis_client))
    # Give the worker a moment to process
    await asyncio.sleep(0.1)
    await _cancel_task(worker_task)

    assert called["count"] == 1
    assert await redis_client.llen(queue_key) == 0
    assert gauge.last_value() == 0


@pytest.mark.asyncio
async def test_proof_queue_worker_enqueues_settlement_when_proof_exists(monkeypatch):
    redis_client = DummyRedis()
    gauge = DummyGauge()
    monkeypatch.setattr(proofs, "PROOF_QUEUE_DEPTH_GAUGE", gauge)

    called = {"settlement": 0}

    async def fake_generate(redis_client=None, market_snapshot=None, market_payload=None, condition_id=None):
        return False

    async def fake_pending(event_id):
        return True

    async def fake_enqueue(redis_client=None, market_id=None):
        called["settlement"] += 1
        return 1

    monkeypatch.setattr(proofs, "maybe_generate_settlement_proof", fake_generate)
    monkeypatch.setattr(proofs, "_has_pending_settlement_for_event", fake_pending)
    monkeypatch.setattr(proofs, "enqueue_settlement_job", fake_enqueue)

    queue_key = runtime_module.settings.proof_queue_key
    job = {
        "job_id": "job-existing-proof",
        "market_snapshot": {"id": 2, "event_id": "evt-existing-proof"},
        "market_payload": MarketPayload(
            event_id="evt-existing-proof",
            title="Existing Proof",
            slug="existing-proof",
            category="news",
            metadata_uri=None,
            oracle="polymarket",
            status="commit",
            outcomes=["Yes", "No"],
            outcome_prices=[0.5, 0.5],
        ).model_dump(),
        "condition_id": "0xdef",
    }
    await redis_client.rpush(queue_key, json.dumps(job))
    worker_task = asyncio.create_task(proofs.run_proof_queue_worker(redis_client))
    await asyncio.sleep(0.1)
    await _cancel_task(worker_task)

    assert called["settlement"] == 1
    assert await redis_client.llen(queue_key) == 0
    assert gauge.last_value() == 0


@pytest.mark.asyncio
async def test_proof_queue_worker_drops_invalid_payload(monkeypatch):
    redis_client = DummyRedis()
    gauge = DummyGauge()
    monkeypatch.setattr(proofs, "PROOF_QUEUE_DEPTH_GAUGE", gauge)
    monkeypatch.setattr(proofs, "PROOF_QUEUE_DLQ_COUNTER", DummyCounter())

    # Invalid payload (missing required fields)
    queue_key = runtime_module.settings.proof_queue_key
    job = {"job_id": "job-bad", "market_payload": {"event_id": None}}
    await redis_client.rpush(queue_key, json.dumps(job))
    worker_task = asyncio.create_task(proofs.run_proof_queue_worker(redis_client))
    await asyncio.sleep(0.05)
    await _cancel_task(worker_task)

    assert await redis_client.llen(queue_key) == 0
    assert gauge.last_value() == 0
    assert redis_client.store.get(runtime_module.settings.proof_queue_dead_letter_key)  # DLQ entry exists
