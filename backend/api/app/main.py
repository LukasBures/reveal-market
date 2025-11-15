from __future__ import annotations

import json
import logging
import re
import time
from contextlib import asynccontextmanager
from threading import Event, Lock
from typing import Annotated, Any
from urllib.parse import unquote_plus
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator
from shared.cache import add_tag, add_tags, get_client, get_json, get_schema_tag, invalidate_tag, set_json
from shared.cache_keys import (
    category_cache_key,
    markets_list_cache_key,
    resolution_cache_key,
    suggest_cache_key,
    tag_cache_key,
)
from shared.categories import canonical_category_from_slug
from shared.logging import log_event, reset_request_id, set_request_id, start_heartbeat_logger
from shared.onchain import OnChainConfigurationError
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import crud, schemas
from app.config import get_settings
from app.database import get_session, run_migrations
from app.health import build_health_response
from app.logging_config import setup_logging
from app.onchain import fetch_factory_markets
from app.security import SecurityHeadersMiddleware

try:
    from redis import Redis
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - redis is an optional dependency during certain tests
    Redis = Any  # type: ignore
    RedisError = Exception  # type: ignore

CANONICAL_TAGS = {
    "gov-shutdown": "Gov shutdown",
    "fed-policy": "Fed policy",
    "eu-elections": "EU elections",
    "btc-halving": "BTC halving",
    "ai-regulation": "AI regulation",
    "climate": "Climate",
}

setup_logging("reveal_market.api")

settings = get_settings()
logger = logging.getLogger("reveal_market.api")
instrumentator = Instrumentator()
cache_client: Redis | None = None
_cache_lock = Lock()
_heartbeat_stop_event: Event | None = None

MARKETS_STATS_KEY = "markets:stats"
MARKET_DETAIL_PREFIX = "markets:detail"
MARKET_RESOLUTION_PREFIX = "markets:resolution"

MARKETS_CACHE_COUNTER = Counter(
    "markets_cache_requests_total",
    "Cache hits and misses for /markets",
    ["outcome", "status", "category"],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _heartbeat_stop_event
    run_migrations()
    _heartbeat_stop_event = start_heartbeat_logger(
        logger,
        settings.app_name,
        interval_seconds=settings.container_heartbeat_seconds,
        message=f"{settings.app_name} container heartbeat",
    )
    yield
    if _heartbeat_stop_event is not None:
        _heartbeat_stop_event.set()
        _heartbeat_stop_event = None


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


def _filter_markets_for_visibility(markets: list[schemas.MarketResponse]) -> list[schemas.MarketResponse]:
    category_allow = {item.lower() for item in settings.market_category_allowlist if isinstance(item, str)}
    tag_allow = {item.lower() for item in settings.market_tag_allowlist if isinstance(item, str)}
    if not category_allow and not tag_allow:
        return markets

    filtered: list[schemas.MarketResponse] = []
    for market in markets:
        category_ok = True
        if category_allow:
            category_ok = isinstance(market.category, str) and market.category.lower() in category_allow

        tags_ok = True
        if tag_allow:
            tags = [tag.lower() for tag in (market.tags or []) if isinstance(tag, str)]
            tags_ok = any(tag in tag_allow for tag in tags)

        if category_ok and tags_ok:
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
            tag_allowlist=list(tag_allow),
        )
    return filtered


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
        tag_values = getattr(candidate, "tags", None)
        matched_slug = _slugify(str(category_value)) == normalized
        if not matched_slug and isinstance(tag_values, list):
            for tag in tag_values:
                if isinstance(tag, str) and _slugify(tag) == normalized:
                    matched_slug = True
                    break
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


def _canonical_tag_lookup(raw: str) -> tuple[str, str] | None:
    slug = _slugify(raw)
    label = CANONICAL_TAGS.get(slug)
    if label:
        return slug, label
    return None


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid4())
    token = set_request_id(request_id)
    start_time = time.perf_counter()
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
        log_event(
            logger,
            logging.WARNING if 400 <= exc.status_code < 500 else logging.ERROR,
            event="http.request.error",
            message="request failed",
            path=request.url.path,
            method=request.method,
            status_code=exc.status_code,
            duration_ms=round(duration_ms, 2),
        )
        reset_request_id(token)
        raise
    except Exception:
        duration_ms = (time.perf_counter() - start_time) * 1000
        log_event(
            logger,
            logging.ERROR,
            event="http.request.error",
            message="request failed",
            path=request.url.path,
            method=request.method,
            status_code=500,
            duration_ms=round(duration_ms, 2),
        )
        reset_request_id(token)
        raise
    duration_ms = (time.perf_counter() - start_time) * 1000
    response.headers["x-request-id"] = request_id
    log_event(
        logger,
        logging.INFO,
        event="http.request.completed",
        message="request completed",
        path=request.url.path,
        method=request.method,
        status_code=response.status_code,
        duration_ms=round(duration_ms, 2),
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


@app.get("/markets", response_model=list[schemas.MarketResponse], tags=["markets"])
def list_markets(
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
    cached = get_json(cache, cache_key)
    if cached is not None:
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
            result_count=len(cached),
        )
        cached_models = [schemas.MarketResponse.model_validate(item) for item in cached]
        _augment_market_models(cached_models)
        return _filter_markets_for_visibility(cached_models)

    MARKETS_CACHE_COUNTER.labels(outcome="miss", status=status or "*", category=category or "*").inc()
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
    payload = [item.model_dump(mode="json") for item in market_models]
    schema_tag = get_schema_tag(cache, settings.schema_version_key)
    set_json(cache, cache_key, payload, settings.cache_ttl_seconds)
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
        search=search,
        limit=limit,
        offset=offset,
        result_count=len(market_models),
    )
    return market_models


@app.get("/categories/{category_slug}", response_model=list[schemas.MarketResponse], tags=["markets"])
def list_markets_by_category(
    category_slug: str,
    limit: Annotated[
        int,
        Query(ge=1, le=settings.max_page_size, description="Maximum number of markets to return"),
    ] = settings.default_page_size,
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
    cache_key = category_cache_key(category_slug_key, limit)
    cached = get_json(cache, cache_key)
    if cached is not None:
        models_from_cache = _filter_markets_for_visibility(
            _augment_market_models([schemas.MarketResponse.model_validate(item) for item in cached])
        )
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
    )
    if trending_category:
        markets = crud.get_markets(session, limit=limit, offset=0)
    else:
        markets = crud.get_markets(session, category=category_label, limit=limit, offset=0)
    market_models = _filter_markets_for_visibility(
        _augment_market_models([schemas.MarketResponse.model_validate(m) for m in markets])
    )
    if not market_models and not trending_category:
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
        )
    payload = [item.model_dump(mode="json") for item in market_models]
    schema_tag = get_schema_tag(cache, settings.schema_version_key)
    set_json(cache, cache_key, payload, settings.cache_ttl_seconds)
    add_tag(cache, schema_tag, cache_key)
    add_tag(cache, "markets:category", cache_key)
    add_tag(cache, f"category:{category_slug_key}", cache_key)
    log_event(
        logger,
        logging.INFO,
        event="markets.category.cache_miss",
        message="cached category markets",
        category_slug=category_slug_key,
        limit=limit,
        result_count=len(market_models),
        duration_ms=round((time.perf_counter() - start) * 1000, 2),
    )
    return market_models


@app.get("/tags/{tag_slug}", response_model=list[schemas.MarketResponse], tags=["markets"])
def list_markets_by_tag(
    tag_slug: str,
    limit: Annotated[
        int,
        Query(ge=1, le=settings.max_page_size, description="Maximum number of markets to return"),
    ] = settings.default_page_size,
    session: Session = Depends(get_session),
) -> list[schemas.MarketResponse]:
    start = time.perf_counter()
    cache = get_cache_client()
    log_event(
        logger,
        logging.DEBUG,
        event="markets.tag.request",
        message="processing tag listing",
        tag_slug=tag_slug,
        limit=limit,
    )
    tag_value = _decode_slug(tag_slug)
    lookup = _canonical_tag_lookup(tag_value)
    if lookup is None:
        log_event(
            logger,
            logging.WARNING,
            event="markets.tag.invalid_slug",
            message="tag slug not recognized",
            tag_slug=tag_slug,
            limit=limit,
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tag_not_found")
    tag_slug_key, tag_label = lookup
    cache_key = tag_cache_key(tag_slug_key, limit)
    cached = get_json(cache, cache_key)
    if cached is not None:
        models_from_cache = _filter_markets_for_visibility(
            _augment_market_models([schemas.MarketResponse.model_validate(item) for item in cached])
        )
        log_event(
            logger,
            logging.INFO,
            event="markets.tag.cache_hit",
            message="served tag markets from cache",
            tag_slug=tag_slug_key,
            limit=limit,
            result_count=len(models_from_cache),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return models_from_cache

    markets = crud.get_markets_by_tag(session, tag_label, limit)
    market_models = _filter_markets_for_visibility(
        _augment_market_models([schemas.MarketResponse.model_validate(m) for m in markets])
    )
    if not market_models:
        log_event(
            logger,
            logging.INFO,
            event="markets.tag.empty",
            message="no markets available for tag",
            tag_slug=tag_slug_key,
            limit=limit,
        )
    payload = [item.model_dump(mode="json") for item in market_models]
    schema_tag = get_schema_tag(cache, settings.schema_version_key)
    set_json(cache, cache_key, payload, settings.cache_ttl_seconds)
    add_tag(cache, schema_tag, cache_key)
    add_tag(cache, "markets:tag", cache_key)
    add_tag(cache, f"tag:{tag_slug_key}", cache_key)
    log_event(
        logger,
        logging.INFO,
        event="markets.tag.cache_miss",
        message="cached tag markets",
        tag_slug=tag_slug_key,
        limit=limit,
        result_count=len(market_models),
        duration_ms=round((time.perf_counter() - start) * 1000, 2),
    )
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
def market_stats(session: Session = Depends(get_session)) -> list[schemas.MarketStatusBreakdown]:
    start = time.perf_counter()
    cache = get_cache_client()
    log_event(logger, logging.DEBUG, "markets.stats.request", "processing market stats request")
    cached = get_json(cache, MARKETS_STATS_KEY)
    if cached is not None:
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
    schema_tag = get_schema_tag(cache, settings.schema_version_key)
    set_json(cache, MARKETS_STATS_KEY, payload, settings.cache_ttl_seconds)
    add_tag(cache, schema_tag, MARKETS_STATS_KEY)
    add_tag(cache, "markets:stats", MARKETS_STATS_KEY)
    duration = (time.perf_counter() - start) * 1000
    log_event(
        logger,
        logging.INFO,
        event="markets.stats.cache_miss",
        message="cached fresh market stats",
        cache_hit=False,
        duration_ms=round(duration, 2),
        result_count=len(stats),
    )
    return stats


@app.get("/markets/suggest", response_model=list[schemas.MarketResponse], tags=["markets"])
def suggest_markets(
    q: Annotated[str, Query(min_length=2, max_length=200, description="Search term for suggestions")],
    limit: Annotated[int, Query(ge=1, le=25, description="Maximum number of suggestions to return")] = 5,
    session: Session = Depends(get_session),
) -> list[schemas.MarketResponse]:
    start = time.perf_counter()
    cache = get_cache_client()
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
    return filtered


@app.get("/resolution/{condition_id_hex}", response_model=schemas.ResolutionSummary, tags=["markets"])
def read_resolution(condition_id_hex: str, session: Session = Depends(get_session)) -> schemas.ResolutionSummary:
    start = time.perf_counter()
    cache = get_cache_client()
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

    record = crud.get_resolution_by_condition_id(session, normalized_condition)
    if record is None:
        log_event(
            logger,
            logging.WARNING,
            event="markets.resolution.missing",
            message="resolution not found",
            condition_id=normalized_condition,
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resolution_not_found")

    summary: dict[str, Any] = {
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

    market = crud.get_market_by_condition_id(session, normalized_condition)
    if market:
        summary.update(
            {
                "marketId": market.id,
                "eventId": market.event_id,
                "title": market.title,
                "slug": market.slug,
                "outcomes": market.outcomes or summary["outcomes"],
            }
        )

    summary_model = schemas.ResolutionSummary.model_validate(summary)
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
    return summary_model


@app.get("/markets/{event_id}", response_model=schemas.MarketResponse, tags=["markets"])
def read_market(event_id: str, session: Session = Depends(get_session)) -> schemas.MarketResponse:
    cache_key = _market_detail_cache_key(event_id)
    cache = get_cache_client()
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
    schema_tag = get_schema_tag(cache, settings.schema_version_key)
    set_json(cache, cache_key, response.model_dump(mode="json"), settings.cache_ttl_seconds)
    add_tag(cache, schema_tag, cache_key)
    add_tag(cache, f"market:{event_id}", cache_key)
    duration = (time.perf_counter() - start) * 1000
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
