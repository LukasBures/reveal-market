from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Annotated, Optional
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app import crud, schemas
from app.config import get_settings
from app.database import get_session, run_migrations
from app.health import build_health_response
from app.onchain import fetch_factory_markets
from prometheus_fastapi_instrumentator import Instrumentator
from shared.cache import delete, delete_prefix, get_client, get_json, set_json
from shared.logging import configure_json_logging, log_event, reset_request_id, set_request_id
from shared.onchain import ConditionalTokensClient, OnChainConfigurationError

configure_json_logging("reveal_market.api")

settings = get_settings()
logger = logging.getLogger("reveal_market.api")
instrumentator = Instrumentator()
cache_client = get_client(settings.redis_url)

MARKETS_LIST_PREFIX = "markets:list"
MARKETS_STATS_KEY = "markets:stats"
MARKET_DETAIL_PREFIX = "markets:detail"
MARKET_RESOLUTION_PREFIX = "markets:resolution"


_resolution_client: ConditionalTokensClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    yield


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
if not getattr(app.state, "metrics_instrumented", False):
    instrumentator.instrument(app).expose(app, include_in_schema=False, tags=["metrics"])
    app.state.metrics_instrumented = True
app.cache_client = cache_client  # type: ignore[attr-defined]


def _resolution_cache_key(condition_id: str) -> str:
    return f"{MARKET_RESOLUTION_PREFIX}:{condition_id.lower()}"


def _get_conditional_tokens_client() -> ConditionalTokensClient:
    global _resolution_client
    settings = get_settings()
    rpc_url = settings.polygon_rpc_url or settings.rpc_url
    contract_address = settings.conditional_tokens_address
    if not (rpc_url and contract_address):
        raise OnChainConfigurationError("conditional tokens configuration missing")
    if _resolution_client is None:
        try:
            _resolution_client = ConditionalTokensClient(str(rpc_url), contract_address)
        except Exception as exc:  # pragma: no cover - defensive
            raise OnChainConfigurationError(str(exc)) from exc
    return _resolution_client


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
    cache_key = _markets_list_cache_key(status, category, oracle, search, limit, offset)
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
        return [schemas.MarketRead.model_validate(item) for item in cached]

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
    payload = [item.model_dump(mode="json") for item in market_models]
    set_json(cache_client, cache_key, payload, settings.cache_ttl_seconds)
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
    set_json(cache_client, MARKETS_STATS_KEY, payload, settings.cache_ttl_seconds)
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


@app.get("/resolution/{condition_id_hex}", response_model=schemas.ResolutionSummary, tags=["markets"])
def read_resolution(condition_id_hex: str, session: Session = Depends(get_session)) -> schemas.ResolutionSummary:
    cache_key = _resolution_cache_key(condition_id_hex)
    cached = get_json(cache_client, cache_key)
    if cached is not None:
        return schemas.ResolutionSummary.model_validate(cached)

    try:
        client = _get_conditional_tokens_client()
    except OnChainConfigurationError as exc:
        log_event(
            logger,
            logging.WARNING,
            event="markets.resolution.unconfigured",
            message="resolution configuration missing",
            condition_id=condition_id_hex,
        )
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="resolution_not_configured") from exc

    market = crud.get_market_by_condition_id(session, condition_id_hex)
    outcomes = market.outcomes if market else None
    outcome_prices = market.outcome_prices if market else None
    outcome_count_hint = len(outcome_prices) if isinstance(outcome_prices, list) else None

    try:
        summary = client.resolution_summary(condition_id_hex, outcomes or [], outcome_count_hint)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("failed to query conditional tokens resolution", extra={"condition_id": condition_id_hex})
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="resolution_query_failed") from exc

    if market:
        summary["marketId"] = market.id
        summary["eventId"] = market.event_id
        summary["title"] = market.title
        summary["slug"] = market.slug
        summary["outcomes"] = outcomes or []

    set_json(cache_client, cache_key, summary, settings.cache_ttl_seconds)
    return schemas.ResolutionSummary.model_validate(summary)


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
    set_json(cache_client, cache_key, response.model_dump(mode="json"), settings.cache_ttl_seconds)
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
def update_market(event_id: str, update: schemas.MarketUpdate, session: Session = Depends(get_session)) -> schemas.MarketRead:
    market = crud.get_market_by_event_id(session, event_id)
    if not market:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="market_not_found")
    crud.patch_market(session, market, update)
    session.flush()
    _invalidate_market_cache(event_id, getattr(market, "condition_id", None))
    return market


def _markets_list_cache_key(
    status: Optional[str],
    category: Optional[str],
    oracle: Optional[str],
    search: Optional[str],
    limit: int,
    offset: int,
) -> str:
    parts = [
        f"status={status or '*'}",
        f"category={category or '*'}",
        f"oracle={oracle or '*'}",
        f"search={search or '*'}",
        f"limit={limit}",
        f"offset={offset}",
    ]
    return f"{MARKETS_LIST_PREFIX}:" + "|".join(parts)


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
    delete_prefix(cache_client, MARKETS_LIST_PREFIX)
    delete(cache_client, MARKETS_STATS_KEY)
    if event_id:
        delete(cache_client, _market_detail_cache_key(event_id))
    if condition_id:
        delete(cache_client, _resolution_cache_key(condition_id))
