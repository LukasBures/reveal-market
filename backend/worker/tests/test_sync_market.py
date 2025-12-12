"""Regression tests around the worker's database upsert behaviour."""

from __future__ import annotations

from datetime import UTC, datetime

import app.market_sync as market_sync
import app.resolution as resolution_module
import pytest
from app.market_sync import sync_market
from app.polymarket import MarketPayload
from shared.models import Base, Market, Resolution
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.asyncio


async def create_async_in_memory_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    return engine, session_factory


async def test_sync_market_inserts_and_updates():
    """Verify the same event_id can be inserted and subsequently updated."""
    engine, session_factory = await create_async_in_memory_db()

    try:
        initial = MarketPayload(
            event_id="evt-1",
            title="First Market",
            slug="first-market",
            category="sports",
            metadata_uri="ipfs://abc",
            oracle="polymarket",
            factory="0xfactory",
            market_address="0xmarket",
            status="commit",
            outcomes=["YES", "NO"],
            outcome_prices=[0.5, 0.5],
        )

        async with session_factory() as session:
            _, outcome = await sync_market(session, initial)
            assert outcome.market_changed is True
            await session.commit()

        async with session_factory() as session:
            stored = (await session.execute(select(Market).where(Market.event_id == "evt-1"))).scalar_one()
            assert stored.title == "First Market"
            assert stored.status == "commit"
            labels = [row.label for row in stored.outcomes_rel]
            assert labels == ["YES", "NO"]
            assert stored.rake_bps is None

        updated = initial.model_copy(update={"title": "Updated Market", "status": "settled"})

        async with session_factory() as session:
            _, outcome = await sync_market(session, updated)
            assert outcome.market_changed is True
            await session.commit()

        async with session_factory() as session:
            stored = (await session.execute(select(Market).where(Market.event_id == "evt-1"))).scalar_one()
            assert stored.title == "Updated Market"
            assert stored.status == "settled"
            assert stored.rake_bps is None
    finally:
        await engine.dispose()


async def test_sync_market_reuses_prefetched_instance(monkeypatch):
    engine, session_factory = await create_async_in_memory_db()
    try:
        base_payload = MarketPayload(
            event_id="evt-prefetch",
            title="Prefetch Market",
            slug="prefetch-market",
            category="finance",
            metadata_uri=None,
            oracle="polymarket",
            status="commit",
            outcomes=["Yes", "No"],
            outcome_prices=[0.5, 0.5],
            gamma_raw={"id": "evt-prefetch"},
        )

        async with session_factory() as session:
            await sync_market(session, base_payload)
            await session.commit()

        async with session_factory() as session:
            existing = (await session.execute(select(Market).where(Market.event_id == "evt-prefetch"))).scalar_one()
            updated = base_payload.model_copy(update={"title": "Prefetched Update"})

            def _unexpected(*args, **kwargs):
                raise AssertionError("should not refetch market when prefetched instance is provided")

            monkeypatch.setattr("app.market_sync.shared_repository.get_market_by_event_id", _unexpected, raising=False)

            await sync_market(session, updated, existing_market=existing)
            await session.commit()

        async with session_factory() as session:
            stored = (await session.execute(select(Market).where(Market.event_id == "evt-prefetch"))).scalar_one()
            assert stored.title == "Prefetched Update"
    finally:
        await engine.dispose()


async def test_sync_market_persists_resolution(monkeypatch):
    engine, session_factory = await create_async_in_memory_db()

    class DummyClient:
        def resolution_summary(self, condition_id_hex, outcomes, outcome_count_hint):
            return {
                "source": "conditional_tokens",
                "conditionId": condition_id_hex,
                "resolved": True,
                "outcomes": outcomes,
                "payouts": [0, 1],
                "winners": [{"index": 1, "label": outcomes[1] if len(outcomes) > 1 else None, "payout": 1}],
                "checkedAt": datetime.now(UTC),
                "oracle": "0xfeed",
                "questionId": "0x" + "1" * 64,
                "transactionHash": "0x" + "2" * 64,
                "blockNumber": 555,
                "blockTimestamp": datetime.now(UTC),
            }

    try:
        monkeypatch.setattr(resolution_module, "goldsky_client", None, raising=False)
        monkeypatch.setattr(resolution_module, "conditional_tokens_client", DummyClient(), raising=False)

        payload = MarketPayload(
            event_id="evt-resolution",
            title="Resolution Market",
            slug="resolution-market",
            category="news",
            metadata_uri=None,
            oracle="polymarket",
            status="commit",
            outcomes=["Yes", "No"],
            outcome_prices=[0.6, 0.4],
            gamma_raw={"id": "evt-resolution"},
            condition_id="0x" + "3" * 64,
        )

        async with session_factory() as session:
            _, outcome = await sync_market(session, payload)
            assert outcome.resolution_changed is True
            await session.commit()

        async with session_factory() as session:
            record = (
                await session.execute(select(Resolution).where(Resolution.condition_id == payload.condition_id.lower()))
            ).scalar_one()
            assert record.resolved is True
            assert record.transaction_hash == "0x" + "2" * 64
    finally:
        await engine.dispose()
        monkeypatch.setattr(resolution_module, "conditional_tokens_client", None, raising=False)
        monkeypatch.setattr(resolution_module, "goldsky_client", None, raising=False)


async def test_sync_market_uses_goldsky_when_available(monkeypatch):
    engine, session_factory = await create_async_in_memory_db()

    class DummyGoldsky:
        def resolution_summary(self, condition_id_hex, outcomes, outcome_count_hint):
            return {
                "source": "goldsky_subgraph",
                "conditionId": condition_id_hex,
                "resolved": True,
                "outcomes": outcomes,
                "payouts": [1, 0],
                "winners": [{"index": 0, "label": outcomes[0] if outcomes else None, "payout": 1}],
                "checkedAt": datetime.now(UTC),
                "oracle": "0xoracle",
                "questionId": "0x" + "4" * 64,
                "transactionHash": "0x" + "5" * 64,
                "blockNumber": 777,
                "blockTimestamp": datetime.now(UTC),
            }

    try:
        monkeypatch.setattr(resolution_module, "goldsky_client", DummyGoldsky(), raising=False)
        monkeypatch.setattr(resolution_module, "conditional_tokens_client", None, raising=False)

        payload = MarketPayload(
            event_id="evt-goldsky",
            title="Goldsky Market",
            slug="goldsky-market",
            category="crypto",
            metadata_uri=None,
            oracle="polymarket",
            status="commit",
            outcomes=["Yes", "No"],
            outcome_prices=[0.6, 0.4],
            gamma_raw={"id": "evt-goldsky"},
            condition_id="0x" + "6" * 64,
        )

        async with session_factory() as session:
            _, outcome = await sync_market(session, payload)
            assert outcome.resolution_changed is True
            await session.commit()

        async with session_factory() as session:
            record = (
                await session.execute(select(Resolution).where(Resolution.condition_id == payload.condition_id.lower()))
            ).scalar_one()
            assert record.source == "goldsky_subgraph"
            assert record.block_number == 777
    finally:
        await engine.dispose()
        monkeypatch.setattr(resolution_module, "goldsky_client", None, raising=False)


async def test_sync_market_skips_when_source_timestamp_matches(monkeypatch):
    engine, session_factory = await create_async_in_memory_db()
    try:
        updated_at = datetime.now(UTC)
        payload = MarketPayload(
            event_id="evt-skip",
            title="Skip Market",
            slug="skip-market",
            category="science",
            metadata_uri=None,
            oracle="polymarket",
            status="commit",
            outcomes=["Yes", "No"],
            outcome_prices=[0.45, 0.55],
            gamma_raw={"id": "evt-skip"},
            source_updated_at=updated_at,
            content_hash="hash-1",
        )

        call_count = 0
        original_upsert = market_sync.shared_repository.upsert_market

        def tracked_upsert(session, data, existing=None):
            nonlocal call_count
            call_count += 1
            return original_upsert(session, data, existing)

        monkeypatch.setattr("app.market_sync.shared_repository.upsert_market", tracked_upsert, raising=False)

        async with session_factory() as session:
            _, outcome = await sync_market(session, payload)
            assert outcome.market_changed is True
            assert outcome.resolution_changed is False
            await session.commit()

        identical = MarketPayload(**payload.model_dump())

        async with session_factory() as session:
            _, outcome = await sync_market(session, identical)
            assert outcome.market_changed is False
            assert outcome.resolution_changed is False
            await session.commit()

        assert call_count == 1
    finally:
        await engine.dispose()
