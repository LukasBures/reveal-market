from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app import market_sync, runtime
from app.resolution import ResolutionOutcome
from shared.models import Base, Market
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_resolution_backfill_enqueues_updates(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, future=True, expire_on_commit=False)

    async with session_factory() as session:
        session.add(
            Market(
                id=1,
                event_id="evt-1",
                title="Backfill Market",
                oracle="0x" + "1" * 40,
                status="commit",
                condition_id="cond-1",
                resolved_at=datetime.now(UTC),
            )
        )
        await session.commit()

    monkeypatch.setattr(runtime.settings, "resolution_backfill_limit", 5, raising=False)

    async def fake_apply_resolution(_session, record, _payload):
        return ResolutionOutcome(
            changed=True,
            condition_id=record.condition_id,
            cache_payload={"condition_id": record.condition_id, "winning_outcome_id": 1},
        )

    monkeypatch.setattr(market_sync, "apply_resolution", fake_apply_resolution)

    async with session_factory() as session:
        summary = market_sync.SyncSummary()
        backfilled = await market_sync.backfill_missing_resolutions_async(session, summary)

    assert backfilled == 1
    assert "cond-1" in summary.changed_conditions
    assert summary.resolution_cache_updates
