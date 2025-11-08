from __future__ import annotations

import json
import logging
from typing import Any

import app.main
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.main import SchemaSyncResult, process_once
from app.polymarket import MarketPayload
from shared import cache as shared_cache
from shared.models import Base, Market


class DummyRedis:
    def __init__(self):
        self.store: dict[str, Any] = {}
        self.last_set: dict[str, Any] | None = None

    def set(self, key: str, value: Any, ex: int | None = None):
        self.store[key] = value
        self.last_set = {"key": key, "value": value, "ttl": ex}

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
    caplog.set_level(logging.DEBUG, logger="reveal_market.worker")

    stats = process_once(dummy)
    assert stats["markets_processed"] == len(sample_markets)

    with TestSession() as session:
        stored = session.execute(select(Market)).scalars().all()
        assert len(stored) == 2

    assert dummy.last_set is not None
    assert dummy.last_set["key"].startswith("reveal_market_worker")
    assert dummy.last_set["ttl"] > 0
    heartbeat = json.loads(dummy.last_set["value"])
    assert heartbeat["markets_processed"] == len(sample_markets)
    assert all(not key.startswith("markets:") for key in dummy.store.keys())

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
    assert dummy.store.get(app.main.settings.schema_version_key) == schema_state.current_revision
    assert "schema:unknown" in invalidated
    assert f"schema:{schema_state.previous_revision}" in invalidated
