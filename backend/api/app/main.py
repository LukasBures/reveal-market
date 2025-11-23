from __future__ import annotations

import json
import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import httpx
from decimal import Decimal
from threading import Event, Lock, Thread
from typing import Annotated, Any
from urllib.parse import unquote_plus
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator
from shared.cache import add_tag, add_tags, get_client, get_json, get_schema_tag, invalidate_tag, set_json
from shared.cache_keys import category_cache_key, markets_list_cache_key, resolution_cache_key, suggest_cache_key
from shared.categories import canonical_category_from_slug
from shared.indexers import GoldskyClient
from shared.logging import log_event, reset_request_id, set_request_id, start_heartbeat_logger
from shared.onchain import OnChainConfigurationError
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import crud, schemas
from app.config import Settings, get_settings
from app.database import get_session, run_migrations, session_scope
from app.health import build_health_response
from app.logging_config import setup_logging
from app.metrics import RequestMetrics, classify_latency_bucket, update_cache_context
from app.onchain import fetch_factory_markets
from app.pricing import PricingEngine, fetch_fx_quote
from app.rate_limit import RateLimiter, RateLimitMiddleware
from app.security import SecurityHeadersMiddleware
from app import models

try:
    from redis import Redis
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - redis is an optional dependency during certain tests
    Redis = Any  # type: ignore
    RedisError = Exception  # type: ignore

setup_logging("reveal_market.api")

settings = get_settings()


def _current_settings() -> Settings:
    return settings


logger = logging.getLogger("reveal_market.api")
instrumentator = Instrumentator()
cache_client: Redis | None = None
_cache_lock = Lock()
_heartbeat_stop_event: Event | None = None
_metrics_stop_event: Event | None = None
_cache_refresh_stop_event: Event | None = None
request_metrics = RequestMetrics(settings.slow_request_threshold_ms)
goldsky_client: GoldskyClient | None = None

MARKETS_STATS_KEY = "markets:stats"
MARKET_DETAIL_PREFIX = "markets:detail"

MARKETS_CACHE_COUNTER = Counter(
    "markets_cache_requests_total",
    "Cache hits and misses for /markets",
    ["outcome", "status", "category"],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _heartbeat_stop_event, _metrics_stop_event, _cache_refresh_stop_event
    run_migrations()
    _heartbeat_stop_event = start_heartbeat_logger(
        logger,
        settings.app_name,
        interval_seconds=settings.container_heartbeat_seconds,
        message=f"{settings.app_name} container heartbeat",
    )
    if _metrics_stop_event is None:
        _metrics_stop_event = _start_metrics_publisher()
    if settings.cache_hydrate_on_startup:
        hydrate_markets_cache(source="startup", limit=settings.cache_hydrate_limit)
    if _cache_refresh_stop_event is None:
        _cache_refresh_stop_event = _start_cache_refresh_worker()
    yield
    if _heartbeat_stop_event is not None:
        _heartbeat_stop_event.set()
        _heartbeat_stop_event = None
    if _metrics_stop_event is not None:
        _metrics_stop_event.set()
        _metrics_stop_event = None
    if _cache_refresh_stop_event is not None:
        _cache_refresh_stop_event.set()
        _cache_refresh_stop_event = None


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
if settings.allowed_hosts and settings.allowed_hosts != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)

if settings.enable_security_headers:
    api_csp = "default-src 'none'; frame-ancestors 'none'; form-action 'none'; base-uri 'none'; connect-src 'self';"
    docs_csp = (
        "default-src 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'none'; "
        "base-uri 'none'; "
        "connect-src 'self'; "
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
app.cache_client = cache_client  # type: ignore[attr-defined]


def _extract_cache_hit(request: Request | None) -> bool | None:
    ctx = getattr(request.state, "cache_context", None) if request else None
    if isinstance(ctx, dict):
        return ctx.get("cache_hit")
    return None


def _extract_cache_metadata(request: Request | None) -> dict[str, Any]:
    ctx = getattr(request.state, "cache_context", None) if request else None
    if isinstance(ctx, dict):
        return {
            "cache_key": ctx.get("cache_key"),
            "cache_source": ctx.get("cache_source"),
            "cache_hit": ctx.get("cache_hit"),
        }
    return {"cache_key": None, "cache_source": None, "cache_hit": None}


def _estimate_response_bytes(response) -> int:
    header_len = response.headers.get("content-length")
    if header_len:
        try:
            return int(header_len)
        except ValueError:
            pass
    body = getattr(response, "body", None)
    if isinstance(body, (bytes, bytearray)):
        return len(body)
    return 0


def _publish_api_heartbeat() -> None:
    client = get_cache_client()
    if client is None:
        return
    snapshot = request_metrics.snapshot()
    payload = {
        "service": settings.app_name,
        "component": "api",
        "environment": settings.environment,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "uptime_seconds": snapshot.get("window_seconds"),
        "metrics": {
            **snapshot,
            "window_started_at": datetime.fromtimestamp(snapshot["window_started_at"], tz=UTC).isoformat()
            if snapshot.get("window_started_at")
            else None,
            "last_updated_at": datetime.fromtimestamp(snapshot["last_updated_at"], tz=UTC).isoformat()
            if snapshot.get("last_updated_at")
            else None,
        },
    }
    try:
        client.set(
            settings.api_heartbeat_key,
            json.dumps(payload),
            ex=settings.api_heartbeat_ttl_seconds,
        )
    except RedisError as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="api.heartbeat.error",
            message="failed to publish api heartbeat",
            error=str(exc),
        )
    else:
        log_event(
            logger,
            logging.DEBUG,
            event="api.heartbeat.published",
            message="published api heartbeat snapshot",
            requests_total=snapshot.get("total_requests"),
            cache_hit_rate=snapshot.get("cache_hit_rate"),
            avg_latency_ms=snapshot.get("avg_latency_ms"),
        )


def _start_metrics_publisher() -> Event:
    stop_event = Event()
    interval = max(10, settings.performance_heartbeat_interval_seconds)

    def _run() -> None:
        while not stop_event.wait(interval):
            _publish_api_heartbeat()

    thread = Thread(target=_run, name="api-metrics-publisher", daemon=True)
    thread.start()
    return stop_event


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _load_heartbeat_payload(key: str) -> dict[str, Any] | None:
    client = get_cache_client()
    if client is None:
        return None
    try:
        raw = client.get(key)
    except RedisError as exc:  # pragma: no cover - defensive
        log_event(
            logger,
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
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log_event(
            logger,
            logging.WARNING,
            event="heartbeat.dashboard.decode_error",
            message="invalid heartbeat payload",
            key=key,
        )
        return None


def _build_worker_dashboard(now: datetime) -> schemas.HeartbeatMetrics | None:
    payload = _load_heartbeat_payload(settings.heartbeat_key)
    if payload is None:
        return None
    timestamp = _parse_timestamp(payload.get("timestamp"))
    status_value: schemas.HealthState
    if timestamp is None:
        status_value = "degraded"
    else:
        age = (now - timestamp).total_seconds()
        status_value = "ok" if age <= settings.worker_heartbeat_stale_seconds else "degraded"
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


def _build_api_dashboard(now: datetime) -> schemas.HeartbeatMetrics | None:
    payload = _load_heartbeat_payload(settings.api_heartbeat_key)
    if payload is None:
        return None
    timestamp = _parse_timestamp(payload.get("timestamp"))
    status_value: schemas.HealthState
    if timestamp is None:
        status_value = "degraded"
    else:
        age = (now - timestamp).total_seconds()
        status_value = "ok" if age <= settings.api_heartbeat_ttl_seconds else "degraded"
    metrics_payload = payload.get("metrics") or {}
    detail = f"{metrics_payload.get('total_requests', 0)} requests recorded"
    return schemas.HeartbeatMetrics(
        service=payload.get("service") or settings.app_name,
        component=payload.get("component") or "api",
        status=status_value,
        last_heartbeat=timestamp,
        latency_ms=metrics_payload.get("avg_latency_ms"),
        detail=detail,
        metrics=metrics_payload,
    )


def _connect_cache_with_retry() -> Redis | None:
    attempts = max(1, settings.cache_connect_retries)
    delay = max(0.0, settings.cache_connect_retry_delay_seconds)
    for attempt in range(1, attempts + 1):
        client = get_client(settings.redis_url)
        if client is None:
            if attempt < attempts and delay:
                time.sleep(delay)
            continue
        try:
            client.ping()
        except RedisError as exc:  # pragma: no cover - network flake
            log_event(
                logger,
                logging.WARNING,
                event="cache.connect.ping_failed",
                message="redis ping failed, will retry",
                attempt=attempt,
                error=str(exc),
            )
            if attempt < attempts and delay:
                time.sleep(delay)
            continue
        log_event(
            logger,
            logging.INFO,
            event="cache.connect.established",
            message="connected to redis",
            attempt=attempt,
        )
        return client
    log_event(
        logger,
        logging.WARNING,
        event="cache.connect.unavailable",
        message="redis unavailable after retries, continuing without cache",
        attempts=attempts,
    )
    return None


def get_cache_client() -> Redis | None:
    global cache_client
    if cache_client is not None:
        return cache_client
    with _cache_lock:
        if cache_client is None:
            cache_client = _connect_cache_with_retry()
            if cache_client is not None:
                app.cache_client = cache_client  # type: ignore[attr-defined]
    return cache_client


def hydrate_markets_cache(source: str = "manual", *, limit: int | None = None) -> dict[str, Any]:
    """Populate the hottest markets into Redis directly from Postgres."""

    cache = get_cache_client()
    target_limit = limit or settings.cache_hydrate_limit or settings.cacheable_market_limit
    summary = {
        "source": source,
        "status": "skipped",
        "limit": target_limit,
    }
    if cache is None:
        summary["reason"] = "redis_unavailable"
        return summary
    if target_limit is None or target_limit <= 0:
        summary["reason"] = "invalid_limit"
        return summary
    hydrated_limit = min(
        max(1, int(target_limit)),
        settings.cacheable_market_limit,
        settings.max_page_size,
    )
    start_time = time.perf_counter()
    with session_scope() as session:
        records = crud.get_markets(session, limit=hydrated_limit, offset=0)
    market_models = _filter_markets_for_visibility(
        _augment_market_models([schemas.MarketResponse.model_validate(m) for m in records])
    )
    if not market_models:
        summary["reason"] = "no_markets"
        return summary
    cache_key = markets_list_cache_key(None, None, None, None, hydrated_limit, 0)
    schema_tag = get_schema_tag(cache, settings.schema_version_key)
    _write_market_list_cache(cache, cache_key, market_models)
    add_tag(cache, schema_tag, cache_key)
    add_tag(cache, "markets:list", cache_key)
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    log_event(
        logger,
        logging.INFO,
        event="markets.cache.hydrate",
        message="hydrated markets cache from database",
        source=source,
        limit=hydrated_limit,
        result_count=len(market_models),
        cache_key=cache_key,
        duration_ms=duration_ms,
    )
    summary.update(
        {
            "status": "hydrated",
            "limit": hydrated_limit,
            "result_count": len(market_models),
            "cache_key": cache_key,
            "duration_ms": duration_ms,
        }
    )
    return summary


def _start_cache_refresh_worker() -> Event | None:
    if not settings.cache_refresh_enabled:
        return None
    stop_event = Event()
    thread = Thread(target=_cache_refresh_loop, args=(stop_event,), daemon=True)
    thread.start()
    log_event(
        logger,
        logging.INFO,
        event="markets.cache.refresh.start",
        message="started background cache refresh worker",
        interval_seconds=settings.cache_refresh_interval_seconds,
        limit=settings.cache_refresh_limit,
    )
    return stop_event


def _cache_refresh_loop(stop_event: Event) -> None:
    interval = max(1, settings.cache_refresh_interval_seconds)
    while not stop_event.is_set():
        try:
            hydrate_markets_cache(source="refresh", limit=settings.cache_refresh_limit)
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                logger,
                logging.WARNING,
                event="markets.cache.refresh.error",
                message="failed to refresh markets cache",
                error=str(exc),
            )
        stop_event.wait(interval)


rate_limiter = RateLimiter(_current_settings, get_cache_client)
app.add_middleware(RateLimitMiddleware, settings=_current_settings, limiter=rate_limiter)


def _build_goldsky_client() -> GoldskyClient | None:
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
        client = GoldskyClient(
            str(endpoint),
            api_key=api_key,
            timeout_seconds=settings.goldsky_timeout_seconds,
        )
    except Exception as exc:  # pragma: no cover - defensive
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


goldsky_client = _build_goldsky_client()


def _filter_markets_for_visibility(markets: list[schemas.MarketResponse]) -> list[schemas.MarketResponse]:
    category_allow = {item.lower() for item in settings.market_category_allowlist if isinstance(item, str)}
    if not category_allow:
        return markets

    filtered: list[schemas.MarketResponse] = []
    for market in markets:
        if isinstance(market.category, str) and market.category.lower() in category_allow:
            filtered.append(market)

    removed = len(markets) - len(filtered)
    if removed > 0:
        log_event(
            logger,
            logging.DEBUG,
            event="markets.list.filtered",
            message="filtered markets via allowlists",
            removed=removed,
            remaining=len(filtered),
            category_allowlist=list(category_allow),
        )
    return filtered


def _market_record_cache_key(event_id: str) -> str:
    return f"market:{event_id}"


def _should_cache_market_list(limit: int, offset: int, search_query: str | None) -> bool:
    if offset != 0:
        return False
    if search_query:
        return False
    return limit <= settings.cacheable_market_limit


def _sanitize_market_response(market: schemas.MarketResponse) -> dict[str, Any]:
    payload = market.model_dump(mode="json")
    extra = payload.get("extra_data")
    if isinstance(extra, dict):
        trimmed = {k: v for k, v in extra.items() if k.lower() != "gamma"}
        payload["extra_data"] = trimmed or None
    return payload


def _hydrate_cached_market_list(cache: Redis | None, cached_payload: Any) -> list[schemas.MarketResponse] | None:
    if cached_payload is None:
        return None
    if isinstance(cached_payload, list):
        return [schemas.MarketResponse.model_validate(item) for item in cached_payload]
    if isinstance(cached_payload, dict):
        event_ids = cached_payload.get("event_ids")
        if not isinstance(event_ids, list):
            return None
        markets: list[schemas.MarketResponse] = []
        for event_id in event_ids:
            if not isinstance(event_id, str):
                return None
            record = get_json(cache, _market_record_cache_key(event_id))
            if record is None:
                return None
            markets.append(schemas.MarketResponse.model_validate(record))
        return markets
    return None


def _write_market_list_cache(cache: Redis | None, cache_key: str, markets: list[schemas.MarketResponse]) -> None:
    if cache is None or not markets:
        return
    event_ids: list[str] = []
    for market in markets:
        sanitized = _sanitize_market_response(market)
        event_id = sanitized.get("event_id")
        if not isinstance(event_id, str):
            continue
        event_ids.append(event_id)
        set_json(
            cache,
            _market_record_cache_key(event_id),
            sanitized,
            settings.market_record_cache_ttl_seconds,
        )
        add_tag(cache, f"market:{event_id}", _market_record_cache_key(event_id))
    if not event_ids:
        return
    payload = {
        "event_ids": event_ids,
        "generated_at": datetime.now(tz=UTC).isoformat(),
    }
    set_json(cache, cache_key, payload, settings.cache_ttl_seconds)


def _decode_slug(value: str) -> str:
    return unquote_plus(value or "").strip()


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _coerce_list_of_strings(value: Any) -> list[str] | None:
    candidate = value
    if isinstance(candidate, str):
        parsed: Any = None
        try:
            parsed = json.loads(candidate)
        except ValueError:
            parsed = [item.strip() for item in candidate.split(",") if item.strip()]
        candidate = parsed
    if isinstance(candidate, list):
        result = [str(item) for item in candidate if item not in (None, "")]
        return result or None
    return None


def _coerce_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def _extract_market_metadata(extra_data: Any) -> dict[str, Any]:
    extra = _coerce_mapping(extra_data)
    if not extra:
        return {}
    gamma = _coerce_mapping(extra.get("gamma"))
    metadata: dict[str, Any] = {}

    def from_gamma(*keys: str) -> Any | None:
        if not gamma:
            return None
        for key in keys:
            if key in gamma and gamma[key]:
                return gamma[key]
        return None

    description = extra.get("description") or from_gamma("description")
    if description:
        metadata["description"] = description

    resolution_source = (
        extra.get("resolution_source") or extra.get("resolutionSource") or from_gamma("resolutionSource")
    )
    if not resolution_source and gamma and isinstance(gamma.get("events"), list):
        for event in gamma["events"]:
            data = _coerce_mapping(event)
            if data and data.get("resolutionSource"):
                resolution_source = data["resolutionSource"]
                break
    if resolution_source:
        metadata["resolution_source"] = resolution_source

    clob_pair_id = extra.get("clob_pair_id") or extra.get("clobPairId") or from_gamma("clobPairId", "pairId")
    if clob_pair_id:
        metadata["clob_pair_id"] = str(clob_pair_id)

    token_source = extra.get("clob_token_ids") or extra.get("clobTokenIds") or from_gamma("clobTokenIds", "tokenIds")
    token_ids = _coerce_list_of_strings(token_source)
    if token_ids:
        metadata["clob_token_ids"] = token_ids

    return metadata


def _apply_market_metadata(market: schemas.MarketResponse) -> None:
    metadata = _extract_market_metadata(market.extra_data)
    if not metadata:
        return
    if "description" in metadata:
        market.description = metadata["description"]
    if "resolution_source" in metadata:
        market.resolution_source = metadata["resolution_source"]
    if "clob_pair_id" in metadata:
        market.clob_pair_id = metadata["clob_pair_id"]
    if "clob_token_ids" in metadata:
        market.clob_token_ids = metadata["clob_token_ids"]


def _augment_market_models(markets: list[schemas.MarketResponse]) -> list[schemas.MarketResponse]:
    for market in markets:
        _apply_market_metadata(market)
    return markets


def _fallback_markets_by_category_slug(session: Session, slug: str, limit: int) -> list[schemas.MarketResponse]:
    """Fetch markets when canonical category labels fail by matching on slugified category."""

    normalized = slug.strip().lower()
    if not normalized:
        return []
    buffer_size = min(settings.max_page_size * 2, max(limit * 2, settings.default_page_size))
    candidates = crud.get_markets(session, limit=buffer_size, offset=0)
    matched: list[schemas.MarketResponse] = []
    for candidate in candidates:
        category_value = getattr(candidate, "category", None) or ""
        matched_slug = _slugify(str(category_value)) == normalized
        if matched_slug:
            matched.append(schemas.MarketResponse.model_validate(candidate))
            if len(matched) >= limit:
                break
    if matched:
        log_event(
            logger,
            logging.INFO,
            event="markets.category.fallback",
            message="populated category via slug fallback",
            category_slug=normalized,
            fallback_count=len(matched),
        )
    return matched


def _canonical_category_lookup(raw: str) -> tuple[str, str] | None:
    return canonical_category_from_slug(raw)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid4())
    token = set_request_id(request_id)
    start_time = time.perf_counter()
    request.state.cache_context = {"cache_hit": None, "cache_key": None, "cache_source": None}  # type: ignore[attr-defined]
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
        cache_meta = _extract_cache_metadata(request)
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
        cache_meta = _extract_cache_metadata(request)
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
        request_metrics.record(
            status_code=500,
            duration_ms=duration_ms,
            bytes_sent=0,
            cache_hit=cache_meta["cache_hit"],
        )
        reset_request_id(token)
        raise
    duration_ms = (time.perf_counter() - start_time) * 1000
    response.headers["x-request-id"] = request_id
    cache_meta = _extract_cache_metadata(request)
    bytes_sent = _estimate_response_bytes(response)
    latency_bucket = classify_latency_bucket(duration_ms)
    log_event(
        logger,
        logging.INFO,
        event="http.request.completed",
        message="request completed",
        path=request.url.path,
        method=request.method,
        status_code=response.status_code,
        duration_ms=round(duration_ms, 2),
        latency_bucket=latency_bucket,
        bytes_sent=bytes_sent,
        cache_hit=cache_meta["cache_hit"],
        cache_source=cache_meta["cache_source"],
        cache_key=cache_meta["cache_key"],
    )
    request_metrics.record(
        status_code=response.status_code,
        duration_ms=duration_ms,
        bytes_sent=bytes_sent,
        cache_hit=cache_meta["cache_hit"],
    )
    reset_request_id(token)
    return response


@app.get("/", tags=["meta"])
def read_root() -> dict[str, str]:
    cfg = get_settings()
    return {
        "service": cfg.app_name,
        "version": cfg.version,
        "environment": cfg.environment,
    }


@app.get("/health", response_model=schemas.HealthResponse, tags=["health"])
async def health_check(session: Session = Depends(get_session)) -> schemas.HealthResponse:
    return await build_health_response(session)


@app.get("/health/heartbeats", response_model=schemas.HeartbeatDashboard, tags=["health"])
def heartbeat_dashboard() -> schemas.HeartbeatDashboard:
    now = datetime.now(tz=UTC)
    worker_status = _build_worker_dashboard(now)
    api_status = _build_api_dashboard(now)
    return schemas.HeartbeatDashboard(
        generated_at=now,
        worker=worker_status,
        api=api_status,
    )


@app.post("/pricing/quote", response_model=schemas.PricingQuoteResponse, tags=["pricing"])
def pricing_quote(payload: schemas.PricingQuoteRequest) -> schemas.PricingQuoteResponse:
    """Return a pricing quote for a ZEN stake, gating on FX availability."""

    zen_usd = payload.zen_usd
    if zen_usd is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="FX price unavailable")
    engine = PricingEngine(settings)
    try:
        quote = engine.quote(Decimal(str(payload.stake_zen)), Decimal(str(zen_usd)))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    log_event(
        logger,
        logging.INFO,
        event="pricing.quote",
        message="pricing quote generated",
        stake_zen=payload.stake_zen,
        zen_usd=payload.zen_usd,
        total_monetisation=str(quote.total_monetisation),
    )
    return quote


@app.get("/pricing/fx", response_model=schemas.FxQuoteResponse, tags=["pricing"])
async def pricing_fx() -> schemas.FxQuoteResponse:
    try:
        return await fetch_fx_quote(settings)
    except httpx.HTTPError as exc:
        log_event(
            logger,
            logging.WARNING,
            event="pricing.fx.error",
            message="failed to fetch FX feed",
            error=str(exc),
        )
        return schemas.FxQuoteResponse(zen_usd=settings.fx_fallback_price, stale=True)


@app.get("/treasury/snapshots", response_model=list[schemas.TreasurySnapshot], tags=["treasury"])
def treasury_snapshots(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    market_id: Annotated[str | None, Query()] = None,
    session: Session = Depends(get_session),
) -> list[schemas.TreasurySnapshot]:
    query = session.query(models.HedgerTreasurySnapshot).order_by(models.HedgerTreasurySnapshot.created_at.desc())
    if market_id:
        query = query.filter(models.HedgerTreasurySnapshot.market_id == market_id)
    rows = query.limit(limit).all()
    return rows
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.ERROR,
            event="pricing.fx.unexpected",
            message="unexpected FX fetch error",
            error=str(exc),
        )
        return schemas.FxQuoteResponse(zen_usd=settings.fx_fallback_price, stale=True)


@app.get("/markets", response_model=list[schemas.MarketResponse], tags=["markets"])
def list_markets(
    request: Request,
    status: Annotated[str | None, Query(description="Filter markets by status")] = None,
    category: Annotated[str | None, Query(description="Filter markets by category")] = None,
    oracle: Annotated[str | None, Query(description="Filter markets by oracle address")] = None,
    search: Annotated[
        str | None,
        Query(min_length=2, max_length=200, description="Case-insensitive search over market titles"),
    ] = None,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=settings.max_page_size,
            description="Maximum number of markets to return",
        ),
    ] = settings.default_page_size,
    offset: Annotated[int, Query(ge=0, description="Offset into the result set")] = 0,
    session: Session = Depends(get_session),
) -> list[schemas.MarketResponse]:
    normalized_search = search
    if search is not None:
        normalized = search.strip().lower()
        if len(normalized) > 120:
            normalized = normalized[:120]
        normalized_search = normalized
    cache_key = markets_list_cache_key(status, category, oracle, normalized_search, limit, offset)
    cache = get_cache_client()
    log_event(
        logger,
        logging.DEBUG,
        event="markets.list.request",
        message="processing markets list request",
        cache_key=cache_key,
        status=status,
        category=category,
        oracle=oracle,
        search=normalized_search,
        limit=limit,
        offset=offset,
    )
    start = time.perf_counter()
    cache_enabled = cache is not None and _should_cache_market_list(limit, offset, normalized_search)
    if cache_enabled:
        cached_payload = get_json(cache, cache_key)
        hydrated = _hydrate_cached_market_list(cache, cached_payload)
        if hydrated is not None:
            update_cache_context(request, cache_key=cache_key, hit=True, source="markets:list")
            MARKETS_CACHE_COUNTER.labels(outcome="hit", status=status or "*", category=category or "*").inc()
            duration = (time.perf_counter() - start) * 1000
            log_event(
                logger,
                logging.INFO,
                event="markets.list.cache_hit",
                message="served markets list from cache",
                cache_hit=True,
                duration_ms=round(duration, 2),
                cache_key=cache_key,
                status=status,
                category=category,
                oracle=oracle,
                search=normalized_search,
                limit=limit,
                offset=offset,
                result_count=len(hydrated),
            )
            cached_models = _filter_markets_for_visibility(_augment_market_models(hydrated))
            return cached_models
        MARKETS_CACHE_COUNTER.labels(outcome="miss", status=status or "*", category=category or "*").inc()
        update_cache_context(request, cache_key=cache_key, hit=False, source="markets:list")
    else:
        MARKETS_CACHE_COUNTER.labels(outcome="bypass", status=status or "*", category=category or "*").inc()
        update_cache_context(request, cache_key=None, hit=False, source="markets:list")

    markets = crud.get_markets(
        session,
        status=status,
        category=category,
        oracle=oracle,
        search=normalized_search,
        limit=limit,
        offset=offset,
    )
    market_models = _augment_market_models([schemas.MarketResponse.model_validate(m) for m in markets])
    market_models = _filter_markets_for_visibility(market_models)
    if not market_models:
        log_event(
            logger,
            logging.INFO,
            event="markets.list.empty",
            message="no markets matched filters",
            status=status,
            category=category,
            oracle=oracle,
            search=search,
            limit=limit,
            offset=offset,
        )
    if cache_enabled and market_models:
        schema_tag = get_schema_tag(cache, settings.schema_version_key)
        _write_market_list_cache(cache, cache_key, market_models)
        add_tag(cache, schema_tag, cache_key)
        add_tag(cache, "markets:list", cache_key)
        add_tags(
            cache,
            [f"market:{item.event_id}" for item in market_models if item.event_id],
            cache_key,
        )
        duration = (time.perf_counter() - start) * 1000
        log_event(
            logger,
            logging.INFO,
            event="markets.list.cache_miss",
            message="cached fresh markets list",
            cache_hit=False,
            duration_ms=round(duration, 2),
            cache_key=cache_key,
            status=status,
            category=category,
            oracle=oracle,
            search=normalized_search,
            limit=limit,
            offset=offset,
            result_count=len(market_models),
        )
    else:
        duration = (time.perf_counter() - start) * 1000
        log_event(
            logger,
            logging.INFO,
            event="markets.list.response",
            message="served markets list without caching",
            cache_hit=False,
            duration_ms=round(duration, 2),
            cache_key=cache_key if cache_enabled else None,
            status=status,
            category=category,
            oracle=oracle,
            search=normalized_search,
            limit=limit,
            offset=offset,
            result_count=len(market_models),
        )
    return market_models


@app.get("/categories/{category_slug}", response_model=list[schemas.MarketResponse], tags=["markets"])
def list_markets_by_category(
    category_slug: str,
    request: Request,
    limit: Annotated[
        int,
        Query(ge=1, le=settings.max_page_size, description="Maximum number of markets to return"),
    ] = settings.default_page_size,
    offset: Annotated[int, Query(ge=0, description="Offset into the result set")] = 0,
    session: Session = Depends(get_session),
) -> list[schemas.MarketResponse]:
    start = time.perf_counter()
    cache = get_cache_client()
    log_event(
        logger,
        logging.DEBUG,
        event="markets.category.request",
        message="processing category listing",
        category_slug=category_slug,
        limit=limit,
        offset=offset,
    )
    category_value = _decode_slug(category_slug)
    lookup = _canonical_category_lookup(category_value)
    if lookup is None:
        log_event(
            logger,
            logging.WARNING,
            event="markets.category.invalid_slug",
            message="category slug not recognized",
            category_slug=category_slug,
            limit=limit,
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="category_not_found")
    category_slug_key, category_label = lookup
    cache_key = category_cache_key(category_slug_key, limit, offset)
    cache_enabled = cache is not None and _should_cache_market_list(limit, offset, None)
    if cache_enabled:
        cached_payload = get_json(cache, cache_key)
        hydrated = _hydrate_cached_market_list(cache, cached_payload)
        if hydrated is not None:
            update_cache_context(request, cache_key=cache_key, hit=True, source="markets:category")
            models_from_cache = _filter_markets_for_visibility(_augment_market_models(hydrated))
            log_event(
                logger,
                logging.INFO,
                event="markets.category.cache_hit",
                message="served category markets from cache",
                category_slug=category_slug_key,
                limit=limit,
                result_count=len(models_from_cache),
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
            return models_from_cache
        update_cache_context(request, cache_key=cache_key, hit=False, source="markets:category")
    else:
        update_cache_context(request, cache_key=None, hit=False, source="markets:category")

    trending_category = category_slug_key == "trending"
    log_event(
        logger,
        logging.DEBUG,
        event="markets.category.fetch",
        message="fetching category markets from database",
        category_slug=category_slug_key,
        category_label=category_label,
        trending=trending_category,
        limit=limit,
        offset=offset,
    )
    if trending_category:
        markets = crud.get_markets(session, limit=limit, offset=offset)
    else:
        markets = crud.get_markets(session, category=category_label, limit=limit, offset=offset)
    market_models = _filter_markets_for_visibility(
        _augment_market_models([schemas.MarketResponse.model_validate(m) for m in markets])
    )
    if not market_models and not trending_category and offset == 0:
        fallback_matches = _fallback_markets_by_category_slug(session, category_slug_key, limit)
        if fallback_matches:
            market_models = _filter_markets_for_visibility(_augment_market_models(fallback_matches))
    if not market_models:
        log_event(
            logger,
            logging.INFO,
            event="markets.category.empty",
            message="no markets available for category",
            category_slug=category_slug_key,
            limit=limit,
            offset=offset,
        )
    if cache_enabled and market_models:
        schema_tag = get_schema_tag(cache, settings.schema_version_key)
        _write_market_list_cache(cache, cache_key, market_models)
        add_tag(cache, schema_tag, cache_key)
        add_tag(cache, "markets:category", cache_key)
        add_tag(cache, f"category:{category_slug_key}", cache_key)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        log_event(
            logger,
            logging.INFO,
            event="markets.category.cache_miss",
            message="cached category markets",
            category_slug=category_slug_key,
            limit=limit,
            offset=offset,
            result_count=len(market_models),
            duration_ms=duration_ms,
        )
        update_cache_context(request, cache_key=cache_key, hit=False, source="markets:category")
    else:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        log_event(
            logger,
            logging.INFO,
            event="markets.category.cache_bypass",
            message="served category markets without cache write",
            category_slug=category_slug_key,
            limit=limit,
            offset=offset,
            result_count=len(market_models),
            duration_ms=duration_ms,
        )
        update_cache_context(request, cache_key=None, hit=False, source="markets:category")
    return market_models


@app.get("/markets/onchain", tags=["markets"])
async def list_onchain_markets():
    settings = get_settings()
    try:
        addresses = await fetch_factory_markets(settings)
    except OnChainConfigurationError as exc:
        log_event(
            logger,
            logging.WARNING,
            "markets.onchain.unconfigured",
            "on-chain configuration missing",
            error=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="onchain_not_configured") from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("failed to fetch on-chain markets")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="onchain_query_failed") from exc
    return {"markets": addresses}


@app.get("/markets/stats", response_model=list[schemas.MarketStatusBreakdown], tags=["markets"])
def market_stats(
    request: Request,
    session: Session = Depends(get_session),
) -> list[schemas.MarketStatusBreakdown]:
    start = time.perf_counter()
    cache = get_cache_client()
    cache_available = cache is not None
    log_event(logger, logging.DEBUG, "markets.stats.request", "processing market stats request")
    cached = get_json(cache, MARKETS_STATS_KEY)
    if cached is not None:
        update_cache_context(request, cache_key=MARKETS_STATS_KEY, hit=True, source="markets:stats")
        duration = (time.perf_counter() - start) * 1000
        log_event(
            logger,
            logging.INFO,
            event="markets.stats.cache_hit",
            message="served market stats from cache",
            cache_hit=True,
            duration_ms=round(duration, 2),
            result_count=len(cached),
        )
        return [schemas.MarketStatusBreakdown.model_validate(item) for item in cached]
    stats = crud.get_market_stats(session)
    payload = [jsonable_encoder(item) for item in stats]
    duration = (time.perf_counter() - start) * 1000
    if cache_available:
        schema_tag = get_schema_tag(cache, settings.schema_version_key)
        set_json(cache, MARKETS_STATS_KEY, payload, settings.cache_ttl_seconds)
        add_tag(cache, schema_tag, MARKETS_STATS_KEY)
        add_tag(cache, "markets:stats", MARKETS_STATS_KEY)
        log_event(
            logger,
            logging.INFO,
            event="markets.stats.cache_miss",
            message="cached fresh market stats",
            cache_hit=False,
            duration_ms=round(duration, 2),
            result_count=len(stats),
        )
        cache_key = MARKETS_STATS_KEY
    else:
        log_event(
            logger,
            logging.INFO,
            event="markets.stats.cache_bypass",
            message="served market stats without cache",
            cache_hit=False,
            duration_ms=round(duration, 2),
            result_count=len(stats),
        )
        cache_key = None
    update_cache_context(request, cache_key=cache_key, hit=False, source="markets:stats")
    return stats


@app.get("/markets/suggest", response_model=list[schemas.MarketResponse], tags=["markets"])
def suggest_markets(
    request: Request,
    q: Annotated[str, Query(min_length=2, max_length=200, description="Search term for suggestions")],
    limit: Annotated[int, Query(ge=1, le=25, description="Maximum number of suggestions to return")] = 5,
    session: Session = Depends(get_session),
) -> list[schemas.MarketResponse]:
    start = time.perf_counter()
    cache = get_cache_client()
    cache_available = cache is not None
    log_event(
        logger,
        logging.DEBUG,
        event="markets.suggest.request",
        message="processing suggestion request",
        query=q,
        limit=limit,
    )
    normalized_query = q.strip()
    cache_key = suggest_cache_key(normalized_query, limit)
    cached = get_json(cache, cache_key)
    if cached is not None:
        update_cache_context(request, cache_key=cache_key, hit=True, source="markets:suggest")
        models_from_cache = [schemas.MarketResponse.model_validate(item) for item in cached]
        _augment_market_models(models_from_cache)
        log_event(
            logger,
            logging.INFO,
            event="markets.suggest.cache_hit",
            message="served suggestions from cache",
            query=normalized_query,
            limit=limit,
            result_count=len(models_from_cache),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return models_from_cache

    results = crud.search_markets(session, normalized_query, limit)
    market_models = [schemas.MarketResponse.model_validate(m) for m in results]
    filtered = _filter_markets_for_visibility(_augment_market_models(market_models))
    if not filtered:
        log_event(
            logger,
            logging.INFO,
            event="markets.suggest.empty",
            message="no suggestions found for query",
            query=normalized_query,
            limit=limit,
        )
    payload = [item.model_dump(mode="json") for item in filtered]
    if cache_available:
        schema_tag = get_schema_tag(cache, settings.schema_version_key)
        set_json(cache, cache_key, payload, settings.cache_ttl_seconds)
        add_tag(cache, schema_tag, cache_key)
        add_tag(cache, "markets:suggest", cache_key)
        log_event(
            logger,
            logging.INFO,
            event="markets.suggest.cache_miss",
            message="cached suggestion results",
            query=normalized_query,
            limit=limit,
            result_count=len(filtered),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
    else:
        log_event(
            logger,
            logging.INFO,
            event="markets.suggest.cache_bypass",
            message="served suggestions without cache",
            query=normalized_query,
            limit=limit,
            result_count=len(filtered),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
    update_cache_context(request, cache_key=cache_key if cache_available else None, hit=False, source="markets:suggest")
    return filtered


@app.get("/resolution/{condition_id_hex}", response_model=schemas.ResolutionSummary, tags=["markets"])
def read_resolution(
    condition_id_hex: str,
    request: Request,
    session: Session = Depends(get_session),
) -> schemas.ResolutionSummary:
    start = time.perf_counter()
    cache = get_cache_client()
    cache_available = cache is not None
    log_event(
        logger,
        logging.DEBUG,
        event="markets.resolution.request",
        message="fetching resolution summary",
        condition_id=condition_id_hex,
    )
    normalized_condition = condition_id_hex.lower()
    cache_key = resolution_cache_key(normalized_condition)
    cached = get_json(cache, cache_key)
    if cached is not None:
        update_cache_context(request, cache_key=cache_key, hit=True, source="markets:resolution")
        summary = schemas.ResolutionSummary.model_validate(cached)
        log_event(
            logger,
            logging.INFO,
            event="markets.resolution.cache_hit",
            message="served resolution summary from cache",
            condition_id=normalized_condition,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return summary

    market = crud.get_market_by_condition_id(session, normalized_condition)
    record = crud.get_resolution_by_condition_id(session, normalized_condition)

    summary: dict[str, Any] | None = None
    if record is not None:
        summary = {
            "source": record.source,
            "conditionId": record.condition_id,
            "resolved": record.resolved,
            "outcomes": record.outcomes or [],
            "payouts": record.payouts or [],
            "winners": record.winners or [],
            "checkedAt": record.checked_at,
            "oracle": record.oracle,
            "questionId": record.question_id,
            "transactionHash": record.transaction_hash,
            "blockNumber": record.block_number,
            "blockTimestamp": record.block_timestamp,
        }
    elif goldsky_client is not None:
        try:
            summary = goldsky_client.resolution_summary(
                normalized_condition,
                market.outcomes if market and market.outcomes else None,
                len(market.outcomes) if market and market.outcomes else None,
            )
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                logger,
                logging.WARNING,
                event="markets.resolution.goldsky_failed",
                message="failed to fetch resolution from goldsky",
                condition_id=normalized_condition,
                error=str(exc),
            )
        else:
            if summary:
                log_event(
                    logger,
                    logging.INFO,
                    event="markets.resolution.goldsky",
                    message="served resolution summary via goldsky fallback",
                    condition_id=normalized_condition,
                )

    if summary is None:
        log_event(
            logger,
            logging.WARNING,
            event="markets.resolution.missing",
            message="resolution not found",
            condition_id=normalized_condition,
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resolution_not_found")

    if market:
        summary.update(
            {
                "marketId": market.id,
                "eventId": market.event_id,
                "title": market.title,
                "slug": market.slug,
                "outcomes": market.outcomes or summary.get("outcomes", []),
            }
        )

    summary_model = schemas.ResolutionSummary.model_validate(summary)
    if cache_available:
        cache_payload = summary_model.model_dump(mode="json", by_alias=True)
        if summary_model.checked_at is not None:
            cache_payload["checkedAt"] = summary_model.checked_at.isoformat()
        if summary_model.block_timestamp is not None:
            cache_payload["blockTimestamp"] = summary_model.block_timestamp.isoformat()
        schema_tag = get_schema_tag(cache, settings.schema_version_key)
        set_json(cache, cache_key, cache_payload, settings.cache_ttl_seconds)
        add_tag(cache, schema_tag, cache_key)
        add_tag(cache, f"resolution:{normalized_condition}", cache_key)
        log_event(
            logger,
            logging.INFO,
            event="markets.resolution.cache_miss",
            message="cached resolution summary",
            condition_id=normalized_condition,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
    else:
        log_event(
            logger,
            logging.INFO,
            event="markets.resolution.cache_bypass",
            message="served resolution without cache",
            condition_id=normalized_condition,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
    update_cache_context(
        request, cache_key=cache_key if cache_available else None, hit=False, source="markets:resolution"
    )
    return summary_model


@app.get("/markets/{event_id}", response_model=schemas.MarketResponse, tags=["markets"])
def read_market(
    event_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> schemas.MarketResponse:
    cache_key = _market_detail_cache_key(event_id)
    cache = get_cache_client()
    cache_available = cache is not None
    log_event(
        logger,
        logging.DEBUG,
        event="markets.detail.request",
        message="processing market detail request",
        event_id=event_id,
        cache_key=cache_key,
    )
    start = time.perf_counter()
    cached = get_json(cache, cache_key)
    if cached is not None:
        duration = (time.perf_counter() - start) * 1000
        model = schemas.MarketResponse.model_validate(cached)
        _apply_market_metadata(model)
        update_cache_context(request, cache_key=cache_key, hit=True, source="markets:detail")
        log_event(
            logger,
            logging.INFO,
            event="markets.detail.cache_hit",
            message="served market detail from cache",
            cache_hit=True,
            duration_ms=round(duration, 2),
            event_id=event_id,
            result_count=1,
        )
        return model

    market = crud.get_market_by_event_id(session, event_id)
    if not market:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="market_not_found")
    response = schemas.MarketResponse.model_validate(market)
    _apply_market_metadata(response)
    duration = (time.perf_counter() - start) * 1000
    if cache_available:
        schema_tag = get_schema_tag(cache, settings.schema_version_key)
        set_json(cache, cache_key, response.model_dump(mode="json"), settings.cache_ttl_seconds)
        add_tag(cache, schema_tag, cache_key)
        add_tag(cache, f"market:{event_id}", cache_key)
        log_event(
            logger,
            logging.INFO,
            event="markets.detail.cache_miss",
            message="cached fresh market detail",
            cache_hit=False,
            duration_ms=round(duration, 2),
            event_id=event_id,
            result_count=1,
        )
    else:
        log_event(
            logger,
            logging.INFO,
            event="markets.detail.cache_bypass",
            message="served market detail without cache",
            cache_hit=False,
            duration_ms=round(duration, 2),
            event_id=event_id,
            result_count=1,
        )
    update_cache_context(request, cache_key=cache_key if cache_available else None, hit=False, source="markets:detail")
    return response


@app.post("/markets", response_model=schemas.MarketResponse, tags=["markets"], status_code=status.HTTP_201_CREATED)
def upsert_market(market_in: schemas.MarketCreate, session: Session = Depends(get_session)) -> schemas.MarketResponse:
    start = time.perf_counter()
    log_event(
        logger,
        logging.INFO,
        event="markets.create.request",
        message="creating or updating market",
        event_id=market_in.event_id,
        category=market_in.category,
        oracle=market_in.oracle,
    )
    market = crud.create_or_update_market(session, market_in)
    session.flush()
    _invalidate_market_cache(market.event_id, getattr(market, "condition_id", None))
    duration = (time.perf_counter() - start) * 1000
    log_event(
        logger,
        logging.INFO,
        event="markets.create.success",
        message="market persisted",
        event_id=market.event_id,
        category=market.category,
        duration_ms=round(duration, 2),
    )
    response = schemas.MarketResponse.model_validate(market)
    _apply_market_metadata(response)
    return response


@app.patch("/markets/{event_id}", response_model=schemas.MarketResponse, tags=["markets"])
def update_market(
    event_id: str, update: schemas.MarketUpdate, session: Session = Depends(get_session)
) -> schemas.MarketResponse:
    market = crud.get_market_by_event_id(session, event_id)
    if not market:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="market_not_found")
    start = time.perf_counter()
    log_event(
        logger,
        logging.INFO,
        event="markets.update.request",
        message="patching market",
        event_id=event_id,
        fields=list(update.model_dump(exclude_unset=True).keys()),
    )
    crud.patch_market(session, market, update)
    session.flush()
    _invalidate_market_cache(event_id, getattr(market, "condition_id", None))
    duration = (time.perf_counter() - start) * 1000
    log_event(
        logger,
        logging.INFO,
        event="markets.update.success",
        message="market updated",
        event_id=event_id,
        duration_ms=round(duration, 2),
    )
    response = schemas.MarketResponse.model_validate(market)
    _apply_market_metadata(response)
    return response


def _market_detail_cache_key(event_id: str) -> str:
    return f"{MARKET_DETAIL_PREFIX}:{event_id}"


def _invalidate_market_cache(event_id: str | None = None, condition_id: str | None = None) -> None:
    cache = get_cache_client()
    log_event(
        logger,
        logging.DEBUG,
        event="markets.cache.invalidate",
        message="invalidating markets cache",
        event_id=event_id,
        condition_id=condition_id,
    )
    invalidate_tag(cache, "markets:list")
    invalidate_tag(cache, "markets:stats")
    invalidate_tag(cache, "markets:category")
    invalidate_tag(cache, "markets:tag")
    invalidate_tag(cache, "markets:suggest")
    if event_id:
        invalidate_tag(cache, f"market:{event_id}")
    if condition_id:
        invalidate_tag(cache, f"resolution:{condition_id.lower()}")
