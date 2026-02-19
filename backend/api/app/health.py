from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from alembic.util.exc import CommandError
from redis.exceptions import RedisError
from shared.cache_async import get_stats_client
from shared.logging import log_event
from shared.migrations import get_current_revision, get_head_revision
from shared.onchain.client import load_account
from shared.polymarket import build_polymarket_markets_url
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from . import schemas
from .cache import get_redis_client
from .config import Settings, get_settings
from .runtime import load_shed_state

ComponentMap = dict[str, schemas.HealthComponent]
health_logger = logging.getLogger("reveal_market.api.health")


_HEALTH_CACHE: dict[str, tuple[float, schemas.HealthResponse]] = {}
_HEALTH_DEEP_CACHE: dict[str, tuple[float, schemas.HealthResponse]] = {}


async def build_health_response(session: AsyncSession) -> schemas.HealthResponse:
    """Compatibility wrapper for /healthz (shallow)."""

    return await build_shallow_health_response()


async def build_shallow_health_response() -> schemas.HealthResponse:
    settings = get_settings()
    ttl = max(getattr(settings, "health_cache_ttl_seconds", 0) or 0, 0)
    if (settings.environment or "").lower() in {"test", "testing"}:
        ttl = 0
    cache_key = "health:shallow"
    if ttl > 0:
        now = time.monotonic()
        cached = _HEALTH_CACHE.get(cache_key)
        if cached and now < cached[0]:
            return cached[1]

    components: ComponentMap = {}
    component_states: list[str] = []
    try:
        redis_client = get_redis_client()
        cache_key = f"health:shallow:{'redis' if redis_client is not None else 'no_redis'}"
    except Exception:
        cache_key = "health:shallow:no_redis"

    deep_snapshot = await _get_cached_deep_snapshot(redis_client)
    if deep_snapshot is not None:
        components = deep_snapshot.components
        component_states = [component.status for component in components.values()]
    overall_status = _derive_overall_status(component_states) if component_states else "ok"

    response = schemas.HealthResponse(
        status=overall_status,
        service=settings.app_name,
        version=settings.version,
        timestamp=datetime.now(tz=UTC),
        components=components,
        cache_stats=None,
    )
    if ttl > 0:
        _HEALTH_CACHE[cache_key] = (time.monotonic() + ttl, response)
    return response


async def build_deep_health_response(session: AsyncSession, *, force: bool = False) -> schemas.HealthResponse:
    settings = get_settings()
    """Aggregate health information from core dependencies."""

    ttl = max(getattr(settings, "health_deep_cache_ttl_seconds", 0) or 0, 0)
    if (settings.environment or "").lower() in {"test", "testing"}:
        ttl = 0
    cache_key = "health:deep"
    redis_client = None
    try:
        redis_client = get_redis_client()
        cache_key = f"health:deep:{'redis' if redis_client is not None else 'no_redis'}"
    except Exception:
        cache_key = "health:deep:no_redis"

    if ttl > 0 and not force:
        cached = _HEALTH_DEEP_CACHE.get(cache_key)
        if cached and time.monotonic() < cached[0]:
            return cached[1]
        if redis_client is not None:
            try:
                payload = await redis_client.get("health:deep:snapshot")
                if payload:
                    parsed = json.loads(payload)
                    response = schemas.HealthResponse.model_validate(parsed)
                    _HEALTH_DEEP_CACHE[cache_key] = (time.monotonic() + ttl, response)
                    return response
            except Exception as exc:
                log_event(
                    health_logger,
                    logging.DEBUG,
                    event="health.deep.cache.read_failed",
                    message=str(exc),
                )

    components: ComponentMap = {}
    component_states: list[str] = []

    checks: list[tuple[str, schemas.HealthComponent]] = [
        await _check_database(session),
        await _check_redis_connectivity(),
        await _check_worker_heartbeat(settings),
        await _check_polymarket_api(settings),
        await _check_pricing_signer(settings),
        _check_cors(settings),
        _check_fx_cors(settings),
        await _check_schema_revision(settings),
    ]

    for key, component in checks:
        components[key] = component
        component_states.append(component.status)

    overall_status = _derive_overall_status(component_states)

    try:
        stats_client = get_stats_client()
        cache_stats = stats_client.snapshot() if stats_client else None
    except (RuntimeError, AttributeError, ValueError, OSError) as exc:  # pragma: no cover - defensive log
        log_event(health_logger, logging.WARNING, event="health.cache.stats.error", message=str(exc))
        cache_stats = None

    response = schemas.HealthResponse(
        status=overall_status,
        service=settings.app_name,
        version=settings.version,
        timestamp=datetime.now(tz=UTC),
        components=components,
        cache_stats=cache_stats,
    )
    if ttl > 0:
        _HEALTH_DEEP_CACHE[cache_key] = (time.monotonic() + ttl, response)
        if redis_client is not None:
            try:
                await redis_client.set(
                    "health:deep:snapshot",
                    response.model_dump_json(),
                    ex=ttl,
                )
            except Exception as exc:
                log_event(
                    health_logger,
                    logging.DEBUG,
                    event="health.deep.cache.write_failed",
                    message=str(exc),
                )
    return response


async def _get_cached_deep_snapshot(redis_client) -> schemas.HealthResponse | None:
    if redis_client is None:
        return None
    try:
        payload = await redis_client.get("health:deep:snapshot")
        if payload:
            parsed = json.loads(payload)
            return schemas.HealthResponse.model_validate(parsed)
    except Exception:
        return None
    return None


def _derive_overall_status(states: list[str]) -> schemas.HealthState:
    if not states:
        return "ok"
    if "error" in states:
        return "error"
    if "degraded" in states:
        return "degraded"
    return "ok"


async def _check_database(session: AsyncSession) -> tuple[str, schemas.HealthComponent]:
    db_start = time.perf_counter()
    try:
        await session.execute(text("SELECT 1"))
        db_latency = (time.perf_counter() - db_start) * 1000
        component = schemas.HealthComponent(status="ok", latency_ms=db_latency)
        load_shed_state.record_db_success()
    except (SQLAlchemyError, TypeError) as exc:  # pragma: no cover - defensive
        component = schemas.HealthComponent(status="error", detail=str(exc))
        load_shed_state.record_db_failure()
    return "database", component


async def _check_redis_connectivity() -> tuple[str, schemas.HealthComponent]:
    redis_start = time.perf_counter()
    try:
        redis_client = get_redis_client()
        if redis_client is None:
            raise RedisError("redis client unavailable")
        await redis_client.ping()
        redis_latency = (time.perf_counter() - redis_start) * 1000
        component = schemas.HealthComponent(status="ok", latency_ms=redis_latency)
        load_shed_state.record_cache_success()
    except RedisError as exc:
        component = schemas.HealthComponent(status="error", detail=str(exc))
        load_shed_state.record_cache_failure()
    except (TypeError, ValueError, OSError) as exc:  # pragma: no cover - defensive
        component = schemas.HealthComponent(status="error", detail=str(exc))
        load_shed_state.record_cache_failure()
    return "redis", component


async def _check_worker_heartbeat(settings: Settings) -> tuple[str, schemas.HealthComponent]:
    try:
        redis_client = get_redis_client()
        if redis_client is None:
            raise RedisError("redis client unavailable")
        heartbeat_raw = await redis_client.get(settings.heartbeat_key)
        if heartbeat_raw:
            heartbeat_payload = heartbeat_raw.decode() if isinstance(heartbeat_raw, bytes) else str(heartbeat_raw)
            heartbeat = json.loads(heartbeat_payload)
            component = schemas.HealthComponent(
                status="ok",
                detail=f"processed {heartbeat.get('markets_processed', 0)} markets",
                latency_ms=heartbeat.get("latency_ms"),
            )
        else:
            component = schemas.HealthComponent(status="degraded", detail="heartbeat missing")
    except (RedisError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        component = schemas.HealthComponent(status="error", detail=str(exc))
    return "worker", component


async def _check_polymarket_api(settings: Settings) -> tuple[str, schemas.HealthComponent]:
    http_start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=settings.polymarket_timeout_seconds) as client:
            base = str(settings.polymarket_api_base).rstrip("/")
            markets_url = build_polymarket_markets_url(base)
            await client.get(
                base,
                timeout=settings.polymarket_timeout_seconds,
            )
            params: dict[str, str | int] = {
                "limit": 1,
                "order": settings.polymarket_order,
                "ascending": str(settings.polymarket_sort_ascending).lower(),
            }
            if settings.polymarket_only_open_markets is True:
                params["closed"] = "false"
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
    return "polymarket_api", component


async def _check_pricing_signer(settings: Settings) -> tuple[str, schemas.HealthComponent]:
    """Smoke-test pricing signer envs so signed quotes and trade commits can function."""

    status: schemas.HealthState = "ok"
    details: list[str] = []
    derived_chain = settings.pricing_chain_id
    derived_address: str | None = None

    if settings.pricing_chain_id is None:
        status = "error"
        details.append("RM_PRICING_CHAIN_ID missing")

    if settings.pricing_signer_private_key is None:
        status = "error"
        details.append("RM_PRICING_SIGNER_PRIVATE_KEY missing")
    else:
        try:
            acct = await asyncio.to_thread(load_account, settings.pricing_signer_private_key.get_secret_value())
            derived_address = acct.address
        except (ValueError, RuntimeError) as exc:  # pragma: no cover - defensive
            status = "error"
            details.append(f"signer load failed: {exc}")

    env_chain = os.getenv("RM_PRICING_CHAIN_ID")
    if env_chain and derived_chain is not None:
        try:
            if int(env_chain) != int(derived_chain):
                status = "error"
                details.append("RM_PRICING_CHAIN_ID mismatch with env")
        except ValueError:  # pragma: no cover - defensive
            status = "error"
            details.append("RM_PRICING_CHAIN_ID env malformed")

    if settings.rpc_url is None:
        status = "error"
        details.append("RPC_URL missing")

    env_addr = os.getenv("PRICING_SIGNER_ADDRESS")
    if not env_addr:
        status = "error"
        details.append("PRICING_SIGNER_ADDRESS missing")
    if env_addr and derived_address:
        if derived_address.lower() != env_addr.lower():
            status = "error"
            details.append("PRICING_SIGNER_ADDRESS mismatch with derived key")

    summary = f"derived_chain_id={derived_chain}; derived_signer={derived_address or 'unknown'}"
    detail_text = summary if not details else f"{summary} | " + "; ".join(details)
    return "pricing_signer", schemas.HealthComponent(status=status, detail=detail_text)


def _check_cors(settings) -> tuple[str, schemas.HealthComponent]:
    """Warn when CORS is effectively wildcard to catch misconfiguration before prod."""

    origins = settings.cors_allow_origins or []
    is_prod = (settings.environment or "").lower() == "production"
    if (origins == ["*"] or not origins) and is_prod:
        return (
            "cors",
            schemas.HealthComponent(
                status="degraded",
                detail="cors_allow_origins wildcard; set explicit origins for production",
            ),
        )
    detail = (
        "cors_allow_origins configured"
        if origins
        else "cors_allow_origins wildcard; set explicit origins for production"
    )
    return "cors", schemas.HealthComponent(status="ok", detail=detail)


def _check_fx_cors(settings) -> tuple[str, schemas.HealthComponent]:
    """Warn when FX endpoint host is not covered by CORS origins."""

    origins = settings.cors_allow_origins or []
    fx_url = settings.fx_feed_url
    parsed = urlparse(str(fx_url))
    fx_origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else None
    internal_hosts = {"streamer", "localhost", "127.0.0.1"}
    is_prod = (settings.environment or "").lower() == "production"
    if not fx_origin:
        return "fx_cors", schemas.HealthComponent(status="error", detail="FX feed URL invalid")
    if parsed.hostname in internal_hosts:
        return "fx_cors", schemas.HealthComponent(status="ok", detail="FX feed uses internal host")
    if not origins or origins == ["*"]:
        state: schemas.HealthState = "degraded" if is_prod else "ok"
        detail = "CORS origins wildcard; streamer FX origin not explicitly allowed"
        return "fx_cors", schemas.HealthComponent(status=state, detail=detail)
    if fx_origin not in origins:
        state = "degraded" if is_prod else "ok"
        detail = f"FX origin {fx_origin} not in CORS allowlist"
        return "fx_cors", schemas.HealthComponent(status=state, detail=detail)
    return "fx_cors", schemas.HealthComponent(status="ok", detail="FX origin allowed by CORS")


async def _check_schema_revision(settings: Settings) -> tuple[str, schemas.HealthComponent]:
    """Ensure the DB is at Alembic head so normalized tables exist."""

    if str(settings.database_url).startswith("sqlite"):
        return "schema", schemas.HealthComponent(status="ok", detail="sqlite database; skipping Alembic check")

    try:
        current = await asyncio.to_thread(get_current_revision, settings.database_url)
        head = await asyncio.to_thread(get_head_revision)
        if head is None:
            return "schema", schemas.HealthComponent(status="degraded", detail="Alembic head unknown")
        if current != head:
            return (
                "schema",
                schemas.HealthComponent(
                    status="degraded",
                    detail=f"schema revision mismatch (current={current}, head={head})",
                ),
            )
    except (SQLAlchemyError, CommandError, RuntimeError) as exc:  # pragma: no cover - defensive
        return "schema", schemas.HealthComponent(status="error", detail=str(exc))
    return "schema", schemas.HealthComponent(status="ok", detail="schema at head")
