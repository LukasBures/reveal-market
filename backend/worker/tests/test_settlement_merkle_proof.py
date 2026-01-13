from __future__ import annotations

import pytest
from app.settlement import _build_merkle_proof_for_commitment
from shared.merkle import build_merkle_root_and_paths
from shared.models import Base, Commitment, CommitmentMerklePath, Market, Settlement
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_build_merkle_proof_recomputes_and_persists_paths():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, future=True, expire_on_commit=False)

    leaf0 = b"\x01" * 32
    leaf1 = b"\x02" * 32
    root, paths = build_merkle_root_and_paths([leaf0, leaf1])
    merkle_root = "0x" + root.hex()

    async with session_factory() as session:
        market = Market(
            id=1,
            event_id="evt",
            title="Test Market",
            oracle="0x" + "1" * 40,
            market_address="0x" + "1" * 40,
            status="commit",
        )
        settlement = Settlement(
            id=1,
            market_id=1,
            commitments_count=2,
            merkle_root=merkle_root,
        )
        commitment0 = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "2" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=10,
            salt="0x" + "3" * 64,
            ticket_hash="0x" + leaf0.hex(),
            leaf="0x" + leaf0.hex(),
            leaf_index=0,
        )
        commitment1 = Commitment(
            id=2,
            market_id=1,
            user_address="0x" + "4" * 40,
            outcome_id=1,
            amount_wei=10,
            payout_wei=10,
            salt="0x" + "5" * 64,
            ticket_hash="0x" + leaf1.hex(),
            leaf="0x" + leaf1.hex(),
            leaf_index=1,
        )
        session.add_all([market, settlement, commitment0, commitment1])
        await session.commit()

    async with session_factory() as session:
        proof = await _build_merkle_proof_for_commitment(session, 1, settlement, commitment0)
        assert proof
        rows = (
            await session.execute(
                CommitmentMerklePath.__table__.select().where(CommitmentMerklePath.commitment_id == 1)
            )
        ).all()
        assert rows
