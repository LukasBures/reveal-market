from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.config import get_settings
from app.database import engine, get_session
from app.health import build_health_response

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    models.Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)


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
    return crud.get_markets(
        session,
        status=status,
        category=category,
        oracle=oracle,
        search=search,
        limit=limit,
        offset=offset,
    )


@app.get("/markets/stats", response_model=list[schemas.MarketStatusBreakdown], tags=["markets"])
def market_stats(session: Session = Depends(get_session)) -> list[schemas.MarketStatusBreakdown]:
    return crud.get_market_stats(session)


@app.get("/markets/{event_id}", response_model=schemas.MarketRead, tags=["markets"])
def read_market(event_id: str, session: Session = Depends(get_session)) -> schemas.MarketRead:
    market = crud.get_market_by_event_id(session, event_id)
    if not market:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="market_not_found")
    return market


@app.post("/markets", response_model=schemas.MarketRead, tags=["markets"], status_code=status.HTTP_201_CREATED)
def upsert_market(market_in: schemas.MarketCreate, session: Session = Depends(get_session)) -> schemas.MarketRead:
    market = crud.create_or_update_market(session, market_in)
    session.flush()
    return market


@app.patch("/markets/{event_id}", response_model=schemas.MarketRead, tags=["markets"])
def update_market(event_id: str, update: schemas.MarketUpdate, session: Session = Depends(get_session)) -> schemas.MarketRead:
    market = crud.get_market_by_event_id(session, event_id)
    if not market:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="market_not_found")
    crud.patch_market(session, market, update)
    session.flush()
    return market
