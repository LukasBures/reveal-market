from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.metrics import RequestMetrics, classify_latency_bucket, update_cache_context


def test_request_metrics_records_and_snapshots():
    metrics = RequestMetrics(slow_threshold_ms=120)

    metrics.record(status_code=200, duration_ms=80, bytes_sent=512, cache_hit=True)
    metrics.record(status_code=502, duration_ms=240, bytes_sent=256, cache_hit=False)

    snapshot = metrics.snapshot()

    assert snapshot["total_requests"] == 2
    assert snapshot["error_count"] == 1
    assert snapshot["cache_hits"] == 1
    assert snapshot["cache_misses"] == 1
    assert snapshot["slow_requests"] == 1
    assert snapshot["bytes_sent_total"] == 768
    assert snapshot["max_latency_ms"] == pytest.approx(240.0)
    assert snapshot["avg_latency_ms"] == pytest.approx((80 + 240) / 2, rel=1e-3)
    buckets = snapshot["latency_buckets"]
    assert buckets["50-100ms"] == 1
    assert buckets["100-250ms"] == 1


def test_classify_latency_bucket_ranges():
    assert classify_latency_bucket(10) == "<50ms"
    assert classify_latency_bucket(75) == "50-100ms"
    assert classify_latency_bucket(150) == "100-250ms"
    assert classify_latency_bucket(400) == "250-500ms"
    assert classify_latency_bucket(800) == "500-1000ms"
    assert classify_latency_bucket(1500) == ">=1000ms"


def test_update_cache_context_sets_request_state():
    request = SimpleNamespace(state=SimpleNamespace())
    update_cache_context(request, cache_key="markets:list|limit=5", hit=True, source="markets:list")
    ctx = request.state.cache_context
    assert ctx["cache_key"] == "markets:list|limit=5"
    assert ctx["cache_hit"] is True
    assert ctx["cache_source"] == "markets:list"


def test_update_cache_context_handles_missing_request():
    # Ensure this helper is defensive and does not raise
    update_cache_context(None, cache_key="x", hit=False, source=None)
