from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from prometheus_client import REGISTRY, Counter, Gauge


class StreamerMetrics:
    """Container for shared Prometheus instruments and helpers."""

    def __init__(self) -> None:
        self.stream_deliveries = Counter(
            "price_streamer_stream_deliveries_total",
            "Events delivered to clients",
            ["transport", "market_id", "source"],
            registry=REGISTRY,
        )
        self.stream_dropped = Counter(
            "price_streamer_stream_dropped_total",
            "Dropped/ignored stream events",
            ["transport", "reason"],
            registry=REGISTRY,
        )
        self.market_staleness = Gauge(
            "price_streamer_market_staleness_seconds",
            "Seconds since last tick per market",
            ["market_id"],
            registry=REGISTRY,
        )
        self.stale_market_total = Gauge(
            "price_streamer_stale_markets_total",
            "Count of markets considered stale",
            registry=REGISTRY,
        )
        self.assets_fallback = Counter(
            "price_streamer_assets_fallback_total",
            "Connections that fell back to market_id because assets_ids were missing",
            ["transport", "target"],
            registry=REGISTRY,
        )

    def record_delivery(self, transport: str, payload: Any) -> None:
        """Increment delivery counter with parsed labels."""

        market_id = "unknown"
        source = "unknown"
        parsed: dict[str, Any] | None = None
        raw = payload
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8")
            except Exception:
                raw = str(raw)
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = None
        elif isinstance(raw, dict):
            parsed = raw
        if parsed:
            market_id = str(
                parsed.get("market_id")
                or parsed.get("market")
                or parsed.get("id")
                or parsed.get("conditionId")
                or "unknown"
            )
            source = str(parsed.get("source") or parsed.get("type") or parsed.get("event_type") or "unknown")
        self.stream_deliveries.labels(transport=transport, market_id=market_id, source=source).inc()

    def record_drop(self, transport: str, reason: str) -> None:
        self.stream_dropped.labels(transport=transport, reason=reason).inc()

    def record_staleness(self, last_seen: dict[str, datetime], *, stale_after: int) -> list[str]:
        """Update staleness gauges and return stale market ids."""

        now = datetime.now(UTC)
        stale: list[str] = []
        for market_id, ts in last_seen.items():
            age_seconds = max(0.0, (now - ts).total_seconds())
            self.market_staleness.labels(market_id=market_id).set(age_seconds)
            if age_seconds > stale_after:
                stale.append(market_id)
        self.stale_market_total.set(len(stale))
        return stale


_metrics: StreamerMetrics | None = None


def get_metrics() -> StreamerMetrics:
    global _metrics
    if _metrics is None:
        _metrics = StreamerMetrics()
    return _metrics
