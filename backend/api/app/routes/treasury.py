"""Treasury snapshot routes (read-only)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.database import get_session

router = APIRouter()


@router.get("/treasury/snapshots", response_model=list[schemas.TreasurySnapshot], tags=["treasury"])
async def treasury_snapshots(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    market_id: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_session),
) -> list[schemas.TreasurySnapshot]:
    """Return the latest treasury snapshots (optionally filtered by market)."""

    stmt = select(models.HedgerTreasurySnapshot).order_by(models.HedgerTreasurySnapshot.created_at.desc())
    if market_id:
        stmt = stmt.where(models.HedgerTreasurySnapshot.market_id == market_id)
    result = await session.execute(stmt.limit(limit))
    rows = result.scalars().all()
    return [schemas.TreasurySnapshot.model_validate(row) for row in rows]
