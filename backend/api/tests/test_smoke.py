from __future__ import annotations

from sqlalchemy import inspect


def test_health_and_metrics_endpoints(client, db_session):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] in {"ok", "degraded", "error"}

    metrics_response = client.get("/metrics")
    assert metrics_response.status_code == 200
    assert "python_info" in metrics_response.text

    inspector = inspect(db_session.bind)
    assert "markets" in inspector.get_table_names()
