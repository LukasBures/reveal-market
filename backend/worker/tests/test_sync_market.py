"""Regression tests around the worker's database upsert behaviour."""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.main import sync_market
from app.polymarket import MarketPayload
from shared.models import Base, Market


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
            category="sports",
            metadata_uri="ipfs://abc",
            oracle="polymarket",
            factory="0xfactory",
            market_address="0xmarket",
            status="commit",
            outcomes=[{"name": "YES", "price": "0.5"}],
            extra_data={"foo": "bar"},
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
            assert stored.outcomes == [{"name": "YES", "price": "0.5"}]

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
    finally:
        engine.dispose()
