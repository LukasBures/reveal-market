from __future__ import annotations

import logging
import re
import time
from contextlib import asynccontextmanager
from typing import Annotated, Any, Optional
from urllib.parse import unquote_plus
from uuid import uuid4

from app import crud, schemas
from app.config import get_settings
from app.database import get_session, run_migrations
from app.health import build_health_response
from app.logging_config import setup_logging
from app.onchain import fetch_factory_markets
from app.security import SecurityHeadersMiddleware
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
from shared.logging import log_event, reset_request_id, set_request_id
from shared.onchain import OnChainConfigurationError
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

CANONICAL_CATEGORIES = {
    "trending": "Trending",
    "politics": "Politics",
    "sports": "Sports",
    "finance": "Finance",
    "crypto": "Crypto",
    "geopolitics": "Geopolitics",
    "ai-tech": "AI & Tech",
}

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
cache_client = get_client(settings.redis_url)

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
    run_migrations()
    yield


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
    api_csp = (
        "default-src 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'none'; "
        "base-uri 'none'; "
        "connect-src 'self';"
    )
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


def _filter_markets_for_visibility(markets: list[schemas.MarketRead]) -> list[schemas.MarketRead]:
    category_allow = {item.lower() for item in settings.market_category_allowlist if isinstance(item, str)}
    tag_allow = {item.lower() for item in settings.market_tag_allowlist if isinstance(item, str)}
    if not category_allow and not tag_allow:
        return markets

    filtered: list[schemas.MarketRead] = []
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


def _canonical_category_lookup(raw: str) -> tuple[str, str] | None:
    slug = _slugify(raw)
    label = CANONICAL_CATEGORIES.get(slug)
    if label:
        return slug, label
    return None


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
    except Exception as exc:
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
        raise exc
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


@app.get("/markets", response_model=list[schemas.MarketRead], tags=["markets"])
def list_markets(
    status: Annotated[Optional[str], Query(description="Filter markets by status")] = None,
    category: Annotated[Optional[str], Query(description="Filter markets by category")] = None,
    oracle: Annotated[Optional[str], Query(description="Filter markets by oracle address")] = None,
    search: Annotated[
        Optional[str],
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
) -> list[schemas.MarketRead]:
    cache_key = markets_list_cache_key(status, category, oracle, search, limit, offset)
    log_event(
        logger,
        logging.DEBUG,
        event="markets.list.request",
        message="processing markets list request",
        cache_key=cache_key,
        status=status,
        category=category,
        oracle=oracle,
        search=search,
        limit=limit,
        offset=offset,
    )
    start = time.perf_counter()
    cached = get_json(cache_client, cache_key)
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
            search=search,
            limit=limit,
            offset=offset,
            result_count=len(cached),
        )
        cached_models = [schemas.MarketRead.model_validate(item) for item in cached]
        return _filter_markets_for_visibility(cached_models)

    MARKETS_CACHE_COUNTER.labels(outcome="miss", status=status or "*", category=category or "*").inc()
    markets = crud.get_markets(
        session,
        status=status,
        category=category,
        oracle=oracle,
        search=search,
        limit=limit,
        offset=offset,
    )
    market_models = [schemas.MarketRead.model_validate(m) for m in markets]
    market_models = _filter_markets_for_visibility(market_models)
    payload = [item.model_dump(mode="json") for item in market_models]
    schema_tag = get_schema_tag(cache_client, settings.schema_version_key)
    set_json(cache_client, cache_key, payload, settings.cache_ttl_seconds)
    add_tag(cache_client, schema_tag, cache_key)
    add_tag(cache_client, "markets:list", cache_key)
    add_tags(
        cache_client,
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


@app.get("/categories/{category_slug}", response_model=list[schemas.MarketRead], tags=["markets"])
def list_markets_by_category(
    category_slug: str,
    limit: Annotated[
        int,
        Query(ge=1, le=settings.max_page_size, description="Maximum number of markets to return"),
    ] = settings.default_page_size,
    session: Session = Depends(get_session),
) -> list[schemas.MarketRead]:
    category_value = _decode_slug(category_slug)
    lookup = _canonical_category_lookup(category_value)
    if lookup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="category_not_found")
    category_slug_key, category_label = lookup
    cache_key = category_cache_key(category_slug_key, limit)
    cached = get_json(cache_client, cache_key)
    if cached is not None:
        return [schemas.MarketRead.model_validate(item) for item in cached]

    markets = crud.get_markets(session, category=category_label, limit=limit, offset=0)
    market_models = _filter_markets_for_visibility([schemas.MarketRead.model_validate(m) for m in markets])
    payload = [item.model_dump(mode="json") for item in market_models]
    schema_tag = get_schema_tag(cache_client, settings.schema_version_key)
    set_json(cache_client, cache_key, payload, settings.cache_ttl_seconds)
    add_tag(cache_client, schema_tag, cache_key)
    add_tag(cache_client, "markets:category", cache_key)
    add_tag(cache_client, f"category:{category_slug_key}", cache_key)
    return market_models


@app.get("/tags/{tag_slug}", response_model=list[schemas.MarketRead], tags=["markets"])
def list_markets_by_tag(
    tag_slug: str,
    limit: Annotated[
        int,
        Query(ge=1, le=settings.max_page_size, description="Maximum number of markets to return"),
    ] = settings.default_page_size,
    session: Session = Depends(get_session),
) -> list[schemas.MarketRead]:
    tag_value = _decode_slug(tag_slug)
    lookup = _canonical_tag_lookup(tag_value)
    if lookup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tag_not_found")
    tag_slug_key, tag_label = lookup
    cache_key = tag_cache_key(tag_slug_key, limit)
    cached = get_json(cache_client, cache_key)
    if cached is not None:
        return [schemas.MarketRead.model_validate(item) for item in cached]

    markets = crud.get_markets_by_tag(session, tag_label, limit)
    market_models = _filter_markets_for_visibility([schemas.MarketRead.model_validate(m) for m in markets])
    payload = [item.model_dump(mode="json") for item in market_models]
    schema_tag = get_schema_tag(cache_client, settings.schema_version_key)
    set_json(cache_client, cache_key, payload, settings.cache_ttl_seconds)
    add_tag(cache_client, schema_tag, cache_key)
    add_tag(cache_client, "markets:tag", cache_key)
    add_tag(cache_client, f"tag:{tag_slug_key}", cache_key)
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
    log_event(logger, logging.DEBUG, "markets.stats.request", "processing market stats request")
    cached = get_json(cache_client, MARKETS_STATS_KEY)
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
    schema_tag = get_schema_tag(cache_client, settings.schema_version_key)
    set_json(cache_client, MARKETS_STATS_KEY, payload, settings.cache_ttl_seconds)
    add_tag(cache_client, schema_tag, MARKETS_STATS_KEY)
    add_tag(cache_client, "markets:stats", MARKETS_STATS_KEY)
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


@app.get("/markets/suggest", response_model=list[schemas.MarketRead], tags=["markets"])
def suggest_markets(
    q: Annotated[str, Query(min_length=2, max_length=200, description="Search term for suggestions")],
    limit: Annotated[int, Query(ge=1, le=25, description="Maximum number of suggestions to return")] = 5,
    session: Session = Depends(get_session),
) -> list[schemas.MarketRead]:
    normalized_query = q.strip()
    cache_key = suggest_cache_key(normalized_query, limit)
    cached = get_json(cache_client, cache_key)
    if cached is not None:
        return [schemas.MarketRead.model_validate(item) for item in cached]

    results = crud.search_markets(session, normalized_query, limit)
    market_models = [schemas.MarketRead.model_validate(m) for m in results]
    filtered = _filter_markets_for_visibility(market_models)
    payload = [item.model_dump(mode="json") for item in filtered]
    schema_tag = get_schema_tag(cache_client, settings.schema_version_key)
    set_json(cache_client, cache_key, payload, settings.cache_ttl_seconds)
    add_tag(cache_client, schema_tag, cache_key)
    add_tag(cache_client, "markets:suggest", cache_key)
    return filtered


@app.get("/resolution/{condition_id_hex}", response_model=schemas.ResolutionSummary, tags=["markets"])
def read_resolution(condition_id_hex: str, session: Session = Depends(get_session)) -> schemas.ResolutionSummary:
    normalized_condition = condition_id_hex.lower()
    cache_key = resolution_cache_key(normalized_condition)
    cached = get_json(cache_client, cache_key)
    if cached is not None:
        return schemas.ResolutionSummary.model_validate(cached)

    record = crud.get_resolution_by_condition_id(session, normalized_condition)
    if record is None:
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
    cache_payload = summary_model.model_dump(mode="json")
    if summary_model.checkedAt is not None:
        cache_payload["checkedAt"] = summary_model.checkedAt.isoformat()
    if summary_model.blockTimestamp is not None:
        cache_payload["blockTimestamp"] = summary_model.blockTimestamp.isoformat()
    schema_tag = get_schema_tag(cache_client, settings.schema_version_key)
    set_json(cache_client, cache_key, cache_payload, settings.cache_ttl_seconds)
    add_tag(cache_client, schema_tag, cache_key)
    add_tag(cache_client, f"resolution:{normalized_condition}", cache_key)
    return summary_model


@app.get("/markets/{event_id}", response_model=schemas.MarketRead, tags=["markets"])
def read_market(event_id: str, session: Session = Depends(get_session)) -> schemas.MarketRead:
    cache_key = _market_detail_cache_key(event_id)
    log_event(
        logger,
        logging.DEBUG,
        event="markets.detail.request",
        message="processing market detail request",
        event_id=event_id,
        cache_key=cache_key,
    )
    start = time.perf_counter()
    cached = get_json(cache_client, cache_key)
    if cached is not None:
        duration = (time.perf_counter() - start) * 1000
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
        return schemas.MarketRead.model_validate(cached)

    market = crud.get_market_by_event_id(session, event_id)
    if not market:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="market_not_found")
    response = schemas.MarketRead.model_validate(market)
    schema_tag = get_schema_tag(cache_client, settings.schema_version_key)
    set_json(cache_client, cache_key, response.model_dump(mode="json"), settings.cache_ttl_seconds)
    add_tag(cache_client, schema_tag, cache_key)
    add_tag(cache_client, f"market:{event_id}", cache_key)
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


@app.post("/markets", response_model=schemas.MarketRead, tags=["markets"], status_code=status.HTTP_201_CREATED)
def upsert_market(market_in: schemas.MarketCreate, session: Session = Depends(get_session)) -> schemas.MarketRead:
    market = crud.create_or_update_market(session, market_in)
    session.flush()
    _invalidate_market_cache(market.event_id, getattr(market, "condition_id", None))
    return market


@app.patch("/markets/{event_id}", response_model=schemas.MarketRead, tags=["markets"])
def update_market(
    event_id: str, update: schemas.MarketUpdate, session: Session = Depends(get_session)
) -> schemas.MarketRead:
    market = crud.get_market_by_event_id(session, event_id)
    if not market:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="market_not_found")
    crud.patch_market(session, market, update)
    session.flush()
    _invalidate_market_cache(event_id, getattr(market, "condition_id", None))
    return market


def _market_detail_cache_key(event_id: str) -> str:
    return f"{MARKET_DETAIL_PREFIX}:{event_id}"


def _invalidate_market_cache(event_id: Optional[str] = None, condition_id: Optional[str] = None) -> None:
    log_event(
        logger,
        logging.DEBUG,
        event="markets.cache.invalidate",
        message="invalidating markets cache",
        event_id=event_id,
        condition_id=condition_id,
    )
    invalidate_tag(cache_client, "markets:list")
    invalidate_tag(cache_client, "markets:stats")
    invalidate_tag(cache_client, "markets:category")
    invalidate_tag(cache_client, "markets:tag")
    invalidate_tag(cache_client, "markets:suggest")
    if event_id:
        invalidate_tag(cache_client, f"market:{event_id}")
    if condition_id:
        invalidate_tag(cache_client, f"resolution:{condition_id.lower()}")
