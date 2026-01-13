from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
import shared.models as shared_models
from app import runtime
from app.settlement import run_lock_batches_jobs
from eth_account import Account
from shared.models import Base, Commitment, Market
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def _setup_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, future=True, expire_on_commit=False)
    return engine, session_factory


@pytest.mark.asyncio
async def test_lock_batches_enqueues_successful_submission(monkeypatch):
    engine, session_factory = await _setup_session()

    @asynccontextmanager
    async def _session_scope():
        session = session_factory()
        try:
            yield session
            if session.in_transaction():
                await session.commit()
        finally:
            await session.close()

    monkeypatch.setattr("app.settlement.session_scope", _session_scope, raising=False)

    now = datetime.now(UTC)
    market = Market(
        id=1,
        event_id="evt-1",
        title="Test Market",
        oracle="0x" + "1" * 40,
        market_address="0x" + "2" * 40,
        status=shared_models.MarketStatusEnum.COMMIT.value,
        closes_at=now - timedelta(seconds=5),
    )
    commitment = Commitment(
        market_id=1,
        user_address="0x" + "3" * 40,
        outcome_id=0,
        amount_wei=10,
        payout_wei=10,
        salt="0x" + "4" * 64,
        ticket_hash="0x" + "5" * 64,
        leaf="0x" + "5" * 64,
        leaf_index=0,
    )
    async with session_factory() as session:
        session.add(market)
        session.add(commitment)
        await session.commit()

    class _Key:
        def __init__(self, value: str):
            self._value = value

        def get_secret_value(self) -> str:
            return self._value

    signer_key = "1" * 64
    signer_address = Account.from_key(signer_key).address

    snapshot = {
        "phase": 0,
        "commit_deadline": int((now - timedelta(seconds=1)).timestamp()),
        "commitments_count": 1,
        "oracle": signer_address,
        "circuit_hash": "0x" + "6" * 64,
    }

    async def fake_fetch_onchain_snapshot(_web3, _market_address):
        return snapshot

    async def fake_submit_lock_batches(_web3, _account, _market_address, _roots, _counts):
        return "0x" + "a" * 64, 123

    monkeypatch.setattr("app.settlement._fetch_onchain_snapshot", fake_fetch_onchain_snapshot)
    monkeypatch.setattr("app.settlement._submit_lock_batches", fake_submit_lock_batches)
    monkeypatch.setattr(runtime.settings, "rpc_url", "http://rpc", raising=False)
    monkeypatch.setattr(runtime.settings, "lock_batches_use_relayer", False, raising=False)
    monkeypatch.setattr(runtime.settings, "lock_batches_max_per_tick", 1, raising=False)

    monkeypatch.setattr(runtime.settings, "settlement_signer_private_key", _Key(signer_key), raising=False)

    summary = type("Summary", (), {"lock_batches_submitted": 0, "changed_events": set()})
    submitted = await run_lock_batches_jobs(summary, None)
    assert submitted == 1
    assert summary.lock_batches_submitted == 1
    assert "evt-1" in summary.changed_events
