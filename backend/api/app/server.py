"""Async FastAPI application factory and dependency wiring.

This module keeps all global setup in one place so tests can import a fully
configured app without booting uvicorn. It also exposes the long-lived
rate limiter instance for reuse in middleware/tests.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import cast

import httpx
from fastapi import FastAPI
from shared.indexers import AsyncGoldskyClient
from shared.logging import log_event

from app.http_middleware import attach_request_context, configure_http_middleware
from app.pricing import fetch_fx_quote
from app.rate_limit import RateLimiter
from app.routes import markets, meta, pricing, proofs, treasury
from app.routes.pricing import build_quote_digest
from app.runtime import cache_client, is_production, logger, mode_env, settings
from app.services.cache_client import get_cache_client
from app.services.markets import hydrate_markets_cache
from app.tasks import cache_refresh_loop, quote_sweeper_loop, run_startup_tasks, stop_background_tasks


def _build_goldsky_client() -> AsyncGoldskyClient | None:
    """Create a Goldsky client if credentials exist, logging any failures."""

    endpoint = settings.goldsky_subgraph_url
    if not endpoint:
        log_event(
            logger,
            logging.DEBUG,
            event="goldsky.disabled",
            message="goldsky client disabled (missing endpoint)",
        )
        return None
    api_key = settings.goldsky_api_key.get_secret_value() if settings.goldsky_api_key else None
    try:
        client = AsyncGoldskyClient(
            str(endpoint),
            api_key=api_key,
            timeout_seconds=settings.goldsky_timeout_seconds,
        )
    except (ValueError, RuntimeError, httpx.HTTPError, httpx.RequestError) as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="goldsky.error",
            message="failed to initialise goldsky client",
            error=str(exc),
        )
        return None
    log_event(
        logger,
        logging.INFO,
        event="goldsky.enabled",
        message="goldsky client initialised",
    )
    return client


def _initialise_clients() -> None:
    """Populate global clients (Goldsky) during app creation."""

    from app import runtime  # avoid cycle

    if runtime.goldsky_client is None:
        runtime.goldsky_client = _build_goldsky_client()


def _log_environment() -> None:
    """Emit a single startup log showing resolved environment and mode."""

    logger.info(
        "service environment resolved",
        extra={
            "event": "service.env",
            "settings_environment": settings.environment,
            "mode_env": mode_env or None,
            "is_production": is_production,
        },
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan hook that starts and stops background tasks."""

    log_event(
        logger,
        logging.INFO,
        event="service.lifespan.start",
        message="api lifespan starting",
    )
    await run_startup_tasks()
    log_event(
        logger,
        logging.INFO,
        event="service.lifespan.ready",
        message="api startup complete; serving traffic",
    )
    try:
        yield
    finally:
        log_event(
            logger,
            logging.INFO,
            event="service.lifespan.stop",
            message="api lifespan stopping",
        )
        await stop_background_tasks()
        log_event(
            logger,
            logging.INFO,
            event="service.lifespan.stopped",
            message="api background tasks stopped",
        )


def create_app() -> FastAPI:
    """
    Build a FastAPI app instance with middleware, routes, and lifecycle hooks.

    FastAPI caches the app at module import, so this stays lightweight and
    side-effect free beyond client initialisation and middleware wiring.
    """

    _log_environment()
    rate_limiter = RateLimiter(lambda: settings, get_cache_client)
    app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
    app.cache_client = None  # type: ignore[attr-defined]
    configure_http_middleware(app, rate_limiter=rate_limiter)
    attach_request_context(app)
    _initialise_clients()
    app.include_router(meta.router)
    app.include_router(pricing.router)
    app.include_router(treasury.router)
    app.include_router(markets.router)
    app.include_router(proofs.router)
    app.rate_limiter = rate_limiter  # type: ignore[attr-defined]
    return app


app = create_app()
rate_limiter: RateLimiter = cast(RateLimiter, app.rate_limiter)  # type: ignore[attr-defined]
_cache_refresh_loop = cache_refresh_loop
_quote_sweeper_loop = quote_sweeper_loop

__all__ = [
    "app",
    "create_app",
    "settings",
    "cache_client",
    "fetch_fx_quote",
    "build_quote_digest",
    "get_cache_client",
    "hydrate_markets_cache",
    "rate_limiter",
    "_cache_refresh_loop",
    "_quote_sweeper_loop",
]
