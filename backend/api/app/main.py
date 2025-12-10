from __future__ import annotations

import json
import logging
import random
import re
import time
from collections.abc import Iterable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from inspect import isawaitable
from secrets import token_hex
from threading import Event, Lock, Thread
from typing import Annotated, Any, cast
from urllib.parse import unquote_plus
from uuid import uuid4

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram
from prometheus_fastapi_instrumentator import Instrumentator
from py_clob_client.client import ClobClient
from pydantic import SecretStr
from redis import Redis
from redis.exceptions import RedisError
from shared import models as shared_models
from shared import repository as shared_repository
from shared.cache import add_tag, add_tags, get_client, get_json, get_schema_tag, invalidate_tag, set_json
from shared.cache_keys import (
    category_cache_key,
    group_cache_key,
    markets_list_cache_key,
    proof_receipt_cache_key,
    resolution_cache_key,
    suggest_cache_key,
)
from shared.categories import canonical_category_from_slug
from shared.env_presets import get_preset, resolve_mode
from shared.indexers import GoldskyClient
from shared.logging import log_event, reset_request_id, set_request_id, start_heartbeat_logger
from shared.migrations import get_current_revision
from shared.onchain import OnChainConfigurationError
from shared.onchain.client import load_account
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware
from web3 import Web3

from app import crud, models, schemas
from app.config import Settings, get_settings
from app.database import get_session, run_migrations, session_scope
from app.health import build_health_response
from app.logging_config import setup_logging
from app.metrics import RequestMetrics, classify_latency_bucket, update_cache_context
from app.onchain import fetch_factory_markets
from app.pricing import PricingEngine, fetch_fx_price_sync, fetch_fx_quote
from app.rate_limit import RateLimiter, RateLimitMiddleware
from app.security import SecurityHeadersMiddleware

setup_logging("reveal_market.api")

settings = get_settings()
_sanitized_config = {
    k: v
    for k, v in settings.model_dump().items()
    if not any(secret in k for secret in ["key", "private", "secret", "password"])
}
logger = logging.getLogger("reveal_market.api")
logger.info("service configuration", extra={"event": "service.config", "config": _sanitized_config})
mode_env = resolve_mode()
is_production = mode_env == "prod" or settings.environment.lower() == "production"
preset = get_preset()
TRENDING_MIN_LIQUIDITY = 0
TRENDING_MIN_VOLUME_24H = 0
TRENDING_MIN_ORDERBOOK = 0
TRENDING_MIN_TRADES = 0
TRENDING_MIN_SCORE = 0.0
logger.info(
    "service environment resolved",
    extra={
        "event": "service.env",
        "settings_environment": settings.environment,
        "mode_env": mode_env or None,
        "is_production": is_production,
    },
)


def _current_settings() -> Settings:
    return settings


def _coerce_preset_list(value: object) -> list[str]:
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return [str(item) for item in value]
    return []


instrumentator = Instrumentator()
cache_client: Redis | None = None
_cache_lock = Lock()
_heartbeat_stop_event: Event | None = None
_metrics_stop_event: Event | None = None
_cache_refresh_stop_event: Event | None = None
_quote_sweeper_stop_event: Event | None = None
request_metrics = RequestMetrics(settings.slow_request_threshold_ms)
goldsky_client: GoldskyClient | None = None

REQUEST_LATENCY = Histogram(
    "api_request_latency_seconds",
    "Latency of HTTP requests",
    ["method", "path", "status_code"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)

MARKETS_STATS_KEY = "v1:markets:stats"
MARKET_DETAIL_PREFIX = "v1:markets:detail"

MARKETS_CACHE_COUNTER = Counter(
    "markets_cache_requests_total",
    "Cache hits and misses for /markets",
    ["outcome", "status", "category"],
)
PRICING_COUNTER = Counter(
    "pricing_quote_events_total",
    "Pricing quote lifecycle events",
    ["event", "result"],
)
MARKET_DETAIL_CACHE_COUNTER = Counter(
    "markets_detail_cache_requests_total",
    "Cache hits and misses for /markets/{event_id}",
    ["outcome"],
)
RESOLUTION_CACHE_COUNTER = Counter(
    "markets_resolution_cache_requests_total",
    "Cache hits and misses for /resolution/{condition_id}",
    ["outcome"],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _heartbeat_stop_event, _metrics_stop_event, _cache_refresh_stop_event, _quote_sweeper_stop_event
    run_migrations()
    _record_schema_revision_tag()
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
    if _quote_sweeper_stop_event is None:
        _quote_sweeper_stop_event = _start_quote_sweeper()
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
    if _quote_sweeper_stop_event is not None:
        _quote_sweeper_stop_event.set()
        _quote_sweeper_stop_event = None


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
# Use mode presets for host/CORS defaults so deployments don't depend on env quirks.
allowed_hosts = _coerce_preset_list(preset.get("api_allowed_hosts"))
if allowed_hosts and allowed_hosts != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

# Expand CORS origins in non-production environments to include local dev hosts
# so browser clients hitting api.localhost/http://localhost work without manual overrides.
cors_origins = _coerce_preset_list(preset.get("api_cors_origins"))
expected_prod_origins = set(cors_origins if is_production else _coerce_preset_list(preset.get("api_cors_origins")))
local_origins = set(_coerce_preset_list(preset.get("api_cors_origins"))) if not is_production else set()
if not is_production:
    cors_origins = list(local_origins)
if cors_origins and cors_origins != ["*"] and is_production:
    missing_cors = sorted(origin for origin in expected_prod_origins if origin not in cors_origins)
    if missing_cors:
        log_event(
            logger,
            logging.WARNING,
            event="cors.origins.missing",
            message="RM_CORS_ALLOW_ORIGINS missing expected frontend origins",
            missing=missing_cors,
        )
# Keep settings in sync with the middleware payload so /health reflects reality.
settings.cors_allow_origins = cors_origins

_connect_sources = {"'self'"}
for origin in cors_origins:
    sanitized = origin.rstrip("/")
    if sanitized:
        _connect_sources.add(sanitized)
        if sanitized.startswith("http://") or sanitized.startswith("https://"):
            ws_variant = sanitized.replace("http://", "ws://").replace("https://", "wss://")
            _connect_sources.add(ws_variant)
# Include preset streamer hosts explicitly so FX/connect-src stay aligned even if CORS is narrowed.
for preset_origin in (preset.get("streamer_public"), preset.get("streamer_internal")):
    if isinstance(preset_origin, str) and preset_origin:
        sanitized = preset_origin.rstrip("/")
        _connect_sources.add(sanitized)
        if sanitized.startswith("http://") or sanitized.startswith("https://"):
            ws_variant = sanitized.replace("http://", "ws://").replace("https://", "wss://")
            _connect_sources.add(ws_variant)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)

if settings.enable_security_headers:
    connect_src = " ".join(sorted(_connect_sources))
    api_csp = (
        f"default-src 'none'; frame-ancestors 'none'; form-action 'none'; base-uri 'none'; connect-src {connect_src};"
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


def _log_cors_warnings(origins: list[str], scope: str) -> None:
    """Emit a warning when CORS is effectively wide-open so ops can tighten it."""

    if not origins or origins == ["*"]:
        log_event(
            logger,
            logging.WARNING,
            event="cors.unbounded",
            message="CORS allow_origins is wildcard; set explicit origins for production",
            scope=scope,
        )


_log_cors_warnings(settings.cors_allow_origins, scope="api")


def _strip_0x(value: str | None) -> str:
    if not value:
        return ""
    return value[2:] if value.startswith("0x") else value


def _to_wei_amount(stake_zen: float | Decimal) -> int:
    quantized = (Decimal(str(stake_zen)) * Decimal("1e18")).to_integral_value(rounding=ROUND_DOWN)
    return int(quantized)


def _scale_fx_value(zen_usd: float | Decimal) -> int:
    quantized = (Decimal(str(zen_usd)) * Decimal("1e8")).to_integral_value(rounding=ROUND_DOWN)
    return int(quantized)


def _build_quote_digest(
    chain_id: int,
    market_address: str,
    wallet_address: str,
    outcome_id: int,
    stake_wei: int,
    zen_usd_scaled: int,
    expiry_ts: int,
    quote_id_hex: str,
) -> bytes:
    # Mirror the Solidity digest checked by RevealMarket.commitWithQuote:
    # keccak256("QUOTE_V1", chainid, market, expectedUser, outcomeId, stakeWei, fxScaled1e8, expiry, quoteId)
    quote_bytes = bytes.fromhex(_strip_0x(quote_id_hex))
    if len(quote_bytes) != 32:
        raise ValueError("quote_id must be 32 bytes hex")
    return Web3.solidity_keccak(
        [
            "string",
            "uint256",
            "address",
            "address",
            "uint256",
            "uint256",
            "uint256",
            "uint256",
            "bytes32",
        ],
        [
            "QUOTE_V1",
            int(chain_id),
            Web3.to_checksum_address(market_address),
            Web3.to_checksum_address(wallet_address),
            int(outcome_id),
            int(stake_wei),
            int(zen_usd_scaled),
            int(expiry_ts),
            quote_bytes,
        ],
    )


def _derive_winners_from_payouts(payouts: list[int] | None, outcomes: list[str] | None) -> list[dict[str, Any]]:
    winners: list[dict[str, Any]] = []
    if not payouts:
        return winners
    valid_payouts: list[tuple[int, int]] = []
    for index, raw in enumerate(payouts):
        try:
            value = int(raw)
        except (TypeError, ValueError):
            logger.debug("Skipping payout that cannot be coerced to int", exc_info=True)
            value = None
        if value is None:
            continue
        valid_payouts.append((index, value))
    if not valid_payouts:
        return winners
    max_value = max(value for _, value in valid_payouts)
    if max_value <= 0:
        return winners
    labels = outcomes or []
    for index, value in valid_payouts:
        if value == max_value:
            label = labels[index] if index < len(labels) else None
            winners.append({"index": index, "label": label, "payout": value})
    return winners


def _build_resolution_summary_from_record(
    record: models.Resolution,
    market: models.Market | None = None,
    market_outcomes: list[str] | None = None,
) -> schemas.ResolutionSummary:
    outcomes = market_outcomes or []
    payouts = record.payouts or []
    winners = record.winners or _derive_winners_from_payouts(payouts, outcomes)
    winning_outcome_id = record.winning_outcome_id
    if winning_outcome_id is None and winners:
        winning_outcome_id = winners[0].get("index")
    checked_at = record.checked_at or record.created_at
    payload: dict[str, object] = {
        "source": record.source,
        "condition_id": record.condition_id,
        "resolved": record.resolved,
        "outcomes": outcomes or [],
        "payouts": payouts or [],
        "winners": winners or [],
        "checked_at": checked_at,
        "market_id": getattr(record, "market_id", None),
        "event_id": record.event_id or (market.event_id if market else None),
        "title": market.title if market else None,
        "slug": market.slug if market else None,
        "oracle": record.oracle or (market.oracle if market else None),
        "question_id": record.question_id,
        "transaction_hash": record.transaction_hash,
        "block_number": record.block_number,
        "block_timestamp": record.block_timestamp,
        "winning_outcome_id": winning_outcome_id,
        "rake_bps": record.rake_bps if record.rake_bps is not None else getattr(market, "rake_bps", None),
        "request_id": record.request_id,
        "created_at": getattr(record, "created_at", None),
        "updated_at": getattr(record, "updated_at", None),
    }
    return schemas.ResolutionSummary.model_validate(payload)


def _build_market_caps() -> schemas.MarketCaps:
    return schemas.MarketCaps(
        max_stake_zen=Decimal(str(settings.max_stake_zen)),
        max_user_stake_per_market_zen=Decimal(str(settings.max_user_stake_per_market_zen)),
        max_market_stake_zen=Decimal(str(settings.max_market_stake_zen)),
    )


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
    if isawaitable(raw):
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    elif not isinstance(raw, str):
        return None
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


def _record_schema_revision_tag() -> None:
    """Persist the current Alembic revision to DB and Redis for cache tagging/health."""

    cache = get_cache_client()
    try:
        revision = get_current_revision(settings.database_url)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="schema.revision.resolve_failed",
            message="failed to resolve schema revision after migrations",
            error=str(exc),
        )
        return
    if revision is None:
        log_event(
            logger,
            logging.WARNING,
            event="schema.revision.missing",
            message="schema revision missing after migrations",
        )
        return
    try:
        with session_scope() as session:
            shared_repository.record_schema_version(session, revision, key=settings.schema_version_key)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="schema.revision.persist_failed",
            message="failed to record schema revision",
            revision=revision,
            error=str(exc),
        )
    if cache is not None:
        try:
            cache.set(settings.schema_version_key, revision)
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                logger,
                logging.WARNING,
                event="schema.revision.cache_failed",
                message="failed to write schema revision cache tag",
                revision=revision,
                error=str(exc),
            )


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
    lock_key = "lock:markets_cache:hydrate"
    lock_acquired = False
    lock_ttl = max(30, settings.cache_ttl_seconds)
    if cache is not None:
        try:
            lock_acquired = bool(cache.set(lock_key, "1", ex=lock_ttl, nx=True))
        except RedisError:
            lock_acquired = False
    if cache is not None and not lock_acquired:
        summary["status"] = "skipped"
        summary["reason"] = "hydrate_in_progress"
        return summary
    with session_scope() as session:
        records = crud.get_markets(session, limit=hydrated_limit, offset=0)
        market_models = _filter_markets_for_visibility(
            _enrich_market_models(session, [schemas.MarketResponse.model_validate(m) for m in records])
        )
    if not market_models:
        if cache is not None and lock_acquired:
            cache.delete(lock_key)
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
    if cache is not None and lock_acquired:
        try:
            cache.delete(lock_key)
        except RedisError:
            pass
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
        jitter = min(interval * 0.2, 30)
        wait_seconds = interval + _RNG.uniform(-jitter, jitter)
        stop_event.wait(max(1, wait_seconds))


def _quote_sweeper_loop(stop_event: Event, *, run_once: bool = False) -> None:
    interval = max(15, settings.quote_expiry_sweep_interval_seconds)
    while not stop_event.is_set():
        try:
            with session_scope() as session:
                expired = shared_repository.expire_stale_quotes(session)
                session.flush()
                if expired:
                    PRICING_COUNTER.labels(event="sweep", result="expired").inc(expired)
                    log_event(
                        logger,
                        logging.INFO,
                        event="pricing.quote.sweep",
                        message="expired stale quotes",
                        expired=expired,
                        ttl_seconds=settings.quote_store_ttl_seconds,
                    )
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                logger,
                logging.WARNING,
                event="pricing.quote.sweep_error",
                message="quote expiry sweep failed",
                error=str(exc),
            )
        if run_once:
            break
        stop_event.wait(interval)


def _start_quote_sweeper() -> Event:
    stop_event = Event()
    thread = Thread(target=_quote_sweeper_loop, args=(stop_event,), daemon=True)
    thread.start()
    log_event(
        logger,
        logging.INFO,
        event="pricing.quote.sweep.start",
        message="started quote expiry sweeper",
        interval_seconds=settings.quote_expiry_sweep_interval_seconds,
    )
    return stop_event


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


def _resolved_cache_ttl(status: str | None, resolved_at: datetime | None) -> int:
    """Compute cache TTL; resolved markets expire 12 hours after resolution."""

    resolved = resolved_at
    if isinstance(resolved_at, str):
        try:
            resolved = datetime.fromisoformat(resolved_at.replace("Z", "+00:00"))
        except ValueError:
            resolved = None
    if status and status.lower() in {"settled", "cancelled"} and isinstance(resolved, datetime):
        delta = (resolved - datetime.now(tz=UTC)) + timedelta(hours=12)
        seconds = int(delta.total_seconds())
        if seconds <= 0:
            return 0
        return min(seconds, settings.market_record_cache_ttl_seconds)
    return settings.market_record_cache_ttl_seconds


def _should_cache_market_list(limit: int, offset: int, search_query: str | None) -> bool:
    if offset != 0:
        return False
    if search_query:
        return False
    return limit <= settings.cacheable_market_limit


def _sanitize_market_response(market: schemas.MarketResponse) -> dict[str, Any]:
    payload = market.model_dump(mode="json")
    # `extra_data` removed; payload is already normalized
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
        condition_id = sanitized.get("condition_id")
        record_key = _market_record_cache_key(event_id)
        ttl_seconds = _resolved_cache_ttl(sanitized.get("status"), sanitized.get("resolved_at"))
        if ttl_seconds > 0:
            set_json(cache, record_key, sanitized, ttl_seconds)
            add_tag(cache, f"market:{event_id}", record_key)
            if isinstance(condition_id, str):
                add_tag(cache, f"resolution:{condition_id.lower()}", record_key)
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


def _apply_market_caps(market: schemas.MarketResponse) -> None:
    if getattr(market, "caps", None) is None:
        market.caps = _build_market_caps()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        numeric = float(value)
        if numeric != numeric:  # NaN guard
            return None
        return numeric
    except (TypeError, ValueError):
        return None


def _parse_group_threshold(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if isinstance(value, str):
        cleaned = value.strip().lower().replace(",", "").replace("$", "")
        cleaned = cleaned.lstrip("><= ")
        multiplier = 1.0
        if cleaned.endswith("k"):
            multiplier = 1_000.0
            cleaned = cleaned[:-1]
        elif cleaned.endswith("m"):
            multiplier = 1_000_000.0
            cleaned = cleaned[:-1]
        elif cleaned.endswith("b"):
            multiplier = 1_000_000_000.0
            cleaned = cleaned[:-1]
        match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
        if not match:
            return None
        try:
            return float(match.group(0)) * multiplier
        except (TypeError, ValueError, OverflowError):
            return None
    return None


def _parse_threshold_from_title(title: str | None) -> float | None:
    if not title:
        return None
    cleaned = title.strip().lower().replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    suffix = cleaned[match.end() :].strip()
    multiplier = 1.0
    if suffix.startswith("k"):
        multiplier = 1_000.0
    elif suffix.startswith("m"):
        multiplier = 1_000_000.0
    elif suffix.startswith("b"):
        multiplier = 1_000_000_000.0
    try:
        return float(match.group(0)) * multiplier
    except (TypeError, ValueError, OverflowError):
        return None


def _normalize_datetime(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _load_group_aggregates(session: Session, slugs: set[str]) -> dict[str, dict[str, float | None]]:
    if not slugs:
        return {}
    stmt = (
        select(
            models.Market.group_slug,
            func.sum(models.Market.volume_24h_usd),
            func.sum(models.Market.liquidity_usd),
        )
        .where(models.Market.group_slug.in_(list(slugs)))
        .group_by(models.Market.group_slug)
    )
    aggregates: dict[str, dict[str, float | None]] = {}
    for slug, volume_sum, liquidity_sum in session.execute(stmt):
        if not slug:
            continue
        aggregates[slug] = {
            "volume_24h_usd": _safe_float(volume_sum),
            "liquidity_usd": _safe_float(liquidity_sum),
        }
    return aggregates


def _get_group_siblings(session: Session, group_slug: str) -> list[schemas.MarketSibling]:
    normalized = (group_slug or "").strip().lower()
    if not normalized:
        return []
    cache = get_cache_client()
    cache_key = group_cache_key(normalized)
    cached = get_json(cache, cache_key)
    if cached is not None:
        try:
            return [schemas.MarketSibling.model_validate(item) for item in cached]
        except Exception as exc:  # pragma: no cover - defensive cache parse
            log_event(
                logger,
                logging.DEBUG,
                event="markets.group.cache_parse_failed",
                message="failed to parse cached siblings payload",
                group_slug=normalized,
                error=str(exc),
            )

    markets = session.execute(select(models.Market).where(models.Market.group_slug == normalized)).scalars().all()
    if not markets:
        return []
    ids = [m.id for m in markets if m.id is not None]
    outcome_map: dict[int, list[models.MarketOutcome]] = {}
    if ids:
        outcome_rows = session.execute(
            select(models.MarketOutcome)
            .where(models.MarketOutcome.market_id.in_(ids))
            .order_by(models.MarketOutcome.market_id, models.MarketOutcome.outcome_id)
        ).scalars()
        for row in outcome_rows:
            outcome_map.setdefault(row.market_id, []).append(row)
    meta_map: dict[int, models.MarketGammaMetadata] = {}
    if ids:
        meta_rows = session.execute(
            select(models.MarketGammaMetadata).where(models.MarketGammaMetadata.market_id.in_(ids))
        ).scalars()
        meta_map = {row.market_id: row for row in meta_rows}

    siblings_raw: list[tuple[schemas.MarketSibling, datetime | None, str | None, float | None, float | None]] = []
    for record in markets:
        meta = meta_map.get(record.id)
        outcomes = outcome_map.get(getattr(record, "id", -1), [])
        prices_raw = [float(row.price) if row.price is not None else None for row in outcomes]
        threshold = _parse_group_threshold(getattr(meta, "group_item_threshold", None) if meta else None)
        title_value = getattr(meta, "group_item_title", None) if meta else None
        threshold = threshold or _parse_threshold_from_title(title_value)
        position = getattr(record, "group_position", None)
        if position is None and threshold is not None:
            try:
                position = int(threshold)
            except (TypeError, ValueError, OverflowError):
                position = None
        outcome_prices: list[float] | None = None
        if any(p is not None for p in prices_raw):
            outcome_prices = [float(p) for p in prices_raw if p is not None]

        sibling = schemas.MarketSibling(
            event_id=record.event_id,
            title=record.title,
            group_item_title=title_value,
            group_item_threshold=threshold,
            group_position=position,
            outcome_prices=outcome_prices,
            liquidity_usd=_safe_float(record.liquidity_usd),
            volume_24h_usd=_safe_float(record.volume_24h_usd),
        )
        siblings_raw.append(
            (
                sibling,
                _normalize_datetime(getattr(record, "closes_at", None)),
                getattr(record, "slug", None) or sibling.event_id,
                position,
                threshold,
            )
        )

    def _sort_key(item: tuple[schemas.MarketSibling, datetime | None, str | None, float | None, float | None]):
        sibling, closes_at, slug_value, position_value, threshold_value = item
        primary = (
            position_value
            if position_value is not None
            else threshold_value
            if threshold_value is not None
            else float("inf")
        )
        close_ts = closes_at or datetime.max.replace(tzinfo=UTC)
        return primary, close_ts, slug_value or sibling.event_id

    siblings_raw.sort(key=_sort_key)
    siblings = [item[0] for item in siblings_raw]
    if cache is not None and siblings:
        try:
            schema_tag = get_schema_tag(cache, settings.schema_version_key)
            set_json(cache, cache_key, [sib.model_dump(mode="json") for sib in siblings], settings.cache_ttl_seconds)
            add_tag(cache, schema_tag, cache_key)
            add_tag(cache, "markets:group", cache_key)
            add_tag(cache, f"group:{normalized}", cache_key)
        except Exception as exc:  # pragma: no cover - cache best-effort
            log_event(
                logger,
                logging.DEBUG,
                event="markets.group.cache_write_failed",
                message="failed to persist siblings cache payload",
                group_slug=normalized,
                error=str(exc),
            )
    return siblings


def _sum_sibling_volume(siblings: list[schemas.MarketSibling]) -> float | None:
    total = 0.0
    any_value = False
    for sibling in siblings:
        value = _safe_float(getattr(sibling, "volume_24h_usd", None))
        if value is not None:
            total += value
            any_value = True
    return total if any_value else None


def _sum_sibling_liquidity(siblings: list[schemas.MarketSibling]) -> float | None:
    total = 0.0
    any_value = False
    for sibling in siblings:
        value = _safe_float(getattr(sibling, "liquidity_usd", None))
        if value is not None:
            total += value
            any_value = True
    return total if any_value else None


def _coalesce_grouped_markets(markets: list[schemas.MarketResponse]) -> list[schemas.MarketResponse]:
    grouped: dict[str, schemas.MarketResponse] = {}
    standalone: list[schemas.MarketResponse] = []

    def _prefer_candidate(candidate: schemas.MarketResponse, incumbent: schemas.MarketResponse) -> bool:
        cand_volume = _safe_float(getattr(candidate, "volume_24h_usd", None)) or 0.0
        inc_volume = _safe_float(getattr(incumbent, "volume_24h_usd", None)) or 0.0
        if cand_volume > inc_volume:
            return True
        if cand_volume < inc_volume:
            return False
        cand_pos_raw = getattr(candidate, "group_position", None)
        inc_pos_raw = getattr(incumbent, "group_position", None)
        cand_pos = _safe_float(cand_pos_raw)
        inc_pos = _safe_float(inc_pos_raw)
        if cand_pos is not None and inc_pos is not None:
            if cand_pos < inc_pos:
                return True
            if cand_pos > inc_pos:
                return False
        elif cand_pos is not None:
            return True
        elif inc_pos is not None:
            return False
        cand_event = getattr(candidate, "event_id", "") or ""
        inc_event = getattr(incumbent, "event_id", "") or ""
        return cand_event < inc_event

    for market in markets:
        slug = getattr(market, "group_slug", None)
        if not slug:
            standalone.append(market)
            continue
        existing = grouped.get(slug)
        if existing is None or _prefer_candidate(market, existing):
            grouped[slug] = market
    return standalone + list(grouped.values())


def _attach_group_fields(
    session: Session, markets: list[schemas.MarketResponse], *, include_siblings: bool = False
) -> None:
    slug_map: dict[str, list[schemas.MarketResponse]] = {}
    for market in markets:
        slug = getattr(market, "group_slug", None)
        if not slug:
            continue
        if getattr(market, "group_item_threshold", None) is None and getattr(market, "group_item_title", None):
            fallback = _parse_threshold_from_title(getattr(market, "group_item_title", None))
            if fallback is not None:
                market.group_item_threshold = fallback
                if getattr(market, "group_position", None) is None:
                    try:
                        market.group_position = int(fallback)
                    except (TypeError, ValueError, OverflowError):
                        market.group_position = None
        slug_map.setdefault(slug, []).append(market)
    if not slug_map:
        return
    aggregates = _load_group_aggregates(session, set(slug_map.keys()))
    for slug, group_markets in slug_map.items():
        siblings: list[schemas.MarketSibling] | None = None
        if include_siblings:
            siblings = _get_group_siblings(session, slug)
        aggregate = aggregates.get(slug)
        aggregate_volume = aggregate.get("volume_24h_usd") if aggregate else None
        aggregate_liquidity = aggregate.get("liquidity_usd") if aggregate else None
        if siblings is not None:
            aggregate_volume = aggregate_volume or _sum_sibling_volume(siblings)
            aggregate_liquidity = aggregate_liquidity or _sum_sibling_liquidity(siblings)
        for market in group_markets:
            if siblings is not None:
                market.siblings = siblings
            if aggregate_volume is not None:
                market.volume_24h_usd = aggregate_volume
            if aggregate_liquidity is not None:
                market.liquidity_usd = aggregate_liquidity


def _load_normalized_fields(session: Session, markets: list[schemas.MarketResponse]) -> None:
    """Populate outcomes, prices, tags, clob tokens, and gamma metadata onto market models."""

    id_map: dict[int, schemas.MarketResponse] = {}
    for market in markets:
        mid = getattr(market, "id", None)
        if isinstance(mid, int):
            id_map[mid] = market
    if not id_map:
        return
    market_ids = list(id_map.keys())

    # Outcomes
    outcome_rows = session.execute(
        select(models.MarketOutcome)
        .where(models.MarketOutcome.market_id.in_(market_ids))
        .order_by(models.MarketOutcome.market_id, models.MarketOutcome.outcome_id)
    ).scalars()
    outcome_map: dict[int, list[models.MarketOutcome]] = {}
    for outcome_row in outcome_rows:
        mid = getattr(outcome_row, "market_id", None)
        try:
            mid_int = int(mid) if mid is not None else None
        except (TypeError, ValueError):
            mid_int = None
        if mid_int is None:
            continue
        outcome_map.setdefault(mid_int, []).append(outcome_row)
    for mid, target in id_map.items():
        outcomes = outcome_map.get(mid, [])
        labels = [outcome_row.label for outcome_row in outcomes]
        prices_raw = [float(outcome_row.price) if outcome_row.price is not None else None for outcome_row in outcomes]
        target.outcomes = labels or None
        target.outcome_prices = (
            [float(price) for price in prices_raw if price is not None]
            if any(p is not None for p in prices_raw)
            else None
        )

    # Tags
    tag_rows = session.execute(
        select(models.MarketTag).where(models.MarketTag.market_id.in_(market_ids)).order_by(models.MarketTag.tag)
    ).scalars()
    tag_map: dict[int, list[str]] = {}
    tag_iter: Iterable[models.MarketTag] = cast(Iterable[models.MarketTag], tag_rows)
    for tag_row in tag_iter:
        mid = getattr(tag_row, "market_id", None)
        try:
            mid_int = int(mid) if mid is not None else None
        except (TypeError, ValueError):
            mid_int = None
        if mid_int is None or tag_row.tag is None:
            continue
        tag_map.setdefault(mid_int, []).append(str(tag_row.tag))
    for mid, target in id_map.items():
        target.tags = tag_map.get(mid) or None

    # Clob tokens
    token_rows = session.execute(
        select(models.MarketClobToken)
        .where(models.MarketClobToken.market_id.in_(market_ids))
        .order_by(models.MarketClobToken.id)
    ).scalars()
    token_map: dict[int, list[str]] = {}
    token_iter: Iterable[models.MarketClobToken] = cast(Iterable[models.MarketClobToken], token_rows)
    for token_row in token_iter:
        mid = getattr(token_row, "market_id", None)
        try:
            mid_int = int(mid) if mid is not None else None
        except (TypeError, ValueError):
            mid_int = None
        if mid_int is None or not token_row.token_id:
            continue
        token_map.setdefault(mid_int, []).append(str(token_row.token_id))
    for mid, target in id_map.items():
        tokens = token_map.get(mid, [])
        target.clob_token_ids = tokens or None

    # Gamma metadata
    meta_rows = session.execute(
        select(models.MarketGammaMetadata).where(models.MarketGammaMetadata.market_id.in_(market_ids))
    ).scalars()
    meta_map: dict[int, models.MarketGammaMetadata] = {}
    meta_iter: Iterable[models.MarketGammaMetadata] = cast(Iterable[models.MarketGammaMetadata], meta_rows)
    for meta_row in meta_iter:
        mid = getattr(meta_row, "market_id", None)
        try:
            mid_int = int(mid) if mid is not None else None
        except (TypeError, ValueError):
            mid_int = None
        if mid_int is None:
            continue
        meta_map[mid_int] = meta_row
    event_rows = session.execute(
        select(models.MarketGammaEvent).where(models.MarketGammaEvent.market_id.in_(market_ids))
    ).scalars()
    event_map: dict[int, models.MarketGammaEvent] = {}
    event_iter: Iterable[models.MarketGammaEvent] = cast(Iterable[models.MarketGammaEvent], event_rows)
    for event_row in event_iter:
        mid = getattr(event_row, "market_id", None)
        try:
            mid_int = int(mid) if mid is not None else None
        except (TypeError, ValueError):
            mid_int = None
        if mid_int is None or mid_int in event_map:
            continue
        event_map[mid_int] = event_row
    for mid, target in id_map.items():
        meta = meta_map.get(mid)
        if not meta:
            continue
        if meta.description:
            target.description = meta.description
        if meta.resolution_source:
            target.resolution_source = meta.resolution_source
        # Prefer explicit yes/no ids, otherwise fall back to tokens list
        gamma_token_ids: list[str] = []
        if meta.clob_token_id_yes:
            gamma_token_ids.append(str(meta.clob_token_id_yes))
        if meta.clob_token_id_no:
            gamma_token_ids.append(str(meta.clob_token_id_no))
        if gamma_token_ids:
            target.clob_token_ids = gamma_token_ids
        if meta.order_price_min_tick_size is not None:
            target.price_tick_size = Decimal(str(meta.order_price_min_tick_size))
        if meta.order_min_size is not None:
            target.order_min_size = Decimal(str(meta.order_min_size))
        if meta.enable_order_book is not None:
            target.enable_order_book = meta.enable_order_book
        if meta.best_bid is not None:
            target.best_bid = float(meta.best_bid)
        if meta.best_ask is not None:
            target.best_ask = float(meta.best_ask)
        if meta.spread is not None:
            target.spread = float(meta.spread)
        try:
            if meta.volume is not None:
                target.volume = float(meta.volume)
        except (TypeError, ValueError):
            target.volume = target.volume if hasattr(target, "volume") else None
        # Basic liquidity/volume hints from Gamma metadata for popularity scoring.
        try:
            if meta.liquidity_clob is not None:
                target.liquidity_usd = float(meta.liquidity_clob)
            elif meta.liquidity_num is not None:
                target.liquidity_usd = float(meta.liquidity_num)
            elif meta.liquidity is not None:
                target.liquidity_usd = float(meta.liquidity)
        except (TypeError, ValueError):
            target.liquidity_usd = target.liquidity_usd or None
        try:
            if meta.volume1mo is not None:
                target.volume_24h_usd = float(meta.volume1mo) / 30  # rough average
            elif meta.volume_num is not None:
                target.volume_24h_usd = float(meta.volume_num)
            elif meta.volume is not None:
                target.volume_24h_usd = float(meta.volume)
        except (TypeError, ValueError):
            target.volume_24h_usd = target.volume_24h_usd or None
        try:
            if meta.volume_clob is not None:
                target.orderbook_volume_usd = float(meta.volume_clob)
        except (TypeError, ValueError):
            target.orderbook_volume_usd = target.orderbook_volume_usd or None
        if meta.group_slug and not getattr(target, "group_slug", None):
            target.group_slug = meta.group_slug
        if meta.group_item_title and not getattr(target, "group_item_title", None):
            target.group_item_title = meta.group_item_title
        threshold_value = None
        if meta.group_item_threshold is not None:
            threshold_value = _parse_group_threshold(meta.group_item_threshold)
            target.group_item_threshold = threshold_value
        if threshold_value is None and getattr(target, "group_item_title", None):
            threshold_value = _parse_threshold_from_title(target.group_item_title)
            if threshold_value is not None:
                target.group_item_threshold = threshold_value
        if getattr(target, "group_position", None) is None and threshold_value is not None:
            try:
                target.group_position = int(threshold_value)
            except (TypeError, ValueError, OverflowError):
                target.group_position = None
        event_meta = event_map.get(mid)
        if event_meta is not None and event_meta.open_interest is not None:
            try:
                target.open_interest = float(event_meta.open_interest)
            except (TypeError, ValueError):
                target.open_interest = target.open_interest if hasattr(target, "open_interest") else None


def _attach_resolution_to_market(
    market: schemas.MarketResponse,
    resolution: models.Resolution | None = None,
) -> None:
    if resolution is None or market is None:
        return
    try:
        market.resolution = _build_resolution_summary_from_record(resolution, market=market)  # type: ignore[arg-type]
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="markets.resolution.hydrate_failed",
            message="failed to attach resolution to market",
            event_id=getattr(market, "event_id", None),
            condition_id=getattr(resolution, "condition_id", None),
            error=str(exc),
        )
        return


def _augment_market_models(markets: list[schemas.MarketResponse]) -> list[schemas.MarketResponse]:
    for market in markets:
        _apply_market_caps(market)
    return markets


def _compute_market_popularity(market: schemas.MarketResponse) -> float:
    def clamp(value: Any) -> float:
        try:
            if value is None:
                return 0.0
            numeric = float(value)
            return numeric if numeric > 0 else 0.0
        except (TypeError, ValueError):
            return 0.0

    liquidity = clamp(getattr(market, "liquidity_usd", None))
    volume = clamp(getattr(market, "volume_24h_usd", None))
    orderbook = clamp(getattr(market, "orderbook_volume_usd", None))
    trades = clamp(getattr(market, "trades_quantity", None))
    score = (liquidity**0.5) * 0.4 + (volume**0.5) * 0.35 + (orderbook**0.5) * 0.2 + (trades**0.5) * 0.05
    return score if score > 0 and score == score else 0.0


def _is_trending_market(market: schemas.MarketResponse, popularity: float | None = None) -> bool:
    liquidity = getattr(market, "liquidity_usd", None) or 0
    volume = getattr(market, "volume_24h_usd", None) or 0
    orderbook = getattr(market, "orderbook_volume_usd", None) or 0
    trades = getattr(market, "trades_quantity", None) or 0
    popularity = popularity if popularity is not None else _compute_market_popularity(market)
    return (
        popularity >= TRENDING_MIN_SCORE
        and liquidity >= TRENDING_MIN_LIQUIDITY
        and volume >= TRENDING_MIN_VOLUME_24H
        and (orderbook >= TRENDING_MIN_ORDERBOOK or orderbook == 0)
        and (trades >= TRENDING_MIN_TRADES or trades == 0)
    )


def _load_resolution_records(session: Session, markets: list[schemas.MarketResponse]) -> dict[str, models.Resolution]:
    condition_ids = []
    for market in markets:
        condition = getattr(market, "condition_id", None)
        if isinstance(condition, str):
            condition_ids.append(condition.lower())
    if not condition_ids:
        return {}
    stmt = select(models.Resolution).where(models.Resolution.condition_id.in_(condition_ids))
    records: dict[str, models.Resolution] = {}
    for record in session.scalars(stmt):
        if record.condition_id:
            records[record.condition_id.lower()] = record
    return records


def _load_outcomes_for_market(session: Session, market: models.Market | schemas.MarketResponse | None) -> list[str]:
    if market is None:
        return []
    mid = getattr(market, "id", None)
    if not isinstance(mid, int):
        return []
    rows = session.execute(
        select(models.MarketOutcome.label)
        .where(models.MarketOutcome.market_id == mid)
        .order_by(models.MarketOutcome.outcome_id)
    ).scalars()
    return list(rows)


def _enrich_market_models(
    session: Session, markets: list[schemas.MarketResponse], *, include_siblings: bool = False
) -> list[schemas.MarketResponse]:
    """Attach metadata, caps, and cached resolutions to market responses."""

    _load_normalized_fields(session, markets)
    _attach_group_fields(session, markets, include_siblings=include_siblings)
    _augment_market_models(markets)
    resolution_map = _load_resolution_records(session, markets)
    for market in markets:
        condition = getattr(market, "condition_id", None)
        if isinstance(condition, str):
            resolution = resolution_map.get(condition.lower())
            if resolution:
                _attach_resolution_to_market(market, resolution)
    return markets


def _normalize_bigint(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if isinstance(value, Decimal):
            return str(int(value))
        return str(int(value))
    except (TypeError, ValueError, OverflowError):
        try:
            return str(value)
        except (TypeError, ValueError):
            return None


def _parse_public_signals(signals: list[Any] | None) -> dict[str, str | None]:
    parsed: dict[str, str | None] = {
        "merkle_root": None,
        "market_id": None,
        "winning_outcome_id": None,
        "total_escrow": None,
        "total_liability": None,
        "rake_bps": None,
        "pool_total_yes": None,
        "pool_total_no": None,
        "circuit_hash": None,
    }
    if not signals:
        return parsed
    try:
        normalized = [str(entry) for entry in signals]
    except (TypeError, ValueError):
        return parsed
    fields = [
        "merkle_root",
        "market_id",
        "winning_outcome_id",
        "total_escrow",
        "total_liability",
        "rake_bps",
        "pool_total_yes",
        "pool_total_no",
        "circuit_hash",
    ]
    for index, key in enumerate(fields):
        if index < len(normalized):
            parsed[key] = normalized[index]
    return parsed


def _cached_value(cached: dict[str, Any] | None, *keys: str) -> Any:
    if not isinstance(cached, dict):
        return None
    for key in keys:
        if key in cached:
            return cached[key]
    return None


def _cached_public_signals(cached: dict[str, Any] | None) -> list[str] | None:
    signals = _cached_value(cached, "public_signals", "publicSignals")
    if isinstance(signals, list):
        try:
            return [str(entry) for entry in signals]
        except Exception:
            return None
    return None


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _build_proof_receipt_model(
    receipt: shared_models.SettlementReceipt,
    settlement: shared_models.Settlement | None,
    market: shared_models.Market | None,
    cached: dict[str, Any] | None,
) -> schemas.ProofReceipt:
    cached_signals = _cached_public_signals(cached)
    raw_signals = receipt.public_signals
    signals: list[str] | None = None
    if isinstance(raw_signals, (list, tuple)):
        signals = [str(value) for value in raw_signals]
    elif cached_signals:
        signals = cached_signals
    else:
        signals = []
    parsed_signals = _parse_public_signals(signals)

    merkle_root = _coalesce(
        getattr(settlement, "merkle_root", None) if settlement is not None else None,
        _cached_value(cached, "merkleRoot"),
        parsed_signals.get("merkle_root"),
    )
    pool_total_yes = _normalize_bigint(
        _coalesce(
            getattr(settlement, "pool_total_yes", None) if settlement is not None else None,
            parsed_signals.get("pool_total_yes"),
            _cached_value(cached, "poolTotalYes"),
        )
    )
    pool_total_no = _normalize_bigint(
        _coalesce(
            getattr(settlement, "pool_total_no", None) if settlement is not None else None,
            parsed_signals.get("pool_total_no"),
            _cached_value(cached, "poolTotalNo"),
        )
    )
    total_escrow = _normalize_bigint(
        _coalesce(
            getattr(settlement, "total_escrow", None) if settlement is not None else None,
            parsed_signals.get("total_escrow"),
            _cached_value(cached, "totalEscrow"),
        )
    )
    total_liability = _normalize_bigint(
        _coalesce(
            getattr(settlement, "total_liability", None) if settlement is not None else None,
            parsed_signals.get("total_liability"),
            _cached_value(cached, "totalLiability"),
        )
    )

    winning_outcome_raw = _coalesce(
        getattr(settlement, "winning_outcome_id", None) if settlement is not None else None,
        parsed_signals.get("winning_outcome_id"),
        _cached_value(cached, "winningOutcomeId"),
    )
    try:
        winning_outcome_id = int(winning_outcome_raw) if winning_outcome_raw not in (None, "") else None
    except (TypeError, ValueError):
        winning_outcome_id = None

    rake_bps_raw = _coalesce(
        getattr(settlement, "rake_bps", None) if settlement is not None else None,
        parsed_signals.get("rake_bps"),
        _cached_value(cached, "rakeBps"),
    )
    try:
        rake_bps = int(rake_bps_raw) if rake_bps_raw not in (None, "") else None
    except (TypeError, ValueError):
        rake_bps = None

    circuit_hash = _coalesce(
        receipt.circuit_hash,
        settlement.circuit_hash if settlement is not None else None,
        parsed_signals.get("circuit_hash"),
        _cached_value(cached, "circuit_hash", "circuitHash"),
    )
    proof_hash = _coalesce(receipt.proof_hash, _cached_value(cached, "proof_hash", "proofHash"))
    proof_value = _cached_value(cached, "proof")
    generated_at = _coalesce(receipt.generated_at, _cached_value(cached, "generated_at", "generatedAt"))
    condition_id = _coalesce(
        getattr(market, "condition_id", None) if market is not None else None,
        _cached_value(cached, "conditionId"),
    )
    if isinstance(condition_id, str):
        condition_id = condition_id.lower()
    market_address = _coalesce(
        receipt.market_address, getattr(market, "market_address", None) if market is not None else None
    ) or _cached_value(cached, "marketAddress")
    market_id_value = _coalesce(
        receipt.market_id,
        parsed_signals.get("market_id"),
        _cached_value(cached, "marketId"),
    )
    try:
        market_id_int = int(market_id_value) if market_id_value is not None else None
    except (TypeError, ValueError):
        try:
            market_id_int = int(receipt.market_id) if receipt.market_id is not None else None
        except Exception:
            market_id_int = None

    winning_pool = None
    if winning_outcome_id in (0, 1):
        winning_pool = pool_total_yes if winning_outcome_id == 0 else pool_total_no
    total_pool = total_escrow
    if total_pool is None and pool_total_yes is not None and pool_total_no is not None:
        try:
            total_pool = str(int(pool_total_yes) + int(pool_total_no))
        except Exception:
            total_pool = None

    receipt_payload = {
        "request_id": receipt.request_id,
        "market_id": market_id_int,
        "event_id": getattr(market, "event_id", None),
        "condition_id": condition_id,
        "market_address": market_address,
        "proof_hash": proof_hash,
        "prover_version": receipt.prover_version or _cached_value(cached, "prover_version", "proverVersion"),
        "circuit_hash": circuit_hash,
        "generated_at": generated_at,
        "proof": proof_value,
        "public_signals": [str(value) for value in (signals or [])],
        "merkle_root": merkle_root,
        "total_escrow": total_escrow,
        "total_liability": total_liability,
        "rake_bps": rake_bps,
        "winning_outcome_id": winning_outcome_id,
        "pool_total_yes": pool_total_yes,
        "pool_total_no": pool_total_no,
        "winning_pool": winning_pool,
        "total_pool": total_pool,
    }

    return schemas.ProofReceipt.model_validate(receipt_payload)


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
        matched = _enrich_market_models(session, matched)
    return matched


def _canonical_category_lookup(raw: str) -> tuple[str, str] | None:
    return canonical_category_from_slug(raw)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or request.headers.get("traceparent") or str(uuid4())
    token = set_request_id(request_id)
    start_time = time.perf_counter()
    request.state.cache_context = {
        "cache_hit": None,
        "cache_key": None,
        "cache_source": None,
    }  # type: ignore[attr-defined]
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
        try:
            REQUEST_LATENCY.labels(
                method=request.method, path=request.url.path, status_code=str(exc.status_code)
            ).observe(duration_ms / 1000.0)
        except Exception as metric_exc:  # pragma: no cover - defensive metrics guard
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
        try:
            REQUEST_LATENCY.labels(method=request.method, path=request.url.path, status_code="500").observe(
                duration_ms / 1000.0
            )
        except Exception as metric_exc:  # pragma: no cover - defensive metrics guard
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
    try:
        REQUEST_LATENCY.labels(
            method=request.method, path=request.url.path, status_code=str(response.status_code)
        ).observe(duration_ms / 1000.0)
    except Exception as metric_exc:  # pragma: no cover - defensive metrics guard
        log_event(
            logger,
            logging.DEBUG,
            event="metrics.emit.failed",
            message="failed to emit request latency metric",
            error=str(metric_exc),
        )
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


@app.get("/healthz", response_model=schemas.HealthResponse, tags=["health"])
async def health_check(session: Session = Depends(get_session)) -> schemas.HealthResponse:
    return await build_health_response(session)


@app.get("/ready", response_model=schemas.HealthResponse, tags=["health"])
async def readiness_check(session: Session = Depends(get_session)) -> schemas.HealthResponse:
    return await build_health_response(session)


@app.get("/live", tags=["health"])
def liveness_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/healthz/heartbeats", response_model=schemas.HeartbeatDashboard, tags=["health"])
def heartbeat_dashboard() -> schemas.HeartbeatDashboard:
    now = datetime.now(tz=UTC)
    worker_status = _build_worker_dashboard(now)
    api_status = _build_api_dashboard(now)
    return schemas.HeartbeatDashboard(
        generated_at=now,
        worker=worker_status,
        api=api_status,
    )


def _enforce_caps(
    session: Session,
    *,
    stake_zen: Decimal,
    market_id: str | None,
    user_id: str | None,
    include_stake: bool = True,
    exclude_quote: models.Quote | None = None,
) -> tuple[float | None, float | None, float | None, float | None]:
    """Apply per-bet/user/market caps using durable quote state."""

    shared_repository.expire_stale_quotes(session)
    window = settings.bet_cap_ttl_seconds
    market_total = None
    user_total = None
    if market_id:
        market_existing = float(shared_repository.sum_quote_stakes(session, market_id=market_id, window_seconds=window))
        if exclude_quote and exclude_quote.market_id == market_id:
            market_existing = max(0.0, market_existing - float(exclude_quote.stake_zen))
        projected_market = market_existing + (float(stake_zen) if include_stake else 0.0)
        if projected_market > settings.max_market_stake_zen:
            remaining = max(0.0, settings.max_market_stake_zen - market_existing)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "market_cap_exceeded",
                    "max_market_stake_zen": settings.max_market_stake_zen,
                    "remaining_market_stake_zen": remaining,
                    "stake_zen": float(stake_zen),
                    "market_id": market_id,
                },
            )
        market_total = projected_market

    if market_id and user_id:
        user_existing = float(
            shared_repository.sum_quote_stakes(
                session,
                market_id=market_id,
                user_id=user_id,
                window_seconds=window,
            )
        )
        if exclude_quote and exclude_quote.market_id == market_id and exclude_quote.user_id == user_id:
            user_existing = max(0.0, user_existing - float(exclude_quote.stake_zen))
        projected_user = user_existing + (float(stake_zen) if include_stake else 0.0)
        if projected_user > settings.max_user_stake_per_market_zen:
            remaining_user_cap = max(0.0, settings.max_user_stake_per_market_zen - user_existing)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "user_market_cap_exceeded",
                    "max_user_stake_per_market_zen": settings.max_user_stake_per_market_zen,
                    "remaining_user_stake_zen": remaining_user_cap,
                    "stake_zen": float(stake_zen),
                    "market_id": market_id,
                    "user_id": user_id,
                },
            )
        user_total = projected_user

    remaining_market = None
    remaining_user = None
    if market_total is not None:
        remaining_market = max(0.0, settings.max_market_stake_zen - market_total)
    if user_total is not None:
        remaining_user = max(0.0, settings.max_user_stake_per_market_zen - user_total)
    return market_total, user_total, remaining_market, remaining_user


@app.post("/pricing/quote", response_model=schemas.PricingQuoteResponse, tags=["pricing"])
def pricing_quote(
    payload: schemas.PricingQuoteRequest,
    session: Session = Depends(get_session),
) -> schemas.PricingQuoteResponse:
    """Return a pricing quote for a ZEN stake, gating on FX availability."""

    if payload.stake_zen > settings.max_stake_zen:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "stake_above_cap",
                "stake_zen": float(payload.stake_zen),
                "max_stake_zen": settings.max_stake_zen,
            },
        )
    if payload.market_id:
        market_record = shared_repository.get_market_by_event_id(session, payload.market_id)
        if market_record and (
            market_record.status
            in {shared_models.MarketStatusEnum.SETTLED.value, shared_models.MarketStatusEnum.CANCELLED.value}
            or market_record.resolved_at is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Market is settled; new quotes are disabled",
            )
    # Always source FX server-side; ignore client-provided zen_usd.
    try:
        zen_usd_raw, stale, fx_received_at = fetch_fx_price_sync(settings)
        if stale:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "fx_stale",
                    "message": "FX price stale",
                    "fx_received_at": fx_received_at.isoformat() if fx_received_at else None,
                },
            )
        zen_usd = float(zen_usd_raw) if zen_usd_raw is not None else None
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "fx_unavailable", "message": "FX price unavailable"},
        ) from exc

    # Enforce durable per-user and per-market caps using persisted quotes.
    market_total = None
    user_total = None
    user_remaining = None
    market_remaining = None
    if payload.market_id:
        market_total, user_total, market_remaining, user_remaining = _enforce_caps(
            session,
            stake_zen=payload.stake_zen,
            market_id=payload.market_id,
            user_id=payload.user_id,
        )

    if zen_usd is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "fx_unavailable", "message": "FX price unavailable"},
        )
    if settings.pricing_chain_id is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "pricing_chain_missing", "message": "Pricing chain id not configured"},
        )

    stake_wei = _to_wei_amount(payload.stake_zen)
    zen_usd_scaled = _scale_fx_value(zen_usd)
    engine = PricingEngine(settings)
    try:
        quote = engine.quote(Decimal(str(payload.stake_zen)), Decimal(str(zen_usd)))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Build a signed quote to prevent client tampering.
    expires_at = datetime.now(tz=UTC) + timedelta(seconds=settings.pricing_quote_ttl_seconds)
    expiry_ts = int(expires_at.timestamp())
    quote_id = token_hex(32)
    if settings.pricing_signer_private_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "pricing_signer_unavailable", "message": "Pricing signer unavailable"},
            headers=None,
        )
    raw_signer_key = settings.pricing_signer_private_key
    signer_key: str | None
    if isinstance(raw_signer_key, SecretStr):
        signer_key = raw_signer_key.get_secret_value()
    else:
        signer_key = cast(str | None, raw_signer_key)
    signer_account = load_account(signer_key)
    try:
        # Sign the same digest the contract verifies to prevent client tampering.
        digest = _build_quote_digest(
            settings.pricing_chain_id,
            payload.market_address,
            payload.wallet_address,
            int(payload.outcome_id),
            stake_wei,
            zen_usd_scaled,
            expiry_ts,
            quote_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    signed = Account.sign_message(encode_defunct(hexstr=digest.hex()), signer_account.key)  # type: ignore[arg-type]

    quote = quote.model_copy(
        update={
            "max_stake_zen": settings.max_stake_zen,
            "max_user_stake_per_market_zen": settings.max_user_stake_per_market_zen if payload.market_id else None,
            "max_market_stake_zen": settings.max_market_stake_zen if payload.market_id else None,
            "remaining_user_stake_zen": user_remaining,
            "remaining_market_stake_zen": market_remaining,
            "stake_wei": stake_wei,
            "zen_usd_scaled": zen_usd_scaled,
            "quote_id": quote_id,
            "expires_at": expires_at,
            "expiry_ts": expiry_ts,
            "fx_stale": False,
            "fx_received_at": fx_received_at,
            "signature": signed.signature.hex(),
            "signer": signer_account.address,
            "market_id": payload.market_id,
            "user_id": payload.user_id,
            "wallet_address": payload.wallet_address,
            "outcome_id": payload.outcome_id,
            "market_address": payload.market_address,
            "chain_id": settings.pricing_chain_id,
        }
    )
    quote_payload = quote.model_dump(mode="json")
    try:
        shared_repository.create_quote(
            session,
            {
                "quote_id": quote_id,
                "status": models.QuoteStatusEnum.ISSUED.value,
                "payload": quote_payload,
                "stake_zen": Decimal(str(quote.stake_zen)),
                "stake_wei": stake_wei,
                "fx_scaled": zen_usd_scaled,
                "zen_usd": quote.zen_usd,
                "market_id": payload.market_id,
                "market_address": payload.market_address,
                "user_id": payload.user_id,
                "wallet_address": payload.wallet_address,
                "outcome_id": quote.outcome_id,
                "chain_id": settings.pricing_chain_id,
                "expires_at": expires_at,
            },
        )
        session.flush()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive log
        log_event(
            logger,
            logging.ERROR,
            event="pricing.quote.persist_failed",
            message="failed to persist issued quote",
            quote_id=quote_id,
            error=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Quote persistence failed") from exc

    log_event(
        logger,
        logging.INFO,
        event="pricing.quote",
        message="pricing quote generated",
        stake_zen=payload.stake_zen,
        zen_usd=zen_usd,
        total_monetisation=str(quote.total_monetization),
        market_total=market_total,
        user_total=user_total,
        quote_id=quote_id,
        market_id=payload.market_id,
        user_id=payload.user_id,
    )
    PRICING_COUNTER.labels(event="issue", result="ok").inc()
    return quote


@app.post("/pricing/submit", response_model=schemas.PricingSubmitResponse, tags=["pricing"])
def pricing_submit(
    payload: schemas.PricingSubmitRequest,
    session: Session = Depends(get_session),
) -> schemas.PricingSubmitResponse:
    """Validate a signed pricing quote and optionally enforce FX drift bounds."""

    quote = payload.quote
    now = datetime.now(tz=UTC)

    def _as_aware(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            return dt.replace(tzinfo=UTC)
        return dt

    if settings.pricing_chain_id is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Pricing chain id not configured")
    if quote.wallet_address is None or quote.market_address is None or quote.outcome_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="wallet_address, market_address, and outcome_id are required for signed quotes",
        )

    raw_signer_key = settings.pricing_signer_private_key
    signer_key: str | None
    if isinstance(raw_signer_key, SecretStr):
        signer_key = raw_signer_key.get_secret_value()
    else:
        signer_key = cast(str | None, raw_signer_key)
    signer_account = load_account(signer_key) if signer_key else None
    if signer_account is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Pricing signer unavailable")

    if not quote.quote_id:
        PRICING_COUNTER.labels(event="submit", result="missing").inc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote not found or expired")
    quote_id = quote.quote_id
    db_quote = shared_repository.get_quote(session, quote_id)
    if db_quote is None:
        PRICING_COUNTER.labels(event="submit", result="missing").inc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote not found or expired")
    if db_quote.status == models.QuoteStatusEnum.CONSUMED.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Quote already consumed")
    db_expires_at = _as_aware(cast(datetime | None, getattr(db_quote, "expires_at", None)))
    if db_quote.status == models.QuoteStatusEnum.EXPIRED.value or (db_expires_at and db_expires_at <= now):
        db_quote.status = models.QuoteStatusEnum.EXPIRED.value
        session.flush()
        PRICING_COUNTER.labels(event="submit", result="expired").inc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote expired")
    quote_expires_at = _as_aware(quote.expires_at)
    if quote_expires_at and quote_expires_at <= now:
        db_quote.status = models.QuoteStatusEnum.EXPIRED.value
        session.flush()
        PRICING_COUNTER.labels(event="submit", result="expired").inc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote expired")
    if db_quote.wallet_address and quote.wallet_address:
        if db_quote.wallet_address.lower() != quote.wallet_address.lower():
            PRICING_COUNTER.labels(event="submit", result="wallet_mismatch").inc()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote wallet mismatch")
    if db_quote.market_address and quote.market_address:
        if db_quote.market_address.lower() != quote.market_address.lower():
            PRICING_COUNTER.labels(event="submit", result="market_mismatch").inc()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote market mismatch")
    if db_quote.outcome_id is not None and quote.outcome_id is not None:
        if db_quote.outcome_id != quote.outcome_id:
            PRICING_COUNTER.labels(event="submit", result="outcome_mismatch").inc()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote outcome mismatch")

    expiry_reference = quote_expires_at or db_expires_at or now
    expiry_ts = quote.expiry_ts or int(expiry_reference.timestamp())
    stake_wei = quote.stake_wei
    zen_usd_scaled = quote.zen_usd_scaled
    recalculated_stake = _to_wei_amount(quote.stake_zen)
    recalculated_fx = _scale_fx_value(quote.zen_usd)
    if recalculated_stake != stake_wei or recalculated_fx != zen_usd_scaled:
        # Protect against client-side mutation: the numeric fields must match our scaled copies.
        PRICING_COUNTER.labels(event="submit", result="scaled_mismatch").inc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote fields do not match scaled values")
    try:
        digest = _build_quote_digest(
            settings.pricing_chain_id,
            quote.market_address,
            quote.wallet_address,
            int(quote.outcome_id),
            stake_wei,
            zen_usd_scaled,
            expiry_ts,
            quote_id,
        )
        recovered = Account.recover_message(encode_defunct(hexstr=digest.hex()), signature=quote.signature)
    except Exception as exc:
        PRICING_COUNTER.labels(event="submit", result="bad_signature").inc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid signature: {exc}") from exc
    if recovered.lower() != signer_account.address.lower():
        PRICING_COUNTER.labels(event="submit", result="signer_mismatch").inc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote signer mismatch")
    if db_quote.stake_wei != stake_wei or db_quote.fx_scaled != zen_usd_scaled:
        PRICING_COUNTER.labels(event="submit", result="payload_mismatch").inc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote payload mismatch with ledger")

    # Enforce fresh FX vs quoted value if requested.
    current_fx: Decimal | None = None
    if payload.max_fx_diff_percent is not None:
        try:
            raw_fx_price, fx_stale, fx_received_at = fetch_fx_price_sync(settings)
            if raw_fx_price is not None:
                current_fx = Decimal(str(raw_fx_price))
            if fx_stale:
                PRICING_COUNTER.labels(event="submit", result="fx_stale").inc()
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "error": "fx_stale",
                        "message": "FX price stale during submit",
                        "fx_received_at": fx_received_at.isoformat() if fx_received_at else None,
                    },
                )
            fx_diff_percent = (
                (abs(current_fx - quote.zen_usd) / quote.zen_usd * Decimal("100"))
                if current_fx is not None and quote.zen_usd
                else Decimal("0")
            )
            if current_fx is None:
                PRICING_COUNTER.labels(event="submit", result="fx_missing").inc()
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"error": "fx_missing", "message": "FX check failed: missing price"},
                )
            if fx_diff_percent > payload.max_fx_diff_percent:
                PRICING_COUNTER.labels(event="submit", result="fx_drift").inc()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"FX drift {fx_diff_percent:.4f}% exceeds bound {payload.max_fx_diff_percent}%",
                )
        except HTTPException:
            raise
        except Exception as exc:
            PRICING_COUNTER.labels(event="submit", result="fx_error").inc()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "fx_check_failed", "message": f"FX check failed: {exc}"},
            ) from exc
    else:
        current_fx = quote.zen_usd
    _enforce_caps(
        session,
        stake_zen=quote.stake_zen,
        market_id=quote.market_id,
        user_id=quote.user_id,
        exclude_quote=db_quote,
    )

    db_quote.payload = quote.model_dump(mode="json")
    shared_repository.mark_quote_status(
        session,
        db_quote,
        models.QuoteStatusEnum.CONSUMED,
        consumed_at=now,
    )
    session.flush()
    PRICING_COUNTER.labels(event="submit", result="ok").inc()
    log_event(
        logger,
        logging.INFO,
        event="pricing.submit",
        message="pricing quote submitted",
        quote_id=quote.quote_id,
        market_id=quote.market_id,
        user_id=quote.user_id,
        outcome_id=quote.outcome_id,
        stake_zen=float(quote.stake_zen),
        zen_usd=float(quote.zen_usd),
    )

    return schemas.PricingSubmitResponse(
        quote=quote,
        current_fx=current_fx if current_fx is not None else quote.zen_usd,
        valid=True,
    )


@app.get("/pricing/quotes/{quote_id}", response_model=schemas.QuoteRecord, tags=["pricing"])
def pricing_quote_state(quote_id: str, session: Session = Depends(get_session)) -> schemas.QuoteRecord:
    """Diagnostic endpoint to retrieve persisted quote state."""

    record = shared_repository.get_quote(session, quote_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="quote_not_found")
    return schemas.QuoteRecord.model_validate(record)


@app.get("/pricing/fx", response_model=schemas.FxQuoteResponse, tags=["pricing"])
async def pricing_fx() -> schemas.FxQuoteResponse:
    try:
        fx_quote = await fetch_fx_quote(settings, use_cache_on_error=False)
        if fx_quote.stale:
            log_event(
                logger,
                logging.WARNING,
                event="pricing.fx.stale",
                message="FX feed stale",
                fx_received_at=fx_quote.received_at.isoformat() if fx_quote.received_at else None,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "fx_stale",
                    "message": "FX price stale",
                    "fx_received_at": fx_quote.received_at.isoformat() if fx_quote.received_at else None,
                },
            )
        return fx_quote
    except httpx.HTTPError as exc:
        log_event(
            logger,
            logging.WARNING,
            event="pricing.fx.error",
            message="failed to fetch FX feed",
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "fx_unavailable", "message": "FX price unavailable"},
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive catch for malformed payloads
        log_event(
            logger,
            logging.WARNING,
            event="pricing.fx.error",
            message="unexpected FX parsing error",
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "fx_unavailable", "message": "FX price unavailable"},
        ) from exc


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
    return [schemas.TreasurySnapshot.model_validate(row) for row in rows]


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
    order_by: Annotated[str | None, Query(description="Order results (popularity|recent|volume_24h_usd)")] = None,
    trending: Annotated[bool | None, Query(description="Return trending slice first")] = None,
    featured: Annotated[bool | None, Query(description="Return only featured markets", alias="only_featured")] = None,
    coalesce_groups: Annotated[
        bool | None, Query(description="Return a single representative per group_slug", alias="coalesce_groups")
    ] = None,
    session: Session = Depends(get_session),
) -> list[schemas.MarketResponse]:
    coalesce_mode = bool(coalesce_groups)
    popularity_mode = order_by == "popularity" or bool(trending)
    volume_mode = order_by == "volume_24h_usd"
    if popularity_mode and not status:
        status = "active"
    normalized_search = search
    if search is not None:
        normalized = search.strip().lower()
        if len(normalized) > 120:
            normalized = normalized[:120]
        normalized_search = normalized
    cache_key = markets_list_cache_key(
        status,
        category,
        oracle,
        normalized_search,
        limit,
        offset,
        order_by=order_by or ("popularity" if popularity_mode else None),
        trending=trending,
        featured=featured,
        coalesce_groups=coalesce_groups,
    )
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
        order_by=order_by,
        trending=bool(trending),
        featured=featured,
        coalesce_groups=coalesce_mode,
    )
    start = time.perf_counter()
    cache_enabled = cache is not None and _should_cache_market_list(limit, offset, normalized_search)
    if cache_enabled:
        cached_payload = get_json(cache, cache_key)
        hydrated = _hydrate_cached_market_list(cache, cached_payload)
        if hydrated is not None:
            hydrated = _enrich_market_models(session, hydrated)
            update_cache_context(request, cache_key=cache_key, hit=True, source="markets:list")
            MARKETS_CACHE_COUNTER.labels(outcome="hit", status=status or "*", category=category or "*").inc()
            duration = (time.perf_counter() - start) * 1000
            cached_models = _filter_markets_for_visibility(hydrated)
            if coalesce_mode and cached_models:
                cached_models = _coalesce_grouped_markets(cached_models)
                cached_models = cached_models[offset : offset + limit]
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
                result_count=len(cached_models),
                featured=featured,
                coalesce_groups=coalesce_mode,
            )
            return cached_models
        MARKETS_CACHE_COUNTER.labels(outcome="miss", status=status or "*", category=category or "*").inc()
        update_cache_context(request, cache_key=cache_key, hit=False, source="markets:list")
    else:
        MARKETS_CACHE_COUNTER.labels(outcome="bypass", status=status or "*", category=category or "*").inc()
        update_cache_context(request, cache_key=None, hit=False, source="markets:list")

    query_limit = limit
    query_offset = offset
    if popularity_mode:
        query_limit = min(settings.max_page_size, max(limit * 4, settings.default_page_size))
        query_offset = 0
    elif volume_mode:
        query_limit = min(settings.max_page_size, max(limit * 4, settings.default_page_size))
        query_offset = 0
    if coalesce_mode:
        query_limit = min(settings.max_page_size, max(query_limit, limit * 3, limit + offset))
        query_offset = 0
    markets = crud.get_markets(
        session,
        status=status,
        category=category,
        oracle=oracle,
        search=normalized_search,
        featured=featured,
        limit=query_limit,
        offset=query_offset,
    )
    market_models = _enrich_market_models(session, [schemas.MarketResponse.model_validate(m) for m in markets])
    market_models = _filter_markets_for_visibility(market_models)
    if coalesce_mode and market_models:
        market_models = _coalesce_grouped_markets(market_models)
    if popularity_mode:
        popularity_scores = {m.event_id: _compute_market_popularity(m) for m in market_models}
        selected = market_models
        if trending:
            trending_slice = [m for m in market_models if _is_trending_market(m, popularity_scores.get(m.event_id))]
            if trending_slice:
                selected = trending_slice
        selected.sort(
            key=lambda m: (
                popularity_scores.get(m.event_id, 0),
                getattr(m, "updated_at", None) or datetime.fromtimestamp(0, tz=UTC),
            ),
            reverse=True,
        )
        market_models = selected if coalesce_mode else selected[:limit]
    elif order_by == "volume_24h_usd":
        market_models.sort(
            key=lambda m: (
                _safe_float(getattr(m, "volume_24h_usd", None)) or 0,
                getattr(m, "updated_at", None) or datetime.fromtimestamp(0, tz=UTC),
            ),
            reverse=True,
        )
    if coalesce_mode:
        market_models = market_models[offset : offset + limit]
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
            order_by=order_by,
            trending=bool(trending),
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
            order_by=order_by,
            trending=bool(trending),
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
            order_by=order_by,
            trending=bool(trending),
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
    coalesce_groups: Annotated[
        bool | None, Query(description="Return a single representative per group_slug", alias="coalesce_groups")
    ] = None,
    session: Session = Depends(get_session),
) -> list[schemas.MarketResponse]:
    order_by = request.query_params.get("order_by")
    volume_mode = order_by == "volume_24h_usd"
    coalesce_mode = bool(coalesce_groups)
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
        order_by=order_by,
        coalesce_groups=bool(coalesce_groups),
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
    cache_key = category_cache_key(category_slug_key, limit, offset, order_by=order_by, coalesce_groups=coalesce_groups)
    cache_enabled = cache is not None and _should_cache_market_list(limit, offset, None)
    if cache_enabled:
        cached_payload = get_json(cache, cache_key)
        hydrated = _hydrate_cached_market_list(cache, cached_payload)
        if hydrated is not None:
            hydrated = _enrich_market_models(session, hydrated)
            update_cache_context(request, cache_key=cache_key, hit=True, source="markets:category")
            models_from_cache = _filter_markets_for_visibility(hydrated)
            if coalesce_mode and models_from_cache:
                models_from_cache = _coalesce_grouped_markets(models_from_cache)
                models_from_cache = models_from_cache[offset : offset + limit]
            log_event(
                logger,
                logging.INFO,
                event="markets.category.cache_hit",
                message="served category markets from cache",
                category_slug=category_slug_key,
                limit=limit,
                result_count=len(models_from_cache),
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                coalesce_groups=coalesce_mode,
            )
            return models_from_cache
        update_cache_context(request, cache_key=cache_key, hit=False, source="markets:category")
    else:
        update_cache_context(request, cache_key=None, hit=False, source="markets:category")

    trending_category = category_slug_key == "trending"
    fetch_limit = limit
    fetch_offset = offset
    if coalesce_mode:
        fetch_limit = min(settings.max_page_size, max(limit * 3, limit + offset))
        fetch_offset = 0
    log_event(
        logger,
        logging.DEBUG,
        event="markets.category.fetch",
        message="fetching category markets from database",
        category_slug=category_slug_key,
        category_label=category_label,
        trending=trending_category,
        limit=fetch_limit,
        offset=fetch_offset,
        order_by=order_by,
    )
    if trending_category:
        markets = crud.get_markets(session, limit=fetch_limit, offset=fetch_offset)
    else:
        markets = crud.get_markets(session, category=category_label, limit=fetch_limit, offset=fetch_offset)
    market_models = _filter_markets_for_visibility(
        _enrich_market_models(session, [schemas.MarketResponse.model_validate(m) for m in markets])
    )
    if not market_models and not trending_category and offset == 0:
        fallback_matches = _fallback_markets_by_category_slug(session, category_slug_key, limit)
        if fallback_matches:
            market_models = _filter_markets_for_visibility(_enrich_market_models(session, fallback_matches))
    if coalesce_mode and market_models:
        market_models = _coalesce_grouped_markets(market_models)
    if volume_mode and market_models:
        market_models.sort(
            key=lambda m: (
                _safe_float(getattr(m, "volume_24h_usd", None)) or 0,
                getattr(m, "updated_at", None) or datetime.fromtimestamp(0, tz=UTC),
            ),
            reverse=True,
        )
    if coalesce_mode:
        market_models = market_models[offset : offset + limit]
    if not market_models:
        log_event(
            logger,
            logging.INFO,
            event="markets.category.empty",
            message="no markets available for category",
            category_slug=category_slug_key,
            limit=limit,
            offset=offset,
            order_by=order_by,
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


@app.get("/markets/group/{group_slug}", response_model=schemas.GroupedMarketsResponse, tags=["markets"])
def list_grouped_markets(
    group_slug: str,
    session: Session = Depends(get_session),
) -> schemas.GroupedMarketsResponse:
    normalized_slug = group_slug.strip().lower()
    markets = crud.get_markets_by_group_slug(session, normalized_slug)
    if not markets:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="group_not_found")
    market_models = _enrich_market_models(
        session, [schemas.MarketResponse.model_validate(m) for m in markets], include_siblings=True
    )

    def _group_sort_key(market: schemas.MarketResponse):
        position = getattr(market, "group_position", None)
        threshold = getattr(market, "group_item_threshold", None)
        closes_at = _normalize_datetime(getattr(market, "closes_at", None))
        return (
            position if position is not None else threshold if threshold is not None else float("inf"),
            closes_at or datetime.max.replace(tzinfo=UTC),
            getattr(market, "slug", None) or getattr(market, "event_id", ""),
        )

    market_models.sort(key=_group_sort_key)
    aggregate_volume = _safe_float(market_models[0].volume_24h_usd) if market_models else None
    aggregate_liquidity = _safe_float(market_models[0].liquidity_usd) if market_models else None
    return schemas.GroupedMarketsResponse(
        group_slug=normalized_slug,
        markets=market_models,
        aggregate_volume_24h_usd=aggregate_volume,
        aggregate_liquidity_usd=aggregate_liquidity,
    )


@app.get("/markets/onchain", tags=["markets"], include_in_schema=False)
async def list_onchain_markets():
    cfg = get_settings()
    try:
        addresses = await fetch_factory_markets(cfg)
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
        _enrich_market_models(session, models_from_cache)
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
    filtered = _filter_markets_for_visibility(_enrich_market_models(session, market_models))
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


@app.get("/proofs", response_model=list[schemas.ProofReceipt], tags=["proofs"], include_in_schema=False)
def list_proof_receipts(
    request: Request,
    limit: Annotated[
        int, Query(ge=1, le=settings.max_page_size, description="Maximum number of proof receipts to return")
    ] = settings.default_page_size,
    offset: Annotated[int, Query(ge=0, description="Offset into the receipts list")] = 0,
    session: Session = Depends(get_session),
) -> list[schemas.ProofReceipt]:
    start = time.perf_counter()
    cache = get_cache_client()
    cache_available = cache is not None
    bounded_limit = min(limit, settings.max_page_size)
    bounded_offset = max(0, offset)
    log_event(
        logger,
        logging.DEBUG,
        event="proofs.list.request",
        message="fetching proof receipts",
        limit=bounded_limit,
        offset=bounded_offset,
    )
    stmt = (
        select(
            shared_models.SettlementReceipt,
            shared_models.Settlement,
            shared_models.Market,
        )
        .join(
            shared_models.Settlement,
            shared_models.Settlement.market_id == shared_models.SettlementReceipt.market_id,
            isouter=True,
        )
        .join(
            shared_models.Market,
            shared_models.Market.id == shared_models.SettlementReceipt.market_id,
            isouter=True,
        )
        .order_by(
            shared_models.SettlementReceipt.generated_at.desc(),
            shared_models.SettlementReceipt.created_at.desc(),
        )
        .offset(bounded_offset)
        .limit(bounded_limit)
    )
    rows = session.execute(stmt).all()
    receipts: list[schemas.ProofReceipt] = []
    cache_hits = 0
    for receipt_row, settlement_row, market_row in rows:
        cached_payload = None
        condition_value = getattr(market_row, "condition_id", None) if market_row is not None else None
        if cache_available and condition_value:
            cached_payload = get_json(cache, proof_receipt_cache_key(str(condition_value)))
            if cached_payload is not None:
                cache_hits += 1
        receipts.append(_build_proof_receipt_model(receipt_row, settlement_row, market_row, cached_payload))
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    log_event(
        logger,
        logging.INFO,
        event="proofs.list.response",
        message="served proof receipts",
        limit=bounded_limit,
        offset=bounded_offset,
        result_count=len(receipts),
        cache_hits=cache_hits,
        duration_ms=duration_ms,
    )
    update_cache_context(request, cache_key=None, hit=cache_hits > 0, source="proofs")
    return receipts


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
        RESOLUTION_CACHE_COUNTER.labels(outcome="hit").inc()
        update_cache_context(request, cache_key=cache_key, hit=True, source="markets:resolution")
        cached_summary = schemas.ResolutionSummary.model_validate(cached)
        log_event(
            logger,
            logging.INFO,
            event="markets.resolution.cache_hit",
            message="served resolution summary from cache",
            condition_id=normalized_condition,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return cached_summary

    market = crud.get_market_by_condition_id(session, normalized_condition)
    record = crud.get_resolution_by_condition_id(session, normalized_condition)
    market_outcomes = _load_outcomes_for_market(session, market)

    summary_model: schemas.ResolutionSummary | None = None
    if record is not None:
        if market and (record.event_id is None or record.market_id is None):
            record.event_id = market.event_id
            record.market_id = market.id
        summary_model = _build_resolution_summary_from_record(
            record,
            market,
            market_outcomes=market_outcomes,
        )
    elif goldsky_client is not None:
        try:
            summary_payload: dict[str, Any] | None = cast(
                dict[str, Any] | None,
                goldsky_client.resolution_summary(
                    normalized_condition,
                    market_outcomes or None,
                    len(market_outcomes) if market_outcomes else None,
                ),
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
            if summary_payload:
                if market:
                    summary_payload.setdefault("marketId", market.id)
                    summary_payload.setdefault("eventId", market.event_id)
                    summary_payload.setdefault("title", market.title)
                    summary_payload.setdefault("slug", market.slug)
                    summary_payload.setdefault("oracle", market.oracle)
                    summary_payload.setdefault("outcomes", market_outcomes or summary_payload.get("outcomes", []))
                log_event(
                    logger,
                    logging.INFO,
                    event="markets.resolution.goldsky",
                    message="served resolution summary via goldsky fallback",
                    condition_id=normalized_condition,
                )

                try:
                    summary_model = schemas.ResolutionSummary.model_validate(summary_payload)
                    persisted_payload = {
                        "condition_id": normalized_condition,
                        "source": summary_model.source,
                        "resolved": summary_model.resolved,
                        "payouts": summary_model.payouts or [],
                        "winners": [
                            winner.model_dump() if hasattr(winner, "model_dump") else winner
                            for winner in (summary_model.winners or [])
                        ],
                        "outcomes": summary_model.outcomes or [],
                        "oracle": summary_model.oracle,
                        "question_id": summary_model.question_id,
                        "transaction_hash": summary_model.transaction_hash,
                        "block_number": summary_model.block_number,
                        "block_timestamp": summary_model.block_timestamp,
                        "winning_outcome_id": summary_model.winning_outcome_id,
                        "rake_bps": summary_model.rake_bps
                        if summary_model.rake_bps is not None
                        else getattr(market, "rake_bps", None),
                        "request_id": summary_model.request_id,
                        "checked_at": summary_model.checked_at or datetime.now(tz=UTC),
                        "market_id": getattr(market, "id", None) if market else None,
                        "event_id": getattr(market, "event_id", None) if market else None,
                    }
                    shared_repository.upsert_resolution(session, persisted_payload)
                    session.flush()
                except Exception as exc:  # pragma: no cover - defensive persistence
                    log_event(
                        logger,
                        logging.WARNING,
                        event="markets.resolution.persist_failed",
                        message="failed to persist resolution from fallback",
                        condition_id=normalized_condition,
                        error=str(exc),
                    )

    if summary_model is None:
        if record is not None:
            summary_model = _build_resolution_summary_from_record(
                record,
                market,
                market_outcomes=market_outcomes,
            )
    if summary_model is None:
        RESOLUTION_CACHE_COUNTER.labels(outcome="miss").inc()
        log_event(
            logger,
            logging.WARNING,
            event="markets.resolution.missing",
            message="resolution not found",
            condition_id=normalized_condition,
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resolution_not_found")

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
    if cache_available:
        RESOLUTION_CACHE_COUNTER.labels(outcome="miss").inc()
    else:
        RESOLUTION_CACHE_COUNTER.labels(outcome="bypass").inc()
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
        _enrich_market_models(session, [model], include_siblings=True)
        update_cache_context(request, cache_key=cache_key, hit=True, source="markets:detail")
        MARKET_DETAIL_CACHE_COUNTER.labels(outcome="hit").inc()
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
        MARKET_DETAIL_CACHE_COUNTER.labels(outcome="miss").inc()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="market_not_found")
    response = _enrich_market_models(session, [schemas.MarketResponse.model_validate(market)], include_siblings=True)[0]
    duration = (time.perf_counter() - start) * 1000
    if cache_available:
        schema_tag = get_schema_tag(cache, settings.schema_version_key)
        ttl_seconds = _resolved_cache_ttl(
            response.status, response.resolved_at if hasattr(response, "resolved_at") else None
        )
        if ttl_seconds > 0:
            set_json(cache, cache_key, response.model_dump(mode="json"), ttl_seconds)
            add_tag(cache, schema_tag, cache_key)
            add_tag(cache, f"market:{event_id}", cache_key)
            if getattr(response, "condition_id", None):
                add_tag(cache, f"resolution:{str(response.condition_id).lower()}", cache_key)
            if getattr(response, "group_slug", None):
                add_tag(cache, f"group:{str(response.group_slug)}", cache_key)
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
    if cache_available:
        MARKET_DETAIL_CACHE_COUNTER.labels(outcome="miss").inc()
    else:
        MARKET_DETAIL_CACHE_COUNTER.labels(outcome="bypass").inc()
    update_cache_context(request, cache_key=cache_key if cache_available else None, hit=False, source="markets:detail")
    return response


@app.get(
    "/clob/orderbook/{token_id}",
    response_model=schemas.ClobOrderBookResponse,
    tags=["markets"],
    include_in_schema=False,
)
def clob_order_book(token_id: str) -> schemas.ClobOrderBookResponse:
    if not settings.clob_host:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="clob_unavailable")
    try:
        client = ClobClient(str(settings.clob_host))
        summary = client.get_order_book(token_id)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="clob.orderbook.error",
            message="failed to fetch clob orderbook",
            token_id=token_id,
            error=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="clob_request_failed") from exc
    log_event(
        logger,
        logging.INFO,
        event="clob.orderbook.success",
        message="fetched clob orderbook",
        token_id=token_id,
    )
    return schemas.ClobOrderBookResponse.from_summary(summary)


@app.post(
    "/markets",
    response_model=schemas.MarketResponse,
    tags=["markets"],
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
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
    payload = market_in.model_dump()
    for legacy in ("outcomes", "outcome_prices", "tags", "clob_token_ids"):
        payload.pop(legacy, None)
    market = crud.create_or_update_market(session, schemas.MarketCreate(**payload))
    session.flush()
    event_id_value = cast(str | None, getattr(market, "event_id", None))
    _invalidate_market_cache(
        event_id_value,
        cast(str | None, getattr(market, "condition_id", None)),
        cast(str | None, getattr(market, "group_slug", None)),
    )
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
    response = _enrich_market_models(session, [schemas.MarketResponse.model_validate(market)])[0]
    return response


@app.patch(
    "/markets/{event_id}",
    response_model=schemas.MarketResponse,
    tags=["markets"],
    include_in_schema=False,
)
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
    _invalidate_market_cache(
        event_id,
        cast(str | None, getattr(market, "condition_id", None)),
        cast(str | None, getattr(market, "group_slug", None)),
    )
    duration = (time.perf_counter() - start) * 1000
    log_event(
        logger,
        logging.INFO,
        event="markets.update.success",
        message="market updated",
        event_id=event_id,
        duration_ms=round(duration, 2),
    )
    response = _enrich_market_models(session, [schemas.MarketResponse.model_validate(market)])[0]
    return response


def _market_detail_cache_key(event_id: str) -> str:
    return f"{MARKET_DETAIL_PREFIX}:{event_id}"


def _invalidate_market_cache(
    event_id: str | None = None, condition_id: str | None = None, group_slug: str | None = None
) -> None:
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
    invalidate_tag(cache, "markets:group")
    if event_id:
        invalidate_tag(cache, f"market:{event_id}")
    if condition_id:
        invalidate_tag(cache, f"resolution:{condition_id.lower()}")
    if group_slug:
        invalidate_tag(cache, f"group:{group_slug}")


_RNG = random.SystemRandom()
