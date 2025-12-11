from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from inspect import isawaitable
from json import JSONDecodeError
from urllib.parse import urlparse

import httpx
from alembic.util.exc import CommandError
from redis.exceptions import RedisError
from shared.cache import get_stats_client
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

ComponentMap = dict[str, schemas.HealthComponent]
health_logger = logging.getLogger("reveal_market.api.health")


async def build_health_response(session: AsyncSession) -> schemas.HealthResponse:
    """Aggregate health information from core dependencies."""

    settings = get_settings()
    components: ComponentMap = {}
    component_states: list[str] = []

    checks: list[tuple[str, schemas.HealthComponent]] = [
        await _check_database(session),
        _check_redis_connectivity(),
        _check_worker_heartbeat(settings),
        await _check_polymarket_api(settings),
        _check_pricing_signer(settings),
        _check_cors(settings),
        _check_fx_cors(settings),
        _check_schema_revision(settings),
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

    return schemas.HealthResponse(
        status=overall_status,
        service=settings.app_name,
        version=settings.version,
        timestamp=datetime.now(tz=UTC),
        components=components,
        cache_stats=cache_stats,
    )


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
    except (SQLAlchemyError, TypeError) as exc:  # pragma: no cover - defensive
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
    except (TypeError, ValueError, OSError) as exc:  # pragma: no cover - defensive
        component = schemas.HealthComponent(status="error", detail=str(exc))
    return "redis", component


def _check_worker_heartbeat(settings: Settings) -> tuple[str, schemas.HealthComponent]:
    try:
        redis_client = get_redis_client()
        heartbeat_raw = redis_client.get(settings.heartbeat_key)
        if isawaitable(heartbeat_raw):
            raise TypeError("redis client returned awaitable")
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
    except (RedisError, TypeError, JSONDecodeError, UnicodeDecodeError) as exc:
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
            if settings.polymarket_closed_filter is not None:
                params["closed"] = str(settings.polymarket_closed_filter).lower()
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


def _check_pricing_signer(settings: Settings) -> tuple[str, schemas.HealthComponent]:
    """Smoke-test pricing signer envs so signed quotes/commitWithQuote can function."""

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
            acct = load_account(settings.pricing_signer_private_key.get_secret_value())
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
    is_prod = (settings.environment or "").lower() == "production"
    if not fx_origin:
        return "fx_cors", schemas.HealthComponent(status="error", detail="FX feed URL invalid")
    if not origins or origins == ["*"]:
        state: schemas.HealthState = "degraded" if is_prod else "ok"
        detail = "CORS origins wildcard; streamer FX origin not explicitly allowed"
        return "fx_cors", schemas.HealthComponent(status=state, detail=detail)
    if fx_origin not in origins:
        state = "degraded" if is_prod else "ok"
        detail = f"FX origin {fx_origin} not in CORS allowlist"
        return "fx_cors", schemas.HealthComponent(status=state, detail=detail)
    return "fx_cors", schemas.HealthComponent(status="ok", detail="FX origin allowed by CORS")


def _check_schema_revision(settings: Settings) -> tuple[str, schemas.HealthComponent]:
    """Ensure the DB is at Alembic head so normalized tables exist."""

    if str(settings.database_url).startswith("sqlite"):
        return "schema", schemas.HealthComponent(status="ok", detail="sqlite database; skipping Alembic check")

    try:
        current = get_current_revision(settings.database_url)
        head = get_head_revision()
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
