from __future__ import annotations

import pytest
from shared import models, repository_async
from sqlalchemy import select


def _ticket_base() -> dict[str, object]:
    return {
        "ticketHash": "0x" + "b" * 64,
        "leaf": "0x" + "b" * 64,
        "user": "0x00000000000000000000000000000000000000bb",
        "outcomeId": 1,
        "amount": 1,
        "salt": "0x0",
        "merklePath": [],
    }


@pytest.mark.asyncio
async def test_record_commitments_missing_merkle_index_async(test_database):
    _, testing_async_session, _ = test_database
    async with testing_async_session() as session:
        market = models.Market(event_id="evt-async-1", title="Async Market", oracle="oracle")
        session.add(market)
        await session.flush()

        count = await repository_async.record_commitments(session, market.id, [_ticket_base()])
        await session.commit()

    async with testing_async_session() as session:
        commitment = (await session.execute(select(models.Commitment))).scalar_one()
        assert count == 1
        assert commitment.leaf_index is None


@pytest.mark.asyncio
async def test_record_commitments_dedupes_ticket_hashes_async(test_database):
    _, testing_async_session, _ = test_database
    async with testing_async_session() as session:
        market = models.Market(event_id="evt-async-2", title="Async Market", oracle="oracle")
        session.add(market)
        await session.flush()

        ticket = _ticket_base()
        duplicate = dict(ticket)
        duplicate["amount"] = 5
        count = await repository_async.record_commitments(session, market.id, [ticket, duplicate])
        await session.commit()

    async with testing_async_session() as session:
        commitments = (await session.execute(select(models.Commitment))).scalars().all()
        assert count == 1
        assert len(commitments) == 1
