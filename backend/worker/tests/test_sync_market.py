"""Regression tests around the worker's database upsert behaviour."""

from __future__ import annotations

from datetime import UTC, datetime

import app.market_sync as market_sync
import app.resolution as resolution_module
import pytest
from app.polymarket import MarketPayload
from shared.models import Base, Market, Resolution
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

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
            _, outcome = await market_sync.sync_market(session, initial)
            assert outcome.market_changed is True
            await session.commit()

        async with session_factory() as session:
            stored = (
                await session.execute(
                    select(Market).options(selectinload(Market.outcomes_rel)).where(Market.event_id == "evt-1")
                )
            ).scalar_one()
            assert stored.title == "First Market"
            assert stored.status == "commit"
            labels = [row.label for row in stored.outcomes_rel]
            assert labels == ["YES", "NO"]
            assert stored.rake_bps is None

        updated = initial.model_copy(update={"title": "Updated Market", "status": "settled"})

        async with session_factory() as session:
            _, outcome = await market_sync.sync_market(session, updated)
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
        )

        async with session_factory() as session:
            await market_sync.sync_market(session, base_payload)
            await session.commit()

        async with session_factory() as session:
            existing = (await session.execute(select(Market).where(Market.event_id == "evt-prefetch"))).scalar_one()
            updated = base_payload.model_copy(update={"title": "Prefetched Update"})

            def _unexpected(*args, **kwargs):
                raise AssertionError("should not refetch market when prefetched instance is provided")

            monkeypatch.setattr("app.market_sync.shared_repository.get_market_by_event_id", _unexpected, raising=False)

            await market_sync.sync_market(session, updated, existing_market=existing)
            await session.commit()

        async with session_factory() as session:
            stored = (await session.execute(select(Market).where(Market.event_id == "evt-prefetch"))).scalar_one()
            assert stored.title == "Prefetched Update"
    finally:
        await engine.dispose()


async def test_sync_market_preserves_onchain_fields():
    """Ensure worker sync does not wipe stored market address/onchain ids when payload omits them."""

    engine, session_factory = await create_async_in_memory_db()
    try:
        initial = MarketPayload(
            event_id="evt-onchain",
            title="Onchain Market",
            slug="onchain-market",
            category="finance",
            metadata_uri=None,
            oracle="polymarket",
            factory="0xfac7ory",
            market_address="0xabc0000000000000000000000000000000000000",
            onchain_market_id=42,
            status="commit",
            outcomes=["Yes", "No"],
            outcome_prices=[0.55, 0.45],
        )

        async with session_factory() as session:
            await market_sync.sync_market(session, initial)
            await session.commit()

        updated = MarketPayload(
            event_id=initial.event_id,
            title="Updated Title",
            slug=initial.slug,
            category=initial.category,
            metadata_uri=initial.metadata_uri,
            oracle=initial.oracle,
            status="commit",
            outcomes=initial.outcomes,
            outcome_prices=initial.outcome_prices,
            source_updated_at=datetime.now(UTC),
        )

        async with session_factory() as session:
            await market_sync.sync_market(session, updated)
            await session.commit()

        conflicting = updated.model_copy(
            update={
                "market_address": "0xdef0000000000000000000000000000000000000",
                "onchain_market_id": 999,
                "factory": "0xdeadbeef",
            }
        )

        async with session_factory() as session:
            await market_sync.sync_market(session, conflicting)
            await session.commit()

        async with session_factory() as session:
            stored = (await session.execute(select(Market).where(Market.event_id == initial.event_id))).scalar_one()
            assert stored.title == "Updated Title"
            assert stored.market_address == initial.market_address
            assert stored.onchain_market_id == initial.onchain_market_id
            assert stored.factory == initial.factory
    finally:
        await engine.dispose()


async def test_sync_market_persists_resolution(monkeypatch):
    engine, session_factory = await create_async_in_memory_db()

    class DummyClient:
        def resolution_summary(self, condition_id_hex, outcomes, outcome_count_hint):
            return {
                "source": "goldsky_subgraph",
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
        monkeypatch.setattr(resolution_module, "goldsky_client", DummyClient(), raising=False)

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
            condition_id="0x" + "3" * 64,
        )

        async with session_factory() as session:
            _, outcome = await market_sync.sync_market(session, payload)
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
            _, outcome = await market_sync.sync_market(session, payload)
            assert outcome.market_changed is True
            assert outcome.resolution_changed is False
            await session.commit()

        identical = MarketPayload(**payload.model_dump())

        async with session_factory() as session:
            _, outcome = await market_sync.sync_market(session, identical)
            assert outcome.market_changed is False
            assert outcome.resolution_changed is False
            await session.commit()

        assert call_count == 1
    finally:
        await engine.dispose()


async def test_sync_market_upserts_when_hash_changes_with_same_timestamp(monkeypatch):
    engine, session_factory = await create_async_in_memory_db()
    try:
        updated_at = datetime.now(UTC)
        payload = MarketPayload(
            event_id="evt-hash-change",
            title="Hash Change Market",
            slug="hash-change-market",
            category="science",
            metadata_uri=None,
            oracle="polymarket",
            status="commit",
            outcomes=["Yes", "No"],
            outcome_prices=[0.45, 0.55],
            source_updated_at=updated_at,
        )

        call_count = 0
        original_upsert = market_sync.shared_repository.upsert_market

        def tracked_upsert(session, data, existing=None):
            nonlocal call_count
            call_count += 1
            return original_upsert(session, data, existing)

        monkeypatch.setattr("app.market_sync.shared_repository.upsert_market", tracked_upsert, raising=False)

        async with session_factory() as session:
            _, outcome = await market_sync.sync_market(session, payload)
            assert outcome.market_changed is True
            assert outcome.resolution_changed is False
            await session.commit()

        modified = payload.model_copy(update={"outcome_prices": [0.4, 0.6]})

        async with session_factory() as session:
            _, outcome = await market_sync.sync_market(session, modified)
            assert outcome.market_changed is True
            assert outcome.resolution_changed is False
            await session.commit()

        assert call_count == 2
    finally:
        await engine.dispose()


async def test_sync_market_skips_when_source_timestamp_matches_without_hash(monkeypatch):
    engine, session_factory = await create_async_in_memory_db()
    try:
        updated_at = datetime.now(UTC)
        payload = MarketPayload(
            event_id="evt-skip-no-hash",
            title="Skip Market No Hash",
            slug="skip-market-no-hash",
            category="science",
            metadata_uri=None,
            oracle="polymarket",
            status="commit",
            outcomes=["Yes", "No"],
            outcome_prices=[0.45, 0.55],
            source_updated_at=updated_at,
        )

        call_count = 0
        original_upsert = market_sync.shared_repository.upsert_market

        def tracked_upsert(session, data, existing=None):
            nonlocal call_count
            call_count += 1
            return original_upsert(session, data, existing)

        monkeypatch.setattr("app.market_sync.shared_repository.upsert_market", tracked_upsert, raising=False)

        async with session_factory() as session:
            _, outcome = await market_sync.sync_market(session, payload)
            assert outcome.market_changed is True
            assert outcome.resolution_changed is False
            await session.commit()

        identical = MarketPayload(**payload.model_dump())

        async with session_factory() as session:
            _, outcome = await market_sync.sync_market(session, identical)
            assert outcome.market_changed is False
            assert outcome.resolution_changed is False
            await session.commit()

        assert call_count == 1
    finally:
        await engine.dispose()
