from __future__ import annotations

from shared.db_metrics import DbMetricsSnapshot, DbQueryHotspot

from app import service as worker_service


def test_log_db_metrics_emits_hotspots(monkeypatch):
    monkeypatch.setattr(worker_service.runtime.settings, "db_query_warn_threshold", 1, raising=False)
    monkeypatch.setattr(worker_service.runtime.settings, "db_query_time_warn_ms", 1.0, raising=False)
    monkeypatch.setattr(worker_service.runtime.settings, "db_query_hotspot_limit", 3, raising=False)
    monkeypatch.setattr(worker_service.runtime.settings, "db_query_hotspot_min_total_ms", 0.0, raising=False)

    monkeypatch.setattr(
        "shared.db_metrics.snapshot",
        lambda: DbMetricsSnapshot(query_count=12, total_time_ms=987.6, max_time_ms=123.4),
    )
    monkeypatch.setattr(
        "shared.db_metrics.snapshot_hotspots",
        lambda limit, min_total_time_ms: [
            DbQueryHotspot(
                query="SELECT * FROM markets WHERE id = ?",
                query_count=5,
                total_time_ms=501.2,
                max_time_ms=190.3,
            )
        ],
    )

    emitted: list[dict] = []

    def _capture_log_event(_logger, _level, **kwargs):
        emitted.append(kwargs)

    monkeypatch.setattr(worker_service, "log_event", _capture_log_event)
    worker_service._log_db_metrics("process_once")

    budget_event = next(item for item in emitted if item["event"] == "worker.db.query_budget.exceeded")
    assert budget_event["query_count"] == 12
    assert budget_event["hotspot_count"] == 1

    hotspot_event = next(item for item in emitted if item["event"] == "worker.db.query_hotspots")
    assert hotspot_event["context"] == "process_once"
    assert hotspot_event["hotspots"][0]["query_count"] == 5
    assert hotspot_event["hotspots"][0]["query"] == "SELECT * FROM markets WHERE id = ?"
