"""Regression tests around the worker's database upsert behaviour."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.main import sync_market
from app.polymarket import MarketPayload
from shared.models import Base, Market, Resolution


def create_in_memory_db():
    """Bootstrap a temporary SQLite database mirroring the production schema subset."""
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(bind=engine)

    TestSession = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    return engine, TestSession


def test_sync_market_inserts_and_updates():
    """Verify the same event_id can be inserted and subsequently updated."""
    engine, TestSession = create_in_memory_db()

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
            extra_data={"gamma": {"id": "evt-1"}},
        )

        with TestSession() as session:
            sync_market(session, initial)
            session.commit()

        with TestSession() as session:
            stored = session.execute(
                select(Market).where(Market.event_id == "evt-1")
            ).scalar_one()
            assert stored.title == "First Market"
            assert stored.status == "commit"
            assert stored.outcomes == ["YES", "NO"]
            assert stored.rake_bps is None

        updated = initial.model_copy(update={"title": "Updated Market", "status": "settled"})

        with TestSession() as session:
            sync_market(session, updated)
            session.commit()

        with TestSession() as session:
            stored = session.execute(
                select(Market).where(Market.event_id == "evt-1")
            ).scalar_one()
            assert stored.title == "Updated Market"
            assert stored.status == "settled"
            assert stored.rake_bps is None
    finally:
        engine.dispose()


def test_sync_market_persists_resolution(monkeypatch):
    engine, TestSession = create_in_memory_db()

    class DummyClient:
        def resolution_summary(self, condition_id_hex, outcomes, outcome_count_hint):
            return {
                "source": "conditional_tokens",
                "conditionId": condition_id_hex,
                "resolved": True,
                "outcomes": outcomes,
                "payouts": [0, 1],
                "winners": [{"index": 1, "label": outcomes[1] if len(outcomes) > 1 else None, "payout": 1}],
                "checkedAt": datetime.now(timezone.utc),
                "oracle": "0xfeed",
                "questionId": "0x" + "1" * 64,
                "transactionHash": "0x" + "2" * 64,
                "blockNumber": 555,
                "blockTimestamp": datetime.now(timezone.utc),
            }

    try:
        monkeypatch.setattr("app.main.conditional_tokens_client", DummyClient(), raising=False)

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
            extra_data={"gamma": {"id": "evt-resolution"}},
            condition_id="0x" + "3" * 64,
        )

        with TestSession() as session:
            sync_market(session, payload)
            session.commit()

        with TestSession() as session:
            record = session.execute(
                select(Resolution).where(Resolution.condition_id == payload.condition_id.lower())
            ).scalar_one()
            assert record.resolved is True
            assert record.transaction_hash == "0x" + "2" * 64
    finally:
        engine.dispose()
        monkeypatch.setattr("app.main.conditional_tokens_client", None, raising=False)
