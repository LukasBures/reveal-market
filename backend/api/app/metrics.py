from __future__ import annotations

import time
from threading import Lock
from typing import Any, Dict, Optional


_LATENCY_BUCKETS = (
    (50.0, "<50ms"),
    (100.0, "50-100ms"),
    (250.0, "100-250ms"),
    (500.0, "250-500ms"),
    (1000.0, "500-1000ms"),
)


def classify_latency_bucket(duration_ms: float) -> str:
    for threshold, label in _LATENCY_BUCKETS:
        if duration_ms < threshold:
            return label
    return ">=1000ms"


class RequestMetrics:
    """Thread-safe accumulator for API request performance statistics."""

    def __init__(self, slow_threshold_ms: float = 500.0):
        self._lock = Lock()
        self._slow_threshold_ms = slow_threshold_ms
        self._reset()

    def _reset(self) -> None:
        now = time.time()
        self._window_started = now
        self._last_updated = now
        self._total_requests = 0
        self._error_count = 0
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_unknown = 0
        self._total_latency_ms = 0.0
        self._max_latency_ms = 0.0
        self._bytes_sent_total = 0
        self._slow_requests = 0
        self._latency_buckets: Dict[str, int] = {label: 0 for _, label in _LATENCY_BUCKETS}
        self._latency_buckets[">=1000ms"] = 0

    def record(
        self,
        *,
        status_code: int,
        duration_ms: float,
        bytes_sent: int,
        cache_hit: Optional[bool],
    ) -> None:
        with self._lock:
            self._total_requests += 1
            self._total_latency_ms += duration_ms
            self._last_updated = time.time()
            if duration_ms > self._max_latency_ms:
                self._max_latency_ms = duration_ms
            if bytes_sent > 0:
                self._bytes_sent_total += bytes_sent
            if status_code >= 500:
                self._error_count += 1
            if cache_hit is True:
                self._cache_hits += 1
            elif cache_hit is False:
                self._cache_misses += 1
            else:
                self._cache_unknown += 1
            if duration_ms >= self._slow_threshold_ms:
                self._slow_requests += 1
            bucket_label = classify_latency_bucket(duration_ms)
            self._latency_buckets[bucket_label] = self._latency_buckets.get(bucket_label, 0) + 1

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            uptime = now - self._window_started
            snapshot = {
                "window_started_at": self._window_started,
                "window_seconds": uptime,
                "last_updated_at": self._last_updated,
                "total_requests": self._total_requests,
                "error_count": self._error_count,
                "cache_hits": self._cache_hits,
                "cache_misses": self._cache_misses,
                "cache_unknown": self._cache_unknown,
                "bytes_sent_total": self._bytes_sent_total,
                "slow_requests": self._slow_requests,
                "max_latency_ms": self._max_latency_ms,
                "latency_buckets": dict(self._latency_buckets),
            }
            if self._total_requests > 0:
                snapshot["avg_latency_ms"] = self._total_latency_ms / self._total_requests
                known_cache = self._cache_hits + self._cache_misses
                snapshot["cache_hit_rate"] = (
                    self._cache_hits / known_cache if known_cache > 0 else None
                )
            else:
                snapshot["avg_latency_ms"] = None
                snapshot["cache_hit_rate"] = None
            return snapshot


def update_cache_context(request, *, cache_key: str | None, hit: bool, source: str | None = None) -> None:
    """Attach cache metadata to the request state so middleware can log it."""

    if request is None or not hasattr(request, "state"):
        return
    request.state.cache_context = {
        "cache_key": cache_key,
        "cache_hit": hit,
        "cache_source": source,
    }
