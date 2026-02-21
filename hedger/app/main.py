from __future__ import annotations

import logging
from contextlib import asynccontextmanager, suppress
from threading import Event
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .admin import router as admin_router
from .config import get_settings
from .local_logging import log_event, reset_request_id, set_request_id, start_heartbeat_logger
from .logging_config import setup_logging
from .rate_limit import RateLimiter
from .service import HedgerService


def create_app() -> FastAPI:
    settings = get_settings()
    env = (settings.environment or "").strip().lower()
    if env not in {"local", "dev", "development", "test"} and not settings.admin_internal_secret:
        raise RuntimeError("HEDGER_ADMIN_INTERNAL_SECRET is required when environment is not local/test")
    setup_logging("reveal_market.hedger")
    logger = logging.getLogger("reveal_market.hedger")
    sanitized_config = {
        k: v
        for k, v in settings.model_dump().items()
        if not any(secret in k for secret in ["key", "private", "secret", "password"])
    }
    log_event(logger, logging.INFO, event="service.config", message="hedger configuration", config=sanitized_config)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        heartbeat_stop: Event | None = None
        try:
            await service.startup()
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                event="hedger.startup.failed",
                message="hedger startup failed; continuing in degraded mode",
                error=str(exc),
            )
        heartbeat_stop = start_heartbeat_logger(
            logger,
            "hedger",
            interval_seconds=settings.heartbeat_interval_seconds,
            message="hedger running",
        )
        log_event(logger, logging.INFO, event="hedger.ready", message="hedger api is ready")
        try:
            yield
        finally:
            if heartbeat_stop:
                heartbeat_stop.set()
            with suppress(Exception):
                await service.fx_oracle.client.aclose()
                await service.settlement.client.aclose()
                await service.bridge_client.client.aclose()
                if service.redis:
                    await service.redis.aclose()

    middleware = [
        Middleware(TrustedHostMiddleware, allowed_hosts=["*"]),
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        ),
    ]
    app = FastAPI(title="Reveal Hedger", version="0.1.0", lifespan=lifespan, middleware=middleware)

    admin_rate_limiter = None
    if settings.admin_rate_limit_requests > 0:
        admin_rate_limiter = RateLimiter(
            settings.admin_rate_limit_requests,
            settings.admin_rate_limit_window_seconds,
        )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or request.headers.get("traceparent") or f"req-{uuid4().hex}"
        token = set_request_id(request_id)
        try:
            if admin_rate_limiter and request.url.path.startswith("/admin"):
                client_ip = request.client.host if request.client else "unknown"
                key = f"{client_ip}:{request.url.path}"
                if not admin_rate_limiter.allow(key):
                    raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate_limited")
            response = await call_next(request)
        finally:
            reset_request_id(token)
        response.headers["x-request-id"] = request_id
        return response

    service = HedgerService(settings)
    app.state.service = service

    @app.get("/healthz")
    async def healthz() -> dict:
        snapshot = service.cached_health_snapshot()
        return snapshot or {"status": "ok", "service": "hedger"}

    @app.get("/healthz/deep")
    async def healthz_deep(force: bool = False) -> dict:
        if force:
            payload = await service.health()
            service.store_health_snapshot(payload)
            return payload
        snapshot = service.cached_health_snapshot()
        if snapshot:
            return snapshot
        payload = await service.health()
        service.store_health_snapshot(payload)
        return payload

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(admin_router)
    return app
