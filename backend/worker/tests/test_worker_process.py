from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import app.database as db
import app.fetcher as fetcher
import app.market_sync as market_sync
import app.prime as prime
import app.proofs as proofs
import app.runtime as runtime_module
import app.service as worker_service
import httpx
import pytest
from app.market_sync import SyncSummary
from app.polymarket import MarketPayload, PolymarketClient
from app.prover_client import SettlementProofResponse
from app.schema import SchemaSyncResult
from prometheus_client import REGISTRY
from shared import cache_async as shared_cache
from shared.cache_keys import markets_list_cache_key, suggest_cache_key
from shared.models import Base, Market
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.asyncio


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


class DummyRedis:
    def __init__(self):
        self.store: dict[str, Any] = {}
        self.last_set: dict[str, Any] | None = None
        self._ttls: dict[str, int | None] = {}

    async def set(self, key: str, value: Any, ex: int | None = None):
        self.store[key] = value
        self.last_set = {"key": key, "value": value, "ttl": ex}
        self._ttls[key] = ex

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
        self.store.setdefault(key, set()).add(value)

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

    async def brpop(self, keys, timeout: int | None = None):
        key = keys[0] if keys else None
        if key is None:
            return None
        queue = self.store.get(key, [])
        if not queue:
            return None
        value = queue.pop()
        return key, value

    async def llen(self, key: str) -> int:
        queue = self.store.get(key, [])
        return len(queue) if isinstance(queue, list) else 0


class DummyCounter:
    def __init__(self):
        self.records: list[dict[str, Any]] = []

    def labels(self, **labels):
        record = {"labels": labels, "amount": 0}
        self.records.append(record)

        class _Recorder:
            def __init__(self, target):
                self.target = target

            def inc(self, amount: float = 1.0):
                self.target["amount"] += amount

        return _Recorder(record)


async def test_fetch_markets_from_polymarket_builds_expected_filters(monkeypatch):
    captured: dict[str, Any] = {}

    class DummyClient:
        async def fetch_events_markets(self, **kwargs):
            captured.update(kwargs)
            return []

    monkeypatch.setattr(runtime_module, "polymarket_client", DummyClient(), raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_page_size", 25, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_max_pages", 4, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_order", "updatedAt", raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_sort_ascending", False, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_closed_filter", False, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_active_filter", True, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_archived_filter", False, raising=False)

    markets, latency = await fetcher.fetch_markets_from_polymarket()

    assert markets == []
    assert latency >= 0
    assert captured["page_size"] == 25
    assert captured["max_pages"] == 4
    assert captured["order"] == "updatedAt"
    assert captured["ascending"] is False
    assert captured["closed"] is False
    extra = captured["extra_params"]
    assert extra["active"] == "true"
    assert extra["archived"] == "false"


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

    markets, _ = await fetcher.fetch_markets_from_polymarket()

    assert markets == []
    assert calls["events"] == 1
    assert calls["markets"] == 0
    assert calls["kwargs"]["order"] == runtime_module.settings.polymarket_order


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
            gamma_raw={"id": "evt-1"},
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
            gamma_raw={"id": "evt-2"},
        ),
    ]

    async def _fake_paginated(**_kwargs):
        yield sample_markets

    monkeypatch.setattr(
        runtime_module,
        "polymarket_client",
        type("DummyClient", (), {"fetch_markets_paginated": _fake_paginated})(),
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
    assert stats["summaries_enqueued"] == 0
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
        return SyncSummary(), 0, 0, 0.0

    monkeypatch.setattr(worker_service, "ensure_schema", fake_schema, raising=False)
    monkeypatch.setattr(worker_service, "_sync_polymarket_feed", fake_sync, raising=False)
    monkeypatch.setattr(worker_service, "run_prover_jobs", lambda *_args, **_kwargs: 0, raising=False)

    invalidated: list[str] = []

    def fake_invalidate(redis_client, tag: str):
        invalidated.append(tag)
        return 0

    monkeypatch.setattr(shared_cache, "invalidate_tag", fake_invalidate, raising=False)

    stats = await worker_service.process_once(dummy)
    assert stats["markets_processed"] == 0
    assert stats["markets_changed"] == 0
    assert stats["resolutions_changed"] == 0
    assert stats["markets_changed"] == 0
    assert stats["summaries_enqueued"] == 0
    assert stats["resolutions_changed"] == 0
    assert dummy.store.get(runtime_module.settings.schema_version_key) == schema_state.current_revision
    assert "schema:unknown" in invalidated
    assert f"schema:{schema_state.previous_revision}" in invalidated


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
        assert request.url.path == "/markets"
        assert request.url.params["limit"] == "7"
        assert request.url.params["order_by"] == "volume_24h_usd"
        return httpx.Response(status_code=200, json=payload)

    transport = httpx.MockTransport(handler)

    monkeypatch.setattr(runtime_module.settings, "api_base_url", "http://api:8000", raising=False)
    monkeypatch.setattr(runtime_module.settings, "markets_cache_limit", 7, raising=False)
    monkeypatch.setattr(runtime_module.settings, "markets_cache_offset", 0, raising=False)
    monkeypatch.setattr(runtime_module.settings, "markets_cache_order_by", "volume_24h_usd", raising=False)
    monkeypatch.setattr(runtime_module.settings, "markets_cache_prime_pages", 2, raising=False)
    monkeypatch.setattr(runtime_module.settings, "markets_cache_ttl_seconds", 45, raising=False)
    monkeypatch.setattr(runtime_module.settings, "cache_prime_timeout_seconds", 2.0, raising=False)
    monkeypatch.setattr(runtime_module.settings, "prime_markets_cache_enabled", True, raising=False)

    summary = await prime.prime_markets_cache(dummy, transport=transport)
    assert summary["status"] == "primed"
    assert summary["result_count"] == len(payload)
    assert summary["pages"]
    first_page = summary["pages"][0]
    cache_key = markets_list_cache_key(None, None, None, None, 7, 0, order_by="volume_24h_usd")
    assert first_page["cache_key"] == cache_key
    assert cache_key in dummy.store
    assert dummy._ttls[cache_key] == 45
    cached = json.loads(dummy.store[cache_key])
    assert cached == payload


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
    assert dummy.last_set["ttl"] == 300
    payload = json.loads(dummy.last_set["value"])
    assert payload["markets_processed"] == 12
    assert payload["markets_changed"] == 4
    assert payload["resolutions_changed"] == 1
    assert payload["categories_changed"] == 2
    assert payload["prime"] == prime_stats


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
        "summaries_enqueued": 0,
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


async def test_prime_featured_views_prefetches_categories_and_suggestions(monkeypatch):
    dummy = DummyRedis()
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if "/markets/suggest" in request.url.path:
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
    assert any("/markets/suggest" in url and "limit=4" in url for url in requests)


def _fetch_counter(outcome: str) -> float:
    value = REGISTRY.get_sample_value("worker_polymarket_fetch_total", {"outcome": outcome})
    return value or 0.0


async def test_fetch_markets_from_polymarket_counts_success(monkeypatch):
    payload = MarketPayload(
        event_id="evt-success",
        title="OK",
        category="sports",
        oracle="polymarket",
        status="commit",
        gamma_raw={"id": "evt-success"},
    )

    async def _fake_events_markets(**_kwargs):
        return [payload]

    monkeypatch.setattr(runtime_module.settings, "polymarket_sync_max_attempts", 1, raising=False)
    monkeypatch.setattr(
        runtime_module, "polymarket_client", type("Dummy", (), {"fetch_events_markets": _fake_events_markets})()
    )
    before = _fetch_counter("success")

    markets, _ = await fetcher.fetch_markets_from_polymarket()

    assert markets[0].event_id == "evt-success"
    assert _fetch_counter("success") == before + 1


async def test_fetch_markets_from_polymarket_counts_errors(monkeypatch):
    def always_fail(**kwargs):
        raise RuntimeError("fatal failure")

    monkeypatch.setattr(runtime_module.settings, "polymarket_sync_max_attempts", 1, raising=False)
    monkeypatch.setattr(runtime_module, "polymarket_client", type("Dummy", (), {"fetch_events_markets": always_fail})())
    before = _fetch_counter("error")
    with pytest.raises(RuntimeError):
        await fetcher.fetch_markets_from_polymarket()
    assert _fetch_counter("error") == before + 1


async def test_fetch_markets_from_polymarket_retries(monkeypatch):
    payload = MarketPayload(
        event_id="evt-retry",
        title="Retry",
        category="sports",
        oracle="polymarket",
        status="commit",
        gamma_raw={"id": "evt-retry"},
    )

    attempts = {"count": 0}

    async def flaky_fetch(**kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary failure")
        return [payload]

    monkeypatch.setattr(runtime_module.settings, "polymarket_sync_max_attempts", 2, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_sync_retry_backoff_seconds", 0, raising=False)
    monkeypatch.setattr(runtime_module.settings, "polymarket_sync_retry_backoff_max_seconds", 0, raising=False)
    monkeypatch.setattr("tenacity.nap.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runtime_module, "polymarket_client", type("Dummy", (), {"fetch_events_markets": flaky_fetch})())

    markets, _ = await fetcher.fetch_markets_from_polymarket()

    assert attempts["count"] == 2
    assert markets[0].event_id == "evt-retry"


async def test_publish_heartbeat_retries_on_failure(monkeypatch):
    class FlakyRedis:
        def __init__(self):
            self.calls = 0
            self.payloads: list[str] = []

        def set(self, key, value, ex=None):
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


async def test_publish_heartbeat_logs_after_exhausting_retries(monkeypatch, caplog):
    class BrokenRedis:
        def __init__(self):
            self.calls = 0

        def set(self, *args, **kwargs):
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
    monkeypatch.setattr(runtime_module.settings, "prover_enabled", True, raising=False)
    monkeypatch.setattr(runtime_module.settings, "auto_settlement_enabled", True, raising=False)

    redis_client = DummyRedis()
    market_payload = MarketPayload(
        event_id="evt-proof",
        title="Proof Market",
        outcomes=["Yes", "No"],
        outcome_prices=[0.6, 0.4],
    )
    market_snapshot = {
        "event_id": "evt-proof",
        "market_address": "0xabc",
        "condition_id": "0xabc",
        "commitments_root": "0xroot",
        "tickets": [
            {
                "user": "0x1",
                "outcomeId": "0",
                "amount": "1",
                "salt": "0x1",
                "ticketHash": "0x2",
                "leaf": "0x2",
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
    assert await proofs.maybe_generate_settlement_proof(
        redis_client,
        market_snapshot=market_snapshot,
        market_payload=market_payload,
        condition_id="0xabc",
    )
    assert fake_prover.called_with is not None
    assert redis_client.last_set is not None


def test_polymarket_client_retries_failed_requests(monkeypatch):
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise httpx.ReadTimeout("timeout", request=request)
        return httpx.Response(
            status_code=200,
            json=[{"id": "evt-123", "question": "Will it work?", "category": "AI"}],
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr("tenacity.nap.sleep", lambda *_args, **_kwargs: None)
    client = PolymarketClient(
        "https://gamma.polymarket.example",
        timeout=0.1,
        transport=transport,
        request_max_attempts=3,
        request_backoff_seconds=0,
        request_backoff_max_seconds=0,
    )

    markets = client.fetch_markets(page_size=1, max_pages=1)

    assert attempts["count"] == 3
    assert markets[0].event_id == "evt-123"


def test_polymarket_client_raises_after_request_retry_budget(monkeypatch):
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        raise httpx.ReadTimeout("timeout", request=request)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr("tenacity.nap.sleep", lambda *_args, **_kwargs: None)
    client = PolymarketClient(
        "https://gamma.polymarket.example",
        timeout=0.1,
        transport=transport,
        request_max_attempts=2,
        request_backoff_seconds=0,
        request_backoff_max_seconds=0,
    )

    with pytest.raises(httpx.ReadTimeout):
        client.fetch_markets(page_size=1, max_pages=1)
    assert attempts["count"] == 2
