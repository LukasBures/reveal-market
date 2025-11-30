from __future__ import annotations

import logging
from contextlib import suppress
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .admin import router as admin_router
from .config import get_settings
from .local_logging import log_event, reset_request_id, set_request_id, start_heartbeat_logger
from .logging_config import setup_logging
from .service import HedgerService


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging("reveal_market.hedger", settings.log_level)
    logger = logging.getLogger("reveal_market.hedger")
    sanitized_config = {
        k: v
        for k, v in settings.model_dump().items()
        if not any(secret in k for secret in ["key", "private", "secret", "password"])
    }
    log_event(logger, logging.INFO, event="service.config", message="hedger configuration", config=sanitized_config)

    app = FastAPI(title="Reveal Hedger", version="0.1.0")
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["*"],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or request.headers.get("traceparent") or f"req-{uuid4().hex}"
        token = set_request_id(request_id)
        try:
            response = await call_next(request)
        finally:
            reset_request_id(token)
        response.headers["x-request-id"] = request_id
        return response

    service = HedgerService(settings)
    app.state.service = service
    heartbeat_stop = None

    @app.on_event("startup")
    async def _startup() -> None:
        await service.startup()
        nonlocal heartbeat_stop
        heartbeat_stop = start_heartbeat_logger(
            logger,
            "hedger",
            interval_seconds=settings.heartbeat_interval_seconds,
            message="hedger running",
        )
        log_event(logger, logging.INFO, event="hedger.ready", message="hedger api is ready")

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        if heartbeat_stop:
            heartbeat_stop.set()
        with suppress(Exception):
            await service.fx_oracle.client.aclose()
            await service.settlement.client.aclose()
            await service.bridge_client.client.aclose()
            if service.redis:
                await service.redis.aclose()

    @app.get("/health")
    async def health() -> dict:
        status = await service.health()
        return {"status": "ok", "service": "hedger", **status}

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(admin_router)
    return app
