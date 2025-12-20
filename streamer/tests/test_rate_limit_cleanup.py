from __future__ import annotations

import inspect

from app.config import Settings
from app.main import create_app


def _get_rate_limit(app):
    stream_route = next(route for route in app.router.routes if getattr(route, "path", None) == "/stream")
    closure = inspect.getclosurevars(stream_route.endpoint)
    return closure.nonlocals["_rate_limit"]


def test_rate_limit_cleanup_prunes_buckets(monkeypatch):
    settings = Settings(rate_limit_per_minute=1)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    now = {"value": 0.0}
    monkeypatch.setattr("app.main.time", lambda: now["value"])

    app = create_app()
    rate_limit = _get_rate_limit(app)

    rate_limit("a")
    rate_limit("b")
    buckets = inspect.getclosurevars(rate_limit).nonlocals["rl_buckets"]
    assert set(buckets.keys()) == {"a", "b"}

    now["value"] = 120.0
    rate_limit("a")
    buckets = inspect.getclosurevars(rate_limit).nonlocals["rl_buckets"]
    assert set(buckets.keys()) == {"a"}
