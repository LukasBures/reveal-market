from __future__ import annotations

from shared import models, repository
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed_market(session: Session, event_id: str = "evt-1") -> models.Market:
    market = models.Market(event_id=event_id, title="Test Market", oracle="oracle")
    session.add(market)
    session.commit()
    return market


def _ticket_base() -> dict[str, object]:
    return {
        "ticketHash": "0x" + "a" * 64,
        "leaf": "0x" + "a" * 64,
        "user": "0x00000000000000000000000000000000000000aa",
        "outcomeId": 0,
        "amount": 1,
        "salt": "0x0",
        "merklePath": [],
    }


def test_record_commitments_missing_merkle_index_sets_none():
    session = _session()
    market = _seed_market(session)

    count = repository.record_commitments(session, market.id, [_ticket_base()])
    session.commit()

    assert count == 1
    commitment = session.execute(select(models.Commitment)).scalar_one()
    assert commitment.leaf_index is None


def test_record_commitments_dedupes_ticket_hashes_in_batch():
    session = _session()
    market = _seed_market(session)

    ticket = _ticket_base()
    duplicate = dict(ticket)
    duplicate["amount"] = 2

    count = repository.record_commitments(session, market.id, [ticket, duplicate])
    session.commit()

    assert count == 1
    commitments = session.execute(select(models.Commitment)).scalars().all()
    assert len(commitments) == 1


def test_record_commitments_coerces_merkle_index_when_present():
    session = _session()
    market = _seed_market(session)
    ticket = _ticket_base()
    ticket["merkleIndex"] = "3"

    count = repository.record_commitments(session, market.id, [ticket])
    session.commit()

    assert count == 1
    commitment = session.execute(select(models.Commitment)).scalar_one()
    assert commitment.leaf_index == 3


def test_record_commitments_invalid_merkle_index_sets_none():
    session = _session()
    market = _seed_market(session)
    ticket = _ticket_base()
    ticket["merkleIndex"] = "not-a-number"

    count = repository.record_commitments(session, market.id, [ticket])
    session.commit()

    assert count == 1
    commitment = session.execute(select(models.Commitment)).scalar_one()
    assert commitment.leaf_index is None
