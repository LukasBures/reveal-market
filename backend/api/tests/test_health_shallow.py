from __future__ import annotations

from app.config import get_settings


def test_health_shallow_returns_ok(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr("app.health.get_settings", lambda: settings)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    assert payload["components"] == {}
