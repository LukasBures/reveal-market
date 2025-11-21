from __future__ import annotations

from worker.app import main as worker_main


def test_prime_markets_cache_handles_missing_redis(monkeypatch):
    monkeypatch.setattr(worker_main.settings, "prime_markets_cache_enabled", True, raising=False)
    summary = worker_main.prime_markets_cache(redis_client=None)
    assert summary["status"] == "skipped"
    assert summary["reason"] == "redis_unavailable"


def test_prime_featured_views_noops_without_api_base(monkeypatch):
    monkeypatch.setattr(worker_main.settings, "api_base_url", None, raising=False)
    result = worker_main.prime_featured_views(redis_client=None)
    assert result == {"categories_primed": 0, "suggestions_primed": 0, "suggestion_ttls": {}}
