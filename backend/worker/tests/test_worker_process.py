from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import app.main
import httpx
import pytest
from app.main import (
    SchemaSyncResult,
    cleanup_resolved_markets,
    maybe_generate_settlement_proof,
    prime_featured_views,
    prime_markets_cache,
    process_once,
    record_batch_stats,
)
from app.main import (
    settings as worker_settings,
)
from app.polymarket import MarketPayload, PolymarketClient
from app.prover_client import SettlementProofResponse
from prometheus_client import REGISTRY
from shared import cache as shared_cache
from shared.cache_keys import suggest_cache_key
from shared.models import Base, Market
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from tests.test_sync_market import create_in_memory_db


class DummyRedis:
    def __init__(self):
        self.store: dict[str, Any] = {}
        self.last_set: dict[str, Any] | None = None
        self._ttls: dict[str, int | None] = {}

    def set(self, key: str, value: Any, ex: int | None = None):
        self.store[key] = value
        self.last_set = {"key": key, "value": value, "ttl": ex}
        self._ttls[key] = ex

    def get(self, key: str):
        return self.store.get(key)

    def delete(self, *keys: str):
        for key in keys:
            self.store.pop(key, None)

    def scan_iter(self, match: str):
        prefix = match[:-1] if match.endswith("*") else match
        for key in list(self.store.keys()):
            if key.startswith(prefix):
                yield key

    def sadd(self, key: str, value: str):
        self.store.setdefault(key, set()).add(value)

    def smembers(self, key: str):
        members = self.store.get(key)
        if isinstance(members, set):
            return set(members)
        return set()

    def ttl(self, key: str):
        ttl = self._ttls.get(key)
        if ttl is None:
            return -1
        return ttl

    def lpush(self, key: str, value: Any):
        queue = self.store.setdefault(key, [])
        if not isinstance(queue, list):
            queue = []
            self.store[key] = queue
        queue.insert(0, value)

    def rpush(self, key: str, value: Any):
        queue = self.store.setdefault(key, [])
        if not isinstance(queue, list):
            queue = []
            self.store[key] = queue
        queue.append(value)


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


def test_process_once_persists_markets_and_emits_heartbeat(monkeypatch, tmp_path, caplog):
    db_url = f"sqlite:///{tmp_path / 'worker.db'}"
    engine = create_engine(db_url, future=True)
    session_factory = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr("app.main.engine", engine, raising=False)
    monkeypatch.setattr("app.main.SessionLocal", session_factory, raising=False)
    monkeypatch.setattr(app.main.settings, "run_migrations_on_startup", False, raising=False)

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
            extra_data={"gamma": {"id": "evt-1"}},
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
            extra_data={"gamma": {"id": "evt-2"}},
        ),
    ]

    monkeypatch.setattr(
        "app.main.fetch_markets_from_polymarket",
        lambda: (sample_markets, 42.0),
    )

    dummy = DummyRedis()
    invalidated_tags: list[str] = []

    def fake_invalidate(_, tag: str):
        invalidated_tags.append(tag)
        return []

    monkeypatch.setattr(shared_cache, "invalidate_tag", fake_invalidate, raising=False)
    caplog.set_level(logging.DEBUG, logger="reveal_market.worker")

    category_before = (
        REGISTRY.get_sample_value(
            "worker_cache_invalidations_total",
            labels={"type": "category"},
        )
        or 0
    )
    stats = process_once(dummy)
    assert stats["markets_processed"] == len(sample_markets)
    assert stats["markets_changed"] == len(sample_markets)
    assert stats["resolutions_changed"] == 0
    assert stats["categories_changed"] == 2
    assert stats["tags_changed"] == 0
    assert stats["markets_changed"] == len(sample_markets)
    assert stats["resolutions_changed"] == 0
    assert stats["summaries_enqueued"] == 0
    assert stats["cache_invalidations"] >= 0

    with session_factory() as session:
        stored = session.execute(select(Market)).scalars().all()
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


def test_process_once_publishes_schema_revision(monkeypatch):
    """Ensure schema revisions are broadcast to Redis and tagged caches are invalidated."""

    dummy = DummyRedis()
    schema_state = SchemaSyncResult(
        changed=True,
        previous_revision="0002_resolutions",
        current_revision="0003_schema_versions",
    )

    monkeypatch.setattr("app.main._ensure_schema", lambda: schema_state, raising=False)
    monkeypatch.setattr("app.main.fetch_markets_from_polymarket", lambda: ([], 5.0), raising=False)

    invalidated: list[str] = []

    def fake_invalidate(redis_client, tag: str):
        invalidated.append(tag)
        return []

    monkeypatch.setattr(shared_cache, "invalidate_tag", fake_invalidate, raising=False)

    stats = process_once(dummy)
    assert stats["markets_processed"] == 0
    assert stats["markets_changed"] == 0
    assert stats["resolutions_changed"] == 0
    assert stats["markets_changed"] == 0
    assert stats["summaries_enqueued"] == 0
    assert stats["resolutions_changed"] == 0
    assert dummy.store.get(app.main.settings.schema_version_key) == schema_state.current_revision
    assert "schema:unknown" in invalidated
    assert f"schema:{schema_state.previous_revision}" in invalidated


def test_process_once_handles_polymarket_failures(monkeypatch, caplog):
    dummy = DummyRedis()
    schema_state = SchemaSyncResult(
        changed=False,
        previous_revision=None,
        current_revision="0004_latest_revision",
    )

    def fail_fetch():
        raise RuntimeError("connect refused")

    published_stats: dict[str, Any] = {}

    def fake_publish(_redis, stats):
        published_stats.update(stats)

    monkeypatch.setattr("app.main._ensure_schema", lambda: schema_state, raising=False)
    monkeypatch.setattr("app.main.fetch_markets_from_polymarket", fail_fetch, raising=False)
    monkeypatch.setattr("app.main.publish_heartbeat", fake_publish, raising=False)

    caplog.set_level(logging.WARNING, logger="reveal_market.worker")
    stats = process_once(dummy)

    assert stats["markets_processed"] == 0
    assert stats == published_stats
    assert dummy.store.get(app.main.settings.schema_version_key) == schema_state.current_revision
    events = [getattr(record, "event", None) for record in caplog.records]
    assert "worker.sync.skipped" in events


def test_prime_markets_cache_stores_payload(monkeypatch):
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
        return httpx.Response(status_code=200, json=payload)

    transport = httpx.MockTransport(handler)

    monkeypatch.setattr(app.main.settings, "api_base_url", "http://api:8000", raising=False)
    monkeypatch.setattr(app.main.settings, "markets_cache_limit", 7, raising=False)
    monkeypatch.setattr(app.main.settings, "markets_cache_offset", 0, raising=False)
    monkeypatch.setattr(app.main.settings, "markets_cache_ttl_seconds", 45, raising=False)
    monkeypatch.setattr(app.main.settings, "cache_prime_timeout_seconds", 2.0, raising=False)
    monkeypatch.setattr(app.main.settings, "prime_markets_cache_enabled", True, raising=False)

    summary = prime_markets_cache(dummy, transport=transport)
    assert summary["status"] == "primed"
    assert summary["result_count"] == len(payload)
    assert dummy.last_set is not None
    assert dummy.last_set["key"].startswith("markets:list:")
    assert dummy.last_set["ttl"] == 45
    cached_payload = json.loads(dummy.last_set["value"])
    assert cached_payload == payload
    tag_members = dummy.store.get("cache:tag:markets:list")
    assert dummy.last_set["key"] in tag_members


def test_record_batch_stats_publishes_metrics(monkeypatch):
    dummy = DummyRedis()
    monkeypatch.setattr(app.main.settings, "batch_stats_key", "worker:batch_stats", raising=False)
    monkeypatch.setattr(app.main.settings, "batch_stats_ttl_seconds", 300, raising=False)
    stats = {
        "markets_processed": 12,
        "markets_changed": 4,
        "resolutions_changed": 1,
        "categories_changed": 2,
        "tags_changed": 3,
        "latency_ms": 55.2,
    }
    prime_stats = {"status": "primed", "cache_key": "markets:list:*"}

    record_batch_stats(dummy, stats, prime_stats)

    assert dummy.last_set is not None
    assert dummy.last_set["key"] == "worker:batch_stats"
    assert dummy.last_set["ttl"] == 300
    payload = json.loads(dummy.last_set["value"])
    assert payload["markets_processed"] == 12
    assert payload["markets_changed"] == 4
    assert payload["resolutions_changed"] == 1
    assert payload["categories_changed"] == 2
    assert payload["tags_changed"] == 3
    assert payload["prime"] == prime_stats


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
            tags=["Gov"],
        )
        recent = Market(
            event_id="evt-new",
            title="Fresh market",
            category="News",
            oracle="0xnew",
            status="settled",
            resolved_at=datetime.now(UTC),
            tags=["Crypto"],
        )
        with session_factory() as session:
            session.add_all([expired, recent])
            session.commit()

        monkeypatch.setattr(app.main.settings, "resolved_retention_seconds", 60 * 60, raising=False)

        with session_factory() as session:
            outcome = cleanup_resolved_markets(session, now=datetime.now(UTC))
            session.commit()

        assert outcome.events == {"evt-old"}
        assert "sports" in {slug for slug in outcome.categories if slug}
        assert "gov" in {slug for slug in outcome.tags if slug}
        assert outcome.deleted_rows == 0
        assert outcome.eligible_rows == 1
        assert outcome.dry_run is True

        with session_factory() as session:
            remaining = session.execute(select(Market.event_id)).scalars().all()
            assert set(remaining) == {"evt-old", "evt-new"}
    finally:
        engine.dispose()


def test_prime_featured_views_prefetches_categories_and_tags(monkeypatch):
    dummy = DummyRedis()
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if "/markets/suggest" in request.url.path:
            key = suggest_cache_key("Alpha query", app.main.settings.suggest_cache_limit)
            shared_cache.set_json(dummy, key, [], 30)
        return httpx.Response(status_code=200, json=[])

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(app.main.settings, "api_base_url", "http://api:8000", raising=False)
    monkeypatch.setattr(app.main.settings, "featured_categories", ["Politics"], raising=False)
    monkeypatch.setattr(app.main.settings, "featured_tags", ["BTC halving"], raising=False)
    monkeypatch.setattr(app.main.settings, "featured_suggest_queries", ["Alpha query"], raising=False)
    monkeypatch.setattr(app.main.settings, "category_cache_limit", 7, raising=False)
    monkeypatch.setattr(app.main.settings, "tag_cache_limit", 5, raising=False)
    monkeypatch.setattr(app.main.settings, "suggest_cache_limit", 4, raising=False)

    summary = prime_featured_views(dummy, transport=transport)

    assert summary["categories_primed"] == 1
    assert summary["tags_primed"] == 1
    assert summary["suggestions_primed"] == 1
    assert summary["suggestion_ttls"]["Alpha query"] == 30
    assert any("/categories/Politics" in url and "limit=7" in url for url in requests)
    assert any("/tags/BTC+halving" in url and "limit=5" in url for url in requests)
    assert any("/markets/suggest" in url and "limit=4" in url for url in requests)


def _fetch_counter(outcome: str) -> float:
    value = REGISTRY.get_sample_value("worker_polymarket_fetch_total", {"outcome": outcome})
    return value or 0.0


def test_fetch_markets_from_polymarket_counts_success(monkeypatch):
    payload = MarketPayload(
        event_id="evt-success",
        title="OK",
        category="sports",
        oracle="polymarket",
        status="commit",
        extra_data={"gamma": {"id": "evt-success"}},
    )

    monkeypatch.setattr(app.main.polymarket_client, "fetch_markets", lambda **kwargs: [payload], raising=False)
    before = _fetch_counter("success")

    markets, _ = app.main.fetch_markets_from_polymarket()

    assert markets[0].event_id == "evt-success"
    assert _fetch_counter("success") == before + 1


def test_fetch_markets_from_polymarket_counts_errors(monkeypatch):
    def always_fail(**kwargs):
        raise RuntimeError("fatal failure")

    monkeypatch.setattr(app.main.polymarket_client, "fetch_markets", always_fail, raising=False)
    before = _fetch_counter("error")
    with pytest.raises(RuntimeError):
        app.main.fetch_markets_from_polymarket()
    assert _fetch_counter("error") == before + 1


def test_publish_heartbeat_retries_on_failure(monkeypatch):
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
    monkeypatch.setattr(app.main.settings, "heartbeat_max_retries", 3, raising=False)
    monkeypatch.setattr(app.main.settings, "heartbeat_retry_backoff_seconds", 0, raising=False)
    monkeypatch.setattr(app.main.settings, "heartbeat_retry_backoff_max_seconds", 0, raising=False)
    monkeypatch.setattr("tenacity.nap.sleep", lambda *_args, **_kwargs: None)

    app.main.publish_heartbeat(redis_client, {"markets_processed": 5})
    assert redis_client.calls == 2
    assert json.loads(redis_client.payloads[-1])["markets_processed"] == 5


def test_publish_heartbeat_logs_after_exhausting_retries(monkeypatch, caplog):
    class BrokenRedis:
        def __init__(self):
            self.calls = 0

        def set(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("still down")

    redis_client = BrokenRedis()
    monkeypatch.setattr(app.main.settings, "heartbeat_max_retries", 2, raising=False)
    monkeypatch.setattr(app.main.settings, "heartbeat_retry_backoff_seconds", 0, raising=False)
    monkeypatch.setattr(app.main.settings, "heartbeat_retry_backoff_max_seconds", 0, raising=False)
    monkeypatch.setattr("tenacity.nap.sleep", lambda *_args, **_kwargs: None)

    with caplog.at_level(logging.WARNING):
        app.main.publish_heartbeat(redis_client, {"markets_processed": 1})

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
            tags=["btc"],
        )
        with session_factory() as session:
            session.add(market)
            session.commit()

        with session_factory() as session:
            outcome = cleanup_resolved_markets(
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

        monkeypatch.setattr(app.main.settings, "resolved_retention_seconds", 60 * 60, raising=False)
        reference = datetime(2024, 3, 10, 7, 0, tzinfo=UTC)
        with session_factory() as session:
            outcome = cleanup_resolved_markets(session, now=reference)
            session.commit()

        assert outcome.deleted_rows == 0
        assert outcome.eligible_rows == 1
        assert outcome.dry_run is True
        with session_factory() as session:
            remaining = session.execute(select(Market.event_id)).scalars().all()
            assert remaining == ["evt-tz"]
    finally:
        engine.dispose()


def test_maybe_generate_settlement_proof(monkeypatch):
    class FakeProver:
        def __init__(self):
            self.called_with = None

        def generate_settlement_proof(self, request):
            self.called_with = request
            return SettlementProofResponse(
                proof="0xdead",
                public_signals=["1"],
                circuit_hash="0xabc",
                generated_at=datetime.now(UTC),
                prover_version="test",
                request_nonce=request.nonce,
            )

    fake_prover = FakeProver()
    monkeypatch.setattr(app.main, "PROVER_CLIENT", fake_prover, raising=False)
    monkeypatch.setattr(worker_settings, "prover_enabled", True, raising=False)

    redis_client = DummyRedis()
    market_payload = MarketPayload(
        event_id="evt-proof",
        title="Proof Market",
        outcomes=["Yes", "No"],
        outcome_prices=[0.6, 0.4],
    )
    market_snapshot = {"event_id": "evt-proof", "market_address": None, "condition_id": "0xabc"}
    assert maybe_generate_settlement_proof(
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
