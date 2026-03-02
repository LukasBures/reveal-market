from __future__ import annotations

from shared.db_metrics import attach_db_metrics, reset_metrics, snapshot, snapshot_hotspots
from sqlalchemy import create_engine, text


def test_snapshot_hotspots_tracks_query_fingerprints():
    engine = create_engine("sqlite://")
    attach_db_metrics(engine)
    reset_metrics()

    with engine.connect() as connection:
        for _ in range(3):
            connection.execute(text("SELECT 1"))
        connection.execute(text("SELECT 2"))
        connection.execute(text("SELECT :value"), {"value": 99})

    metrics = snapshot()
    assert metrics.query_count == 5
    assert metrics.total_time_ms >= 0

    hotspots = snapshot_hotspots(limit=5, min_total_time_ms=0)
    assert hotspots
    assert hotspots[0].query.startswith("SELECT")
    assert hotspots[0].query_count >= 1

    total_hotspot_count = sum(item.query_count for item in hotspots)
    assert total_hotspot_count == metrics.query_count


def test_snapshot_hotspots_honors_limit():
    engine = create_engine("sqlite://")
    attach_db_metrics(engine)
    reset_metrics()

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        connection.execute(text("SELECT 2"))

    hotspots = snapshot_hotspots(limit=1, min_total_time_ms=0)
    assert len(hotspots) == 1
