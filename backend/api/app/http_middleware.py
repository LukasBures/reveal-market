"""HTTP middleware stack for the Reveal Market API.

This module wires logging, CORS, security headers, metrics, and request/response
instrumentation. Everything stays async so the request pipeline remains
non-blocking even when Redis or metrics backends are slow to respond.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.logging_config import setup_logging
from app.metrics import classify_latency_bucket
from app.metrics_registry import REQUEST_LATENCY
from app.rate_limit import RateLimiter, RateLimitMiddleware
from app.runtime import instrumentator, is_production, logger, preset, sanitized_config, settings
from app.security import SecurityHeadersMiddleware
from app.services.cache_client import get_cache_client
from app.utils.requests import estimate_response_bytes, extract_cache_metadata


def _coerce_preset_list(value: object) -> list[str]:
    """Normalize preset values into a list of strings."""

    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return []


def _log_cors_warnings(origins: list[str], scope: str) -> None:
    """Warn when CORS is open to avoid accidental wildcard in production."""

    if not origins or origins == ["*"]:
        logger.warning("CORS allow_origins is wildcard; set explicit origins for production", extra={"scope": scope})


def _metric_path(request: Request) -> str:
    """Return a templated path for metrics to keep cardinality low."""

    route = request.scope.get("route")
    if route is not None:
        for attr in ("path", "path_format"):
            template = getattr(route, attr, None)
            if isinstance(template, str) and template:
                return template
    return request.url.path


def configure_http_middleware(app: FastAPI, rate_limiter: RateLimiter | None = None) -> None:
    """
    Attach the full HTTP middleware stack (logging, CORS, security, metrics).

    The function is intentionally side-effectful: it mutates FastAPI state,
    configures Prometheus instrumentation, and wires a shared RateLimiter.
    """

    setup_logging("reveal_market.api")
    logger.info("service configuration", extra={"event": "service.config", "config": sanitized_config})
    allowed_hosts = _coerce_preset_list(preset.get("api_allowed_hosts"))
    if allowed_hosts and allowed_hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    cors_origins = _coerce_preset_list(preset.get("api_cors_origins"))
    expected_prod_origins = set(cors_origins if is_production else _coerce_preset_list(preset.get("api_cors_origins")))
    local_origins = set(_coerce_preset_list(preset.get("api_cors_origins"))) if not is_production else set()
    if not is_production:
        cors_origins = list(local_origins)
    if cors_origins and cors_origins != ["*"] and is_production:
        missing_cors = sorted(origin for origin in expected_prod_origins if origin not in cors_origins)
        if missing_cors:
            logger.warning(
                "RM_CORS_ALLOW_ORIGINS missing expected frontend origins",
                extra={"event": "cors.origins.missing", "missing": missing_cors},
            )
    settings.cors_allow_origins = cors_origins

    connect_sources = {"'self'"}
    for origin in cors_origins:
        sanitized = origin.rstrip("/")
        if sanitized:
            connect_sources.add(sanitized)
            if sanitized.startswith("http://") or sanitized.startswith("https://"):
                ws_variant = sanitized.replace("http://", "ws://").replace("https://", "wss://")
                connect_sources.add(ws_variant)
    for preset_origin in (preset.get("streamer_public"), preset.get("streamer_internal")):
        if isinstance(preset_origin, str) and preset_origin:
            sanitized = preset_origin.rstrip("/")
            connect_sources.add(sanitized)
            if sanitized.startswith("http://") or sanitized.startswith("https://"):
                ws_variant = sanitized.replace("http://", "ws://").replace("https://", "wss://")
                connect_sources.add(ws_variant)

    # Attach CORS before any other middleware so headers remain consistent.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )

    if settings.enable_security_headers:
        connect_src = " ".join(sorted(connect_sources))
        api_csp = (
            "default-src 'none'; "
            "frame-ancestors 'none'; "
            "form-action 'none'; "
            "base-uri 'none'; "
            f"connect-src {connect_src};"
        )
        docs_csp = (
            "default-src 'none'; "
            "frame-ancestors 'none'; "
            "form-action 'none'; "
            "base-uri 'none'; "
            f"connect-src {connect_src}; "
            "img-src 'self' data: https://fastapi.tiangolo.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "font-src 'self' https://cdn.jsdelivr.net data:;"
        )
        app.add_middleware(
            SecurityHeadersMiddleware,
            headers={"Content-Security-Policy": api_csp},
            per_path_overrides={
                "/docs": {"Content-Security-Policy": docs_csp},
                "/redoc": {"Content-Security-Policy": docs_csp},
                "/openapi.json": {"Content-Security-Policy": docs_csp},
            },
        )

    if not getattr(app.state, "metrics_instrumented", False):
        instrumentator.instrument(app).expose(app, include_in_schema=False, tags=["metrics"])
        app.state.metrics_instrumented = True

    limiter_instance = rate_limiter or RateLimiter(lambda: settings, get_cache_client)
    app.add_middleware(RateLimitMiddleware, settings=lambda: settings, limiter=limiter_instance)
    app.state.rate_limiter = limiter_instance
    _log_cors_warnings(settings.cors_allow_origins, scope="api")


def _log_request_completion(
    request: Request, response, start_time: float, cache_meta: dict[str, Any], request_id: str
) -> None:
    """Record latency, cache metadata, and emit Prometheus metrics on completion."""

    duration_ms = (time.perf_counter() - start_time) * 1000
    bytes_sent = estimate_response_bytes(response)
    latency_bucket = classify_latency_bucket(duration_ms)
    metric_path = _metric_path(request)
    try:
        REQUEST_LATENCY.labels(method=request.method, path=metric_path, status_code=str(response.status_code)).observe(
            duration_ms / 1000.0
        )
    except Exception as metric_exc:  # pragma: no cover - defensive metrics guard
        logger.debug(
            "failed to emit request latency metric",
            extra={"event": "metrics.emit.failed", "message": str(metric_exc)},
        )
    logger.info(
        "request completed",
        extra={
            "event": "http.request.completed",
            "path": request.url.path,
            "method": request.method,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2),
            "latency_bucket": latency_bucket,
            "bytes_sent": bytes_sent,
            "cache_hit": cache_meta.get("cache_hit"),
            "cache_source": cache_meta.get("cache_source"),
            "cache_key": cache_meta.get("cache_key"),
        },
    )
    from app.runtime import request_metrics  # local to avoid cycle

    request_metrics.record(
        status_code=response.status_code,
        duration_ms=duration_ms,
        bytes_sent=bytes_sent,
        cache_hit=cache_meta.get("cache_hit"),
    )


def attach_request_context(app: FastAPI) -> None:
    """
    Attach middleware that sets request ids, tracks cache metadata, and logs lifecycle events.

    This keeps request-scoped context out of global state while ensuring every
    log line is tied back to a stable identifier.
    """

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        from shared.logging import log_event, reset_request_id, set_request_id

        request_id = request.headers.get("x-request-id") or request.headers.get("traceparent") or str(uuid.uuid4())
        token = set_request_id(request_id)
        start_time = time.perf_counter()
        request.state.cache_context = {
            "cache_hit": None,
            "cache_key": None,
            "cache_source": None,
        }
        log_event(
            logger,
            logging.DEBUG,
            event="http.request.start",
            message="incoming request",
            method=request.method,
            path=request.url.path,
            client=request.client.host if request.client else None,
        )
        try:
            response = await call_next(request)
        except HTTPException as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            cache_meta = extract_cache_metadata(request)
            metric_path = _metric_path(request)
            try:
                REQUEST_LATENCY.labels(
                    method=request.method, path=metric_path, status_code=str(exc.status_code)
                ).observe(duration_ms / 1000.0)
            except Exception as metric_exc:  # pragma: no cover
                log_event(
                    logger,
                    logging.DEBUG,
                    event="metrics.emit.failed",
                    message="failed to emit request latency metric",
                    error=str(metric_exc),
                )
            log_event(
                logger,
                logging.WARNING if 400 <= exc.status_code < 500 else logging.ERROR,
                event="http.request.error",
                message="request failed",
                path=request.url.path,
                method=request.method,
                status_code=exc.status_code,
                duration_ms=round(duration_ms, 2),
                latency_bucket=classify_latency_bucket(duration_ms),
                cache_hit=cache_meta["cache_hit"],
                cache_source=cache_meta["cache_source"],
                cache_key=cache_meta["cache_key"],
            )
            from app.runtime import request_metrics  # local import to prevent cycles

            request_metrics.record(
                status_code=exc.status_code,
                duration_ms=duration_ms,
                bytes_sent=0,
                cache_hit=cache_meta["cache_hit"],
            )
            reset_request_id(token)
            raise
        except Exception:
            duration_ms = (time.perf_counter() - start_time) * 1000
            cache_meta = extract_cache_metadata(request)
            metric_path = _metric_path(request)
            try:
                REQUEST_LATENCY.labels(method=request.method, path=metric_path, status_code="500").observe(
                    duration_ms / 1000.0
                )
            except Exception as metric_exc:  # pragma: no cover
                log_event(
                    logger,
                    logging.DEBUG,
                    event="metrics.emit.failed",
                    message="failed to emit request latency metric",
                    error=str(metric_exc),
                )
            log_event(
                logger,
                logging.ERROR,
                event="http.request.error",
                message="request failed",
                path=request.url.path,
                method=request.method,
                status_code=500,
                duration_ms=round(duration_ms, 2),
                latency_bucket=classify_latency_bucket(duration_ms),
                cache_hit=cache_meta["cache_hit"],
                cache_source=cache_meta["cache_source"],
                cache_key=cache_meta["cache_key"],
            )
            from app.runtime import request_metrics  # local import to prevent cycles

            request_metrics.record(
                status_code=500,
                duration_ms=duration_ms,
                bytes_sent=0,
                cache_hit=cache_meta["cache_hit"],
            )
            reset_request_id(token)
            raise
        cache_meta = extract_cache_metadata(request)
        response.headers["x-request-id"] = request_id
        _log_request_completion(request, response, start_time, cache_meta, request_id)
        reset_request_id(token)
        return response
