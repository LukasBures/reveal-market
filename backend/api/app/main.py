from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from .config import get_settings
from .database import engine, get_session
from . import models, schemas, crud

app = FastAPI(title="Reveal Market API", version="1.0.0")


@app.on_event("startup")
def on_startup() -> None:
    models.Base.metadata.create_all(bind=engine)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "polymarket_api": str(settings.polymarket_api_base)}


@app.get("/markets", response_model=List[schemas.MarketRead], tags=["markets"])
def list_markets(
    status: Optional[str] = None,
    limit: int = 100,
    session: Session = Depends(get_session),
) -> List[schemas.MarketRead]:
    return crud.get_markets(session, status=status, limit=limit)


@app.get("/markets/{event_id}", response_model=schemas.MarketRead, tags=["markets"])
def read_market(event_id: str, session: Session = Depends(get_session)) -> schemas.MarketRead:
    market = crud.get_market_by_event_id(session, event_id)
    if not market:
        raise HTTPException(status_code=404, detail="market_not_found")
    return market


@app.post("/markets", response_model=schemas.MarketRead, tags=["markets"], status_code=201)
def upsert_market(market_in: schemas.MarketCreate, session: Session = Depends(get_session)) -> schemas.MarketRead:
    market = crud.create_or_update_market(session, market_in)
    session.flush()
    return market


@app.patch("/markets/{event_id}", response_model=schemas.MarketRead, tags=["markets"])
def update_market(event_id: str, update: schemas.MarketUpdate, session: Session = Depends(get_session)) -> schemas.MarketRead:
    market = crud.get_market_by_event_id(session, event_id)
    if not market:
        raise HTTPException(status_code=404, detail="market_not_found")
    crud.patch_market(session, market, update)
    session.flush()
    return market
