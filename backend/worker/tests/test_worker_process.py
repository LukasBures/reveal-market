from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import app.main
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.main import (
    SchemaSyncResult,
    cleanup_resolved_markets,
    prime_featured_views,
    prime_markets_cache,
    process_once,
    record_batch_stats,
)
from app.polymarket import MarketPayload
from shared import cache as shared_cache
from shared.cache_keys import suggest_cache_key
from shared.models import Base, Market
from .test_sync_market import create_in_memory_db


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
    TestSession = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr("app.main.engine", engine, raising=False)
    monkeypatch.setattr("app.main.SessionLocal", TestSession, raising=False)
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

    stats = process_once(dummy)
    assert stats["markets_processed"] == len(sample_markets)
    assert stats["markets_changed"] == len(sample_markets)
    assert stats["resolutions_changed"] == 0
    assert stats["categories_changed"] == 2
    assert stats["tags_changed"] == 0
    assert stats["markets_changed"] == len(sample_markets)
    assert stats["resolutions_changed"] == 0

    with TestSession() as session:
        stored = session.execute(select(Market)).scalars().all()
        assert len(stored) == 2

    assert dummy.last_set is not None
    assert dummy.last_set["key"].startswith("reveal_market_worker")
    assert dummy.last_set["ttl"] > 0
    heartbeat = json.loads(dummy.last_set["value"])
    assert heartbeat["markets_processed"] == len(sample_markets)
    assert all(not key.startswith("markets:") for key in dummy.store.keys())
    assert {"market:evt-1", "market:evt-2", "markets:stats"}.issubset(set(invalidated_tags))

    events = [record.event for record in caplog.records if hasattr(record, "event")]
    assert "worker.persist.batch" in events
    assert "worker.cache.invalidate" in events


def test_process_once_publishes_schema_revision(monkeypatch):
    """Ensure schema revisions are broadcast to Redis and tagged caches are invalidated."""

    dummy = DummyRedis()
    schema_state = SchemaSyncResult(changed=True, previous_revision="0002_resolutions", current_revision="0003_schema_versions")

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
    assert stats["resolutions_changed"] == 0
    assert dummy.store.get(app.main.settings.schema_version_key) == schema_state.current_revision
    assert "schema:unknown" in invalidated
    assert f"schema:{schema_state.previous_revision}" in invalidated


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
    assert payload["prime"] == prime_stats


def test_cleanup_resolved_markets_removes_expired(monkeypatch):
    engine, TestSession = create_in_memory_db()
    try:
        deleted_counter = DummyCounter()
        skipped_counter = DummyCounter()
        monkeypatch.setattr("app.main.RETENTION_DELETED_COUNTER", deleted_counter, raising=False)
        monkeypatch.setattr("app.main.RETENTION_SKIPPED_COUNTER", skipped_counter, raising=False)
        expired = Market(
            event_id="evt-old",
            title="Old market",
            category="Sports",
            oracle="0xold",
            status="settled",
            resolved_at=datetime.now(timezone.utc) - timedelta(days=2),
            tags=["Gov"],
        )
        recent = Market(
            event_id="evt-new",
            title="Fresh market",
            category="News",
            oracle="0xnew",
            status="settled",
            resolved_at=datetime.now(timezone.utc),
            tags=["Crypto"],
        )
        with TestSession() as session:
            session.add_all([expired, recent])
            session.commit()

        monkeypatch.setattr(app.main.settings, "resolved_retention_seconds", 60 * 60, raising=False)

        with TestSession() as session:
            outcome = cleanup_resolved_markets(session, now=datetime.now(timezone.utc))
            session.commit()

        assert "evt-old" in outcome.events
        assert "evt-new" not in outcome.events
        assert "sports" in {slug for slug in outcome.categories if slug}
        assert "gov" in {slug for slug in outcome.tags if slug}
        assert outcome.deleted_rows == 1
        assert outcome.eligible_rows == 1
        assert outcome.dry_run is False
        assert deleted_counter.records and deleted_counter.records[0]["amount"] == 1
        assert skipped_counter.records == []

        with TestSession() as session:
            remaining = session.execute(select(Market.event_id)).scalars().all()
            assert remaining == ["evt-new"]
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


def test_cleanup_resolved_markets_respects_dry_run(monkeypatch):
    engine, TestSession = create_in_memory_db()
    try:
        deleted_counter = DummyCounter()
        skipped_counter = DummyCounter()
        monkeypatch.setattr("app.main.RETENTION_DELETED_COUNTER", deleted_counter, raising=False)
        monkeypatch.setattr("app.main.RETENTION_SKIPPED_COUNTER", skipped_counter, raising=False)
        market = Market(
            event_id="evt-dry",
            title="Dry run",
            category="Crypto",
            oracle="0xdry",
            status="settled",
            resolved_at=datetime.now(timezone.utc) - timedelta(days=2),
            tags=["btc"],
        )
        with TestSession() as session:
            session.add(market)
            session.commit()

        with TestSession() as session:
            outcome = cleanup_resolved_markets(
                session,
                dry_run=True,
                now=datetime.now(timezone.utc),
            )
            session.commit()

        assert outcome.deleted_rows == 0
        assert outcome.eligible_rows == 1
        assert outcome.dry_run is True
        with TestSession() as session:
            remaining = session.execute(select(Market.event_id)).scalars().all()
            assert remaining == ["evt-dry"]
        assert skipped_counter.records and skipped_counter.records[0]["amount"] == 1
        assert deleted_counter.records == []
    finally:
        engine.dispose()


def test_cleanup_resolved_markets_handles_timezone_offsets(monkeypatch):
    engine, TestSession = create_in_memory_db()
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
        with TestSession() as session:
            session.add(market)
            session.commit()

        monkeypatch.setattr(app.main.settings, "resolved_retention_seconds", 60 * 60, raising=False)
        reference = datetime(2024, 3, 10, 7, 0, tzinfo=timezone.utc)
        with TestSession() as session:
            outcome = cleanup_resolved_markets(session, now=reference)
            session.commit()

        assert outcome.deleted_rows == 1
        with TestSession() as session:
            remaining = session.execute(select(Market.event_id)).scalars().all()
            assert remaining == []
    finally:
        engine.dispose()
