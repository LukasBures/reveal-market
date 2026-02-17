"""Helpers for reading worker/API heartbeat payloads out of Redis.

The `/healthz/heartbeats` endpoint uses these helpers to surface operational
status without hitting the worker directly.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from redis.exceptions import RedisError
from shared.logging import log_event

from app import runtime, schemas
from app.services.cache_client import get_cache_client

heartbeat_logger = logging.getLogger("reveal_market.api.heartbeat")


def _parse_timestamp(value: str | None) -> datetime | None:
    """Normalize and parse ISO timestamps that may have trailing 'Z'."""

    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


async def _load_heartbeat_payload(key: str) -> dict[str, Any] | None:
    """Fetch and decode a heartbeat JSON blob from Redis."""

    client = await get_cache_client()
    if client is None:
        return None
    try:
        raw = await client.get(key)
    except RedisError as exc:  # pragma: no cover - defensive
        log_event(
            heartbeat_logger,
            logging.WARNING,
            event="heartbeat.dashboard.redis_error",
            message="failed to read heartbeat payload",
            key=key,
            error=str(exc),
        )
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    elif not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log_event(
            heartbeat_logger,
            logging.WARNING,
            event="heartbeat.dashboard.decode_error",
            message="invalid heartbeat payload",
            key=key,
        )
        return None


async def build_worker_dashboard(now: datetime) -> schemas.HeartbeatMetrics | None:
    """Build a summary of the worker heartbeat suitable for dashboards."""

    payload = await _load_heartbeat_payload(runtime.settings.heartbeat_key)
    if payload is None:
        return None
    timestamp = _parse_timestamp(payload.get("timestamp"))
    status_value: schemas.HealthState
    if timestamp is None:
        status_value = "degraded"
    else:
        age = (now - timestamp).total_seconds()
        status_value = "ok" if age <= runtime.settings.worker_heartbeat_stale_seconds else "degraded"
    detail = f"{payload.get('markets_processed', 0)} markets processed"
    return schemas.HeartbeatMetrics(
        service=payload.get("service") or "Reveal Market Worker",
        component=payload.get("component") or "worker",
        status=status_value,
        last_heartbeat=timestamp,
        latency_ms=payload.get("latency_ms"),
        detail=detail,
        metrics={
            "markets_processed": payload.get("markets_processed"),
            "markets_changed": payload.get("markets_changed"),
            "resolutions_changed": payload.get("resolutions_changed"),
        },
    )


async def build_api_dashboard(now: datetime) -> schemas.HeartbeatMetrics | None:
    """Build a summary of the API heartbeat from Redis metrics snapshots."""

    payload = await _load_heartbeat_payload(runtime.settings.api_heartbeat_key)
    if payload is None:
        return None
    timestamp = _parse_timestamp(payload.get("timestamp"))
    status_value: schemas.HealthState
    if timestamp is None:
        status_value = "degraded"
    else:
        age = (now - timestamp).total_seconds()
        status_value = "ok" if age <= runtime.settings.api_heartbeat_ttl_seconds else "degraded"
    metrics_payload = payload.get("metrics") or {}
    detail = f"{metrics_payload.get('total_requests', 0)} requests recorded"
    return schemas.HeartbeatMetrics(
        service=payload.get("service") or runtime.settings.app_name,
        component=payload.get("component") or "api",
        status=status_value,
        last_heartbeat=timestamp,
        latency_ms=metrics_payload.get("avg_latency_ms"),
        detail=detail,
        metrics=metrics_payload,
    )
