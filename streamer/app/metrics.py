from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from prometheus_client import REGISTRY, CollectorRegistry, Counter, Gauge


class StreamerMetrics:
    """Container for shared Prometheus instruments and helpers."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        registry = registry or REGISTRY
        self.stream_deliveries = Counter(
            "streamer_stream_deliveries_total",
            "Events delivered to clients",
            ["transport", "market_id", "source"],
            registry=registry,
        )
        self.stream_dropped = Counter(
            "streamer_stream_dropped_total",
            "Dropped/ignored stream events",
            ["transport", "reason"],
            registry=registry,
        )
        self.market_staleness = Gauge(
            "streamer_market_staleness_seconds",
            "Seconds since last tick per market",
            ["market_id"],
            registry=registry,
        )
        self.stale_market_total = Gauge(
            "streamer_stale_markets_total",
            "Count of markets considered stale",
            registry=registry,
        )
        self.assets_fallback = Counter(
            "streamer_assets_fallback_total",
            "Connections that fell back to market_id because assets_ids were missing",
            ["transport", "target"],
            registry=registry,
        )
        self.ingest_dropped = Counter(
            "streamer_ingest_dropped_total",
            "Dropped/ignored ingest events",
            ["source", "reason"],
            registry=registry,
        )
        self.clob_ws_connected = Gauge(
            "streamer_clob_ws_connected",
            "CLOB websocket connectivity (1=connected,0=disconnected)",
            registry=registry,
        )
        self.clob_ws_last_message_ts = Gauge(
            "streamer_clob_ws_last_message_timestamp_seconds",
            "Unix timestamp of last CLOB websocket message",
            registry=registry,
        )
        self.clob_rest_last_poll_ts = Gauge(
            "streamer_clob_rest_last_poll_timestamp_seconds",
            "Unix timestamp of last CLOB REST poll attempt",
            registry=registry,
        )
        self.clob_rest_last_success_ts = Gauge(
            "streamer_clob_rest_last_success_timestamp_seconds",
            "Unix timestamp of last successful CLOB REST poll",
            registry=registry,
        )
        self.rtds_ws_connected = Gauge(
            "streamer_rtds_ws_connected",
            "RTDS websocket connectivity (1=connected,0=disconnected)",
            registry=registry,
        )
        self.rtds_last_message_ts = Gauge(
            "streamer_rtds_last_message_timestamp_seconds",
            "Unix timestamp of last RTDS message",
            registry=registry,
        )
        self.rtds_enabled = Gauge(
            "streamer_rtds_enabled",
            "RTDS enabled flag (1=enabled,0=disabled)",
            registry=registry,
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
            except UnicodeDecodeError:
                raw = str(raw)
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
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

    def record_ingest_drop(self, source: str, reason: str) -> None:
        self.ingest_dropped.labels(source=source, reason=reason).inc()

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

    def record_clob_ws_connected(self, connected: bool) -> None:
        self.clob_ws_connected.set(1 if connected else 0)

    def record_clob_ws_message(self, ts: datetime) -> None:
        self.clob_ws_last_message_ts.set(ts.timestamp())

    def record_clob_rest_poll(self, ts: datetime) -> None:
        self.clob_rest_last_poll_ts.set(ts.timestamp())

    def record_clob_rest_success(self, ts: datetime) -> None:
        self.clob_rest_last_success_ts.set(ts.timestamp())

    def record_rtds_ws_connected(self, connected: bool) -> None:
        self.rtds_ws_connected.set(1 if connected else 0)

    def record_rtds_message(self, ts: datetime) -> None:
        self.rtds_last_message_ts.set(ts.timestamp())

    def record_rtds_enabled(self, enabled: bool) -> None:
        self.rtds_enabled.set(1 if enabled else 0)


_metrics: StreamerMetrics | None = None


def get_metrics() -> StreamerMetrics:
    global _metrics
    if _metrics is None:
        _metrics = StreamerMetrics()
    return _metrics
