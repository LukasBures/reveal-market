from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime

import httpx
from redis.exceptions import RedisError
from shared.polymarket import build_polymarket_markets_url
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import schemas
from .cache import get_redis_client
from .config import get_settings

ComponentMap = dict[str, schemas.HealthComponent]
_POLYMARKET_NETWORK_WARNED = False
health_logger = logging.getLogger("reveal_market.api.health")


async def build_health_response(session: Session) -> schemas.HealthResponse:
    """Aggregate health information from core dependencies."""

    settings = get_settings()
    components: ComponentMap = {}
    component_states: list[str] = []

    checks: list[tuple[str, schemas.HealthComponent]] = [
        _check_database(session),
        _check_redis_connectivity(),
        _check_worker_heartbeat(settings),
        await _check_polymarket_api(settings),
    ]

    for key, component in checks:
        components[key] = component
        component_states.append(component.status)

    overall_status = _derive_overall_status(component_states)

    return schemas.HealthResponse(
        status=overall_status,
        service=settings.app_name,
        version=settings.version,
        timestamp=datetime.now(tz=UTC),
        components=components,
    )


def _derive_overall_status(states: list[str]) -> str:
    if not states:
        return "ok"
    if "error" in states:
        return "error"
    if "degraded" in states:
        return "degraded"
    return "ok"


def _check_database(session: Session) -> tuple[str, schemas.HealthComponent]:
    db_start = time.perf_counter()
    try:
        session.execute(text("SELECT 1"))
        db_latency = (time.perf_counter() - db_start) * 1000
        component = schemas.HealthComponent(status="ok", latency_ms=db_latency)
    except Exception as exc:  # pragma: no cover - defensive
        component = schemas.HealthComponent(status="error", detail=str(exc))
    return "database", component


def _check_redis_connectivity() -> tuple[str, schemas.HealthComponent]:
    redis_start = time.perf_counter()
    try:
        redis_client = get_redis_client()
        redis_client.ping()
        redis_latency = (time.perf_counter() - redis_start) * 1000
        component = schemas.HealthComponent(status="ok", latency_ms=redis_latency)
    except RedisError as exc:
        component = schemas.HealthComponent(status="error", detail=str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        component = schemas.HealthComponent(status="error", detail=str(exc))
    return "redis", component


def _check_worker_heartbeat(settings) -> tuple[str, schemas.HealthComponent]:
    try:
        redis_client = get_redis_client()
        heartbeat_raw = redis_client.get(settings.heartbeat_key)
        if heartbeat_raw:
            heartbeat = json.loads(heartbeat_raw)
            component = schemas.HealthComponent(
                status="ok",
                detail=f"processed {heartbeat.get('markets_processed', 0)} markets",
                latency_ms=heartbeat.get("latency_ms"),
            )
        else:
            component = schemas.HealthComponent(status="degraded", detail="heartbeat missing")
    except Exception as exc:
        component = schemas.HealthComponent(status="error", detail=str(exc))
    return "worker", component


async def _check_polymarket_api(settings) -> tuple[str, schemas.HealthComponent]:
    http_start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=settings.polymarket_timeout_seconds) as client:
            base = str(settings.polymarket_api_base).rstrip("/")
            markets_url = build_polymarket_markets_url(base)
            await client.get(
                base,
                timeout=settings.polymarket_timeout_seconds,
            )
            params = {
                "limit": 1,
                "order": settings.polymarket_order,
                "ascending": str(settings.polymarket_sort_ascending).lower(),
            }
            if settings.polymarket_closed_filter is not None:
                params["closed"] = str(settings.polymarket_closed_filter).lower()
            if settings.polymarket_network:
                params["network"] = settings.polymarket_network
            else:
                global _POLYMARKET_NETWORK_WARNED
                if not _POLYMARKET_NETWORK_WARNED:
                    health_logger.warning(
                        "polymarket network parameter not configured; defaulting to upstream defaults"
                    )
                    _POLYMARKET_NETWORK_WARNED = True
            response = await client.get(
                markets_url,
                params=params,
                timeout=settings.polymarket_timeout_seconds,
            )
            response.raise_for_status()
        http_latency = (time.perf_counter() - http_start) * 1000
        component = schemas.HealthComponent(status="ok", latency_ms=http_latency)
    except httpx.TimeoutException as exc:
        component = schemas.HealthComponent(status="degraded", detail=str(exc))
    except httpx.HTTPError as exc:
        component = schemas.HealthComponent(status="error", detail=str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        component = schemas.HealthComponent(status="error", detail=str(exc))
    return "polymarket_api", component
