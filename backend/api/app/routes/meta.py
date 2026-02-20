"""Meta/health routes for the Reveal Market API."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas
from app.config import get_settings
from app.database import get_session
from app.health import build_deep_health_response, build_health_response
from app.runtime import settings as runtime_settings
from app.services.heartbeat import build_api_dashboard, build_worker_dashboard

router = APIRouter()
settings = runtime_settings


def _verify_internal_secret(secret_header: str | None) -> None:
    if not settings.internal_api_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="internal_secret_not_configured",
        )
    if secret_header != settings.internal_api_secret.get_secret_value():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_internal_secret")


@router.get("/", tags=["meta"])
async def read_root() -> dict[str, str]:
    """Basic service metadata for quick smoke tests."""

    cfg = get_settings()
    return {
        "service": cfg.app_name,
        "version": cfg.version,
        "environment": cfg.environment,
    }


@router.get("/healthz", response_model=schemas.HealthResponse, tags=["health"])
async def health_check(session: AsyncSession = Depends(get_session)) -> schemas.HealthResponse:
    """Readiness probe that fans out to DB/Redis/worker/Polymarket checks."""

    return await build_health_response(session)


@router.get("/healthz/deep", response_model=schemas.HealthResponse, tags=["health"])
async def health_check_deep(
    session: AsyncSession = Depends(get_session),
    force: bool = Query(default=False),
) -> schemas.HealthResponse:
    """Deep health probe (cached) for dependency checks."""

    return await build_deep_health_response(session, force=force)


@router.get("/ready", response_model=schemas.HealthResponse, tags=["health"])
async def readiness_check(session: AsyncSession = Depends(get_session)) -> schemas.HealthResponse:
    """Alias for /healthz used by Kubernetes readiness probes."""

    return await build_health_response(session)


@router.get("/live", tags=["health"])
async def liveness_check() -> dict[str, str]:
    """Cheap liveness probe that never touches dependencies."""

    return {"status": "ok"}


@router.get("/healthz/heartbeats", response_model=schemas.HeartbeatDashboard, tags=["health"])
async def heartbeat_dashboard(
    internal_secret: str | None = Header(default=None, alias="X-Internal-Secret"),
) -> schemas.HeartbeatDashboard:
    """Return worker/API heartbeat snapshots stored in Redis."""

    _verify_internal_secret(internal_secret)
    now = datetime.now(tz=UTC)
    worker_status = await build_worker_dashboard(now)
    api_status = await build_api_dashboard(now)
    return schemas.HeartbeatDashboard(
        generated_at=now,
        worker=worker_status,
        api=api_status,
    )
