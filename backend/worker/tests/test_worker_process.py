from __future__ import annotations

import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import logging

from app.main import process_once
from app.polymarket import MarketPayload
from shared.models import Base, Market


def test_process_once_persists_markets_and_emits_heartbeat(monkeypatch, tmp_path, caplog):
    db_url = f"sqlite:///{tmp_path / 'worker.db'}"
    engine = create_engine(db_url, future=True)
    TestSession = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr("app.main.engine", engine, raising=False)
    monkeypatch.setattr("app.main.SessionLocal", TestSession, raising=False)

    sample_markets = [
        MarketPayload(
            event_id="evt-1",
            title="First",
            category="sports",
            metadata_uri=None,
            oracle="polymarket",
            status="commit",
        ),
        MarketPayload(
            event_id="evt-2",
            title="Second",
            category="news",
            metadata_uri=None,
            oracle="polymarket",
            status="commit",
        ),
    ]

    monkeypatch.setattr(
        "app.main.fetch_markets_from_polymarket",
        lambda: (sample_markets, 42.0),
    )

    captured: dict[str, str] = {}

    class DummyRedis:
        def __init__(self):
            self.store: dict[str, str] = {}

        def set(self, key, value, ex):  # noqa: D401 - simple stub
            self.store[key] = value
            captured["key"] = key
            captured["value"] = value
            captured["ttl"] = ex

        def get(self, key):
            return self.store.get(key)

        def delete(self, key):
            self.store.pop(key, None)

        def scan_iter(self, match):
            prefix = match[:-1] if match.endswith("*") else match
            for key in list(self.store.keys()):
                if key.startswith(prefix):
                    yield key

    dummy = DummyRedis()
    caplog.set_level(logging.DEBUG, logger="reveal_market.worker")

    stats = process_once(dummy)
    assert stats["markets_processed"] == len(sample_markets)

    with TestSession() as session:
        stored = session.execute(select(Market)).scalars().all()
        assert len(stored) == 2

    assert captured["key"].startswith("reveal_market_worker")
    assert captured["ttl"] > 0
    heartbeat = json.loads(captured["value"])
    assert heartbeat["markets_processed"] == len(sample_markets)
    assert all(not key.startswith("markets:") for key in dummy.store.keys())

    events = [record.event for record in caplog.records if hasattr(record, "event")]
    assert "worker.fetch.success" in events
    assert "worker.persist.batch" in events
    assert "worker.cache.invalidate" in events
