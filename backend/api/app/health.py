from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Dict

import httpx
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.orm import Session

from .cache import get_redis_client
from .config import get_settings
from . import schemas

ComponentMap = Dict[str, schemas.HealthComponent]


async def build_health_response(session: Session) -> schemas.HealthResponse:
    """Aggregate health information from core dependencies."""

    settings = get_settings()
    components: ComponentMap = {}
    component_states: list[str] = []

    # Database connectivity
    db_start = time.perf_counter()
    try:
        session.execute(text("SELECT 1"))
        db_latency = (time.perf_counter() - db_start) * 1000
        components["database"] = schemas.HealthComponent(status="ok", latency_ms=db_latency)
        component_states.append("ok")
    except Exception as exc:  # pragma: no cover - defensive
        components["database"] = schemas.HealthComponent(status="error", detail=str(exc))
        component_states.append("error")

    # Redis connectivity
    redis_start = time.perf_counter()
    try:
        redis_client = get_redis_client()
        redis_client.ping()
        redis_latency = (time.perf_counter() - redis_start) * 1000
        components["redis"] = schemas.HealthComponent(status="ok", latency_ms=redis_latency)
        component_states.append("ok")
    except RedisError as exc:
        components["redis"] = schemas.HealthComponent(status="error", detail=str(exc))
        component_states.append("error")
    except Exception as exc:  # pragma: no cover - defensive
        components["redis"] = schemas.HealthComponent(status="error", detail=str(exc))
        component_states.append("error")

    # External Polymarket API reachability
    http_start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=settings.polymarket_timeout_seconds) as client:
            base = str(settings.polymarket_api_base).rstrip("/")
            params = {
                "limit": 1,
                "order": settings.polymarket_order,
                "ascending": str(settings.polymarket_sort_ascending).lower(),
            }
            if settings.polymarket_closed_filter is not None:
                params["closed"] = str(settings.polymarket_closed_filter).lower()
            response = await client.get(
                f"{base}/markets",
                params=params,
                timeout=settings.polymarket_timeout_seconds,
            )
            response.raise_for_status()
        http_latency = (time.perf_counter() - http_start) * 1000
        components["polymarket_api"] = schemas.HealthComponent(status="ok", latency_ms=http_latency)
        component_states.append("ok")
    except httpx.TimeoutException as exc:
        components["polymarket_api"] = schemas.HealthComponent(status="degraded", detail=str(exc))
        component_states.append("degraded")
    except httpx.HTTPError as exc:
        components["polymarket_api"] = schemas.HealthComponent(status="error", detail=str(exc))
        component_states.append("error")
    except Exception as exc:  # pragma: no cover - defensive
        components["polymarket_api"] = schemas.HealthComponent(status="error", detail=str(exc))
        component_states.append("error")

    overall_status = _derive_overall_status(component_states)

    return schemas.HealthResponse(
        status=overall_status,
        service=settings.app_name,
        version=settings.version,
        timestamp=datetime.now(tz=timezone.utc),
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
