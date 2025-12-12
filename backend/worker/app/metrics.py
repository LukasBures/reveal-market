"""Shared Prometheus counters and cache invalidation reporting helpers for the worker."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from threading import Lock

from shared.logging import log_event

logger = logging.getLogger("reveal_market.worker")

try:
    from prometheus_client import REGISTRY, CollectorRegistry, Counter
except ImportError:  # pragma: no cover - optional dependency

    class _CounterStub:
        def __init__(self, *args, **kwargs):
            pass

        def labels(self, **kwargs):
            return self

        @staticmethod
        def inc(amount: float = 1.0) -> None:
            return None

    class _CollectorRegistryStub:
        pass

    Counter = _CounterStub  # type: ignore[misc,assignment]
    CollectorRegistry = _CollectorRegistryStub  # type: ignore[misc,assignment]
    REGISTRY = None  # type: ignore[assignment]


def _safe_counter(name: str, documentation: str, labelnames: list[str]) -> Counter:
    """Register a Counter while tolerating duplicate registrations in test processes."""

    registry = REGISTRY
    try:
        return Counter(name, documentation, labelnames, registry=registry)
    except ValueError:
        existing = getattr(registry, "_names_to_collectors", {}).get(name) if registry else None
        if isinstance(existing, Counter):
            return existing
        return Counter(name, documentation, labelnames, registry=CollectorRegistry())


RETENTION_METRIC = _safe_counter(
    "worker_retention_candidates_total",
    "Markets considered by the retention reporter",
    ["category"],
)

CACHE_INVALIDATION_COUNTER = _safe_counter(
    "worker_cache_invalidations_total",
    "Number of cache invalidations triggered by the worker",
    ["type"],
)

POLYMARKET_FETCH_COUNTER = _safe_counter(
    "worker_polymarket_fetch_total",
    "Outcome of Polymarket fetch attempts",
    ["outcome"],
)

POLYMARKET_RETRY_COUNTER = _safe_counter(
    "worker_polymarket_retry_total",
    "Retry outcomes for individual Polymarket HTTP requests",
    ["outcome"],
)

POLYMARKET_RATE_LIMIT_COUNTER = _safe_counter(
    "worker_polymarket_rate_limit_total",
    "Rate limit encounters when fetching Polymarket markets",
    ["outcome"],
)

POLYMARKET_EMPTY_PAGE_COUNTER = _safe_counter(
    "worker_polymarket_empty_pages_total",
    "Empty page responses during Polymarket pagination",
    ["outcome"],
)

SUMMARY_DLQ_COUNTER = _safe_counter(
    "worker_summary_dead_letter_total",
    "Summary jobs sent to dead letter queue",
    ["outcome"],
)


def record_retention_metrics(category_counts: dict[str, int]) -> None:
    """Increment retention gauge per category so ops can track expired markets by cohort."""
    for category, count in category_counts.items():
        label = category or "uncategorized"
        RETENTION_METRIC.labels(category=label).inc(count)


@dataclass
class CacheInvalidationReport:
    """Tracks per-tag invalidations to surface in logs and metrics."""

    tag_counts: dict[str, int] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False, compare=False)

    def record(self, tag: str, removed: int) -> None:
        if removed <= 0:
            return
        with self._lock:
            self.tag_counts[tag] = self.tag_counts.get(tag, 0) + removed

    @property
    def total(self) -> int:
        return sum(self.tag_counts.values())

    def log(self) -> None:
        if not self.tag_counts:
            return
        log_event(
            logger,
            logging.DEBUG,
            event="worker.cache.invalidate",
            message="invalidated worker cache tags",
            tags=list(self.tag_counts.keys()),
            total_removed=self.total,
        )
