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


@pytest.mark.asyncio
async def test_record_commitments_updates_placeholder_job_row_with_real_tx_hash_async(test_database):
    _, testing_async_session, _ = test_database
    ticket = _ticket_base()
    ticket["txHash"] = "0x" + "c" * 64
    ticket["merkleIndex"] = 0

    async with testing_async_session() as session:
        market = models.Market(event_id="evt-async-3", title="Async Market", oracle="oracle")
        session.add(market)
        await session.flush()
        session.add(
            models.Commitment(
                market_id=market.id,
                user_address=str(ticket["user"]).lower(),
                outcome_id=int(ticket["outcomeId"]),
                amount_wei=int(ticket["amount"]),
                payout_wei=0,
                salt=str(ticket["salt"]),
                ticket_hash=str(ticket["ticketHash"]).lower(),
                leaf=str(ticket["leaf"]).lower(),
                leaf_index=0,
                tx_hash="job-123",
            )
        )
        await session.commit()
        market_id = market.id

    async with testing_async_session() as session:
        count = await repository_async.record_commitments(session, market_id, [ticket])
        await session.commit()

    async with testing_async_session() as session:
        commitment = (await session.execute(select(models.Commitment))).scalar_one()
        assert count == 1
        assert commitment.tx_hash == "0x" + "c" * 64


@pytest.mark.asyncio
async def test_count_commitments_ignores_non_hex_job_rows_async(test_database):
    _, testing_async_session, _ = test_database
    async with testing_async_session() as session:
        market = models.Market(event_id="evt-async-4", title="Async Market", oracle="oracle")
        session.add(market)
        await session.flush()
        session.add_all(
            [
                models.Commitment(
                    market_id=market.id,
                    user_address="0x" + "1" * 40,
                    outcome_id=0,
                    amount_wei=1,
                    payout_wei=1,
                    salt="0x0",
                    ticket_hash="0x" + "d" * 64,
                    leaf="0x" + "d" * 64,
                    leaf_index=0,
                    tx_hash="job-queued-1",
                ),
                models.Commitment(
                    market_id=market.id,
                    user_address="0x" + "2" * 40,
                    outcome_id=1,
                    amount_wei=1,
                    payout_wei=1,
                    salt="0x0",
                    ticket_hash="0x" + "e" * 64,
                    leaf="0x" + "e" * 64,
                    leaf_index=1,
                    tx_hash="0x" + "f" * 64,
                ),
            ]
        )
        await session.commit()
        market_id = market.id

    async with testing_async_session() as session:
        count = await repository_async.count_commitments(session, market_id)
        commitments = await repository_async.list_commitments_by_market(session, market_id)

    assert count == 1
    assert len(commitments) == 1
    assert commitments[0].tx_hash == "0x" + "f" * 64
