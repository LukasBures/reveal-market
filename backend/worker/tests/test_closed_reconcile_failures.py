from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import logging

import pytest
from app import runtime
from app import service as worker_service
from shared import models as shared_models
from shared.models import Base, Market
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_closed_reconcile_logs_failures(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="reveal_market.worker")

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, future=True, expire_on_commit=False)

    @asynccontextmanager
    async def _session_scope():
        session = session_factory()
        try:
            yield session
            if session.in_transaction():
                await session.commit()
        finally:
            await session.close()

    monkeypatch.setattr(worker_service, "session_scope", _session_scope, raising=False)

    now = datetime.now(UTC)
    async with session_factory() as session:
        session.add(
            Market(
                id=1,
                event_id="evt-closed",
                title="Closed Market",
                oracle="0x" + "1" * 40,
                status="commit",
                condition_id="cond-1",
                closes_at=now - timedelta(seconds=5),
                closed=True,
            )
        )
        await session.commit()

    async with session_factory() as session:
        session.add(
            shared_models.Commitment(
                market_id=1,
                user_address="0x" + "2" * 40,
                outcome_id=0,
                amount_wei=10,
                payout_wei=10,
                salt="0x" + "3" * 64,
                ticket_hash="0x" + "4" * 64,
                leaf="0x" + "4" * 64,
                leaf_index=0,
            )
        )
        await session.commit()

    async def fake_fetch(_batch, *_args, **_kwargs):
        return [], 1, 2

    async def always_run(_redis):
        return True

    monkeypatch.setattr(worker_service, "_fetch_closed_reconcile_markets", fake_fetch)
    monkeypatch.setattr(worker_service, "_should_run_closed_reconcile", always_run)
    monkeypatch.setattr(runtime.settings, "closed_markets_reconcile_batch_size", 2, raising=False)
    monkeypatch.setattr(runtime.settings, "closed_markets_reconcile_max_markets", 10, raising=False)
    monkeypatch.setattr(runtime.settings, "closed_markets_reconcile_stale_seconds", 0, raising=False)
    monkeypatch.setattr(runtime.settings, "closed_markets_reconcile_interval_seconds", 1, raising=False)

    async with session_factory() as session:
        result = await worker_service._reconcile_closed_markets(session, None)
    assert result["failed"] == 1
    assert result["missing"] == 2
    assert any(
        rec.__dict__.get("event") == "worker.maintenance.closed_reconcile.complete" for rec in caplog.records
    )
