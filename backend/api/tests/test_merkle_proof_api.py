"""Tests for _build_merkle_proof_for_commitment (API version) — all validation branches."""

from __future__ import annotations

# ruff: noqa: S101
import pytest
from app.routes.trade import _build_merkle_proof_for_commitment
from fastapi import HTTPException
from shared.merkle import build_merkle_root_and_paths
from shared.models import Base, Commitment, CommitmentMerklePath, Market, Settlement
from shared.poseidon import BATCH_SIZE
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def _make_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, future=True, expire_on_commit=False)
    return engine, session_factory


def _make_leaf(seed: int) -> bytes:
    return bytes([seed % 256]) * 32


# ---------------------------------------------------------------------------
# Group A: Validation — raises HTTPException 409 / 404
# ---------------------------------------------------------------------------


async def test_merkle_proof_raises_when_no_batch_roots():
    """Settlement with neither batch_roots nor merkle_root → 409 merkle_root_missing."""
    _, sf = await _make_db()
    async with sf() as session:
        market = Market(id=1, event_id="m1", title="T", oracle="0x" + "1" * 40, market_address="0x" + "1" * 40)
        settlement = Settlement(id=1, market_id=1, merkle_root=None, commitments_count=1)
        commitment = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "2" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + "aa" * 32,
            leaf="0x" + "aa" * 32,
            leaf_index=0,
        )
        session.add_all([market, settlement, commitment])
        await session.commit()

    async with sf() as session:
        settlement = await session.get(Settlement, 1)
        commitment = await session.get(Commitment, 1)
        market = await session.get(Market, 1)
        with pytest.raises(HTTPException) as exc_info:
            await _build_merkle_proof_for_commitment(session, market, settlement, commitment)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "merkle_root_missing"


async def test_merkle_proof_raises_leaf_index_none():
    """Commitment with leaf_index=None → 409 ticket_index_missing."""
    _, sf = await _make_db()
    root = "0x" + "bb" * 32
    async with sf() as session:
        market = Market(id=1, event_id="m2", title="T", oracle="0x" + "1" * 40, market_address="0x" + "1" * 40)
        settlement = Settlement(id=1, market_id=1, merkle_root=root, commitments_count=1)
        commitment = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "2" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + "aa" * 32,
            leaf="0x" + "aa" * 32,
            leaf_index=None,  # <-- missing
        )
        session.add_all([market, settlement, commitment])
        await session.commit()

    async with sf() as session:
        settlement = await session.get(Settlement, 1)
        commitment = await session.get(Commitment, 1)
        market = await session.get(Market, 1)
        with pytest.raises(HTTPException) as exc_info:
            await _build_merkle_proof_for_commitment(session, market, settlement, commitment)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "ticket_index_missing"


async def test_merkle_proof_raises_batch_count_mismatch():
    """batch_roots length != batch_counts length → 409 batch_count_mismatch."""
    import json

    _, sf = await _make_db()
    async with sf() as session:
        market = Market(id=1, event_id="m3", title="T", oracle="0x" + "1" * 40, market_address="0x" + "1" * 40)
        settlement = Settlement(
            id=1,
            market_id=1,
            batch_roots=json.dumps(["0x" + "aa" * 32, "0x" + "bb" * 32]),
            batch_counts=json.dumps([2]),  # length mismatch: 2 roots, 1 count
        )
        commitment = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "2" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + "cc" * 32,
            leaf="0x" + "cc" * 32,
            leaf_index=0,
        )
        session.add_all([market, settlement, commitment])
        await session.commit()

    async with sf() as session:
        settlement = await session.get(Settlement, 1)
        commitment = await session.get(Commitment, 1)
        market = await session.get(Market, 1)
        with pytest.raises(HTTPException) as exc_info:
            await _build_merkle_proof_for_commitment(session, market, settlement, commitment)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "batch_count_mismatch"


async def test_merkle_proof_raises_batch_index_out_of_range():
    """leaf_index // BATCH_SIZE >= len(batch_roots) → 409 batch_index_out_of_range."""
    import json

    _, sf = await _make_db()
    async with sf() as session:
        market = Market(id=1, event_id="m4", title="T", oracle="0x" + "1" * 40, market_address="0x" + "1" * 40)
        settlement = Settlement(
            id=1,
            market_id=1,
            batch_roots=json.dumps(["0x" + "aa" * 32]),  # 1 batch
            batch_counts=json.dumps([2]),
        )
        commitment = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "2" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + "cc" * 32,
            leaf="0x" + "cc" * 32,
            leaf_index=BATCH_SIZE * 2,  # in batch 2, but only batch 0 exists
        )
        session.add_all([market, settlement, commitment])
        await session.commit()

    async with sf() as session:
        settlement = await session.get(Settlement, 1)
        commitment = await session.get(Commitment, 1)
        market = await session.get(Market, 1)
        with pytest.raises(HTTPException) as exc_info:
            await _build_merkle_proof_for_commitment(session, market, settlement, commitment)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "batch_index_out_of_range"


async def test_merkle_proof_raises_batch_count_invalid_zero():
    """batch_count=0 → 409 batch_count_invalid."""
    import json

    _, sf = await _make_db()
    root = "0x" + "aa" * 32
    async with sf() as session:
        market = Market(id=1, event_id="m5", title="T", oracle="0x" + "1" * 40, market_address="0x" + "1" * 40)
        settlement = Settlement(
            id=1,
            market_id=1,
            batch_roots=json.dumps([root]),
            batch_counts=json.dumps([0]),  # zero count — invalid
        )
        commitment = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "2" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + "cc" * 32,
            leaf="0x" + "cc" * 32,
            leaf_index=0,
        )
        session.add_all([market, settlement, commitment])
        await session.commit()

    async with sf() as session:
        settlement = await session.get(Settlement, 1)
        commitment = await session.get(Commitment, 1)
        market = await session.get(Market, 1)
        with pytest.raises(HTTPException) as exc_info:
            await _build_merkle_proof_for_commitment(session, market, settlement, commitment)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "batch_count_invalid"


async def test_merkle_proof_raises_batch_index_invalid():
    """index_in_batch >= batch_count → 409 batch_index_invalid."""
    import json

    _, sf = await _make_db()
    root = "0x" + "aa" * 32
    async with sf() as session:
        market = Market(id=1, event_id="m6", title="T", oracle="0x" + "1" * 40, market_address="0x" + "1" * 40)
        settlement = Settlement(
            id=1,
            market_id=1,
            batch_roots=json.dumps([root]),
            batch_counts=json.dumps([2]),  # only 2 commitments in batch
        )
        commitment = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "2" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + "cc" * 32,
            leaf="0x" + "cc" * 32,
            leaf_index=5,  # index_in_batch=5, but count=2 → invalid
        )
        session.add_all([market, settlement, commitment])
        await session.commit()

    async with sf() as session:
        settlement = await session.get(Settlement, 1)
        commitment = await session.get(Commitment, 1)
        market = await session.get(Market, 1)
        with pytest.raises(HTTPException) as exc_info:
            await _build_merkle_proof_for_commitment(session, market, settlement, commitment)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "batch_index_invalid"


async def test_merkle_proof_raises_no_commitments_recorded():
    """No commitments in DB (even though settlement has root) → 404 no_commitments_recorded."""
    _, sf = await _make_db()
    root = "0x" + "aa" * 32
    async with sf() as session:
        market = Market(id=1, event_id="m7", title="T", oracle="0x" + "1" * 40, market_address="0x" + "1" * 40)
        settlement = Settlement(id=1, market_id=1, merkle_root=root, commitments_count=1)
        # commitment with leaf_index=0, batch_count will be 1 (from commitments_count)
        commitment = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "2" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + "cc" * 32,
            leaf="0x" + "cc" * 32,
            leaf_index=0,
        )
        # Add settlement and commitment, but NO other commitments to build leaves from
        session.add_all([market, settlement, commitment])
        await session.commit()

    # Remove the commitment to simulate "no commitments in DB for this market"
    async with sf() as session:
        c = await session.get(Commitment, 1)
        await session.delete(c)
        await session.commit()

    async with sf() as session:
        settlement = await session.get(Settlement, 1)
        market = await session.get(Market, 1)
        # Fresh commitment without DB entry — simulate lookup returns None
        commitment = Commitment(
            id=999,
            market_id=1,
            user_address="0x" + "2" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + "cc" * 32,
            leaf="0x" + "cc" * 32,
            leaf_index=0,
        )
        with pytest.raises(HTTPException) as exc_info:
            await _build_merkle_proof_for_commitment(session, market, settlement, commitment)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "no_commitments_recorded"


async def test_merkle_proof_raises_batch_leaf_missing():
    """2 commitments expected in batch but only 1 present → 409 batch_leaf_missing."""
    _, sf = await _make_db()
    leaf0 = _make_leaf(0xAA)
    root_bytes, _ = build_merkle_root_and_paths([leaf0, leaf0])  # placeholder root
    root = "0x" + root_bytes.hex()

    async with sf() as session:
        market = Market(id=1, event_id="m8", title="T", oracle="0x" + "1" * 40, market_address="0x" + "1" * 40)
        settlement = Settlement(id=1, market_id=1, merkle_root=root, commitments_count=2)  # expects 2
        # Only add 1 commitment (leaf_index=0), leaf_index=1 is missing
        commitment0 = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "2" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + leaf0.hex(),
            leaf="0x" + leaf0.hex(),
            leaf_index=0,
        )
        session.add_all([market, settlement, commitment0])
        await session.commit()

    async with sf() as session:
        settlement = await session.get(Settlement, 1)
        commitment = await session.get(Commitment, 1)
        market = await session.get(Market, 1)
        with pytest.raises(HTTPException) as exc_info:
            await _build_merkle_proof_for_commitment(session, market, settlement, commitment)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "batch_leaf_missing"


async def test_merkle_proof_raises_root_mismatch():
    """All leaves present but computed root != stored root → 409 merkle_root_mismatch."""
    _, sf = await _make_db()
    leaf0 = _make_leaf(0x11)
    leaf1 = _make_leaf(0x22)
    wrong_root = "0x" + (b"\xff" * 32).hex()  # Wrong root

    async with sf() as session:
        market = Market(id=1, event_id="m9", title="T", oracle="0x" + "1" * 40, market_address="0x" + "1" * 40)
        settlement = Settlement(id=1, market_id=1, merkle_root=wrong_root, commitments_count=2)
        c0 = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "2" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + leaf0.hex(),
            leaf="0x" + leaf0.hex(),
            leaf_index=0,
        )
        c1 = Commitment(
            id=2,
            market_id=1,
            user_address="0x" + "3" * 40,
            outcome_id=1,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + leaf1.hex(),
            leaf="0x" + leaf1.hex(),
            leaf_index=1,
        )
        session.add_all([market, settlement, c0, c1])
        await session.commit()

    async with sf() as session:
        settlement = await session.get(Settlement, 1)
        commitment = await session.get(Commitment, 1)
        market = await session.get(Market, 1)
        with pytest.raises(HTTPException) as exc_info:
            await _build_merkle_proof_for_commitment(session, market, settlement, commitment)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "merkle_root_mismatch"


# ---------------------------------------------------------------------------
# Group B: Happy Path
# ---------------------------------------------------------------------------


async def test_merkle_proof_returns_stored_path_without_recomputing():
    """Pre-seeded CommitmentMerklePath rows (all levels) returned directly without recomputing."""
    _, sf = await _make_db()
    leaf0 = _make_leaf(0x01)
    leaf1 = _make_leaf(0x02)
    root_bytes, paths = build_merkle_root_and_paths([leaf0, leaf1])
    root = "0x" + root_bytes.hex()
    # All sibling hashes at every level of the proof for leaf 0
    stored_proof = ["0x" + s.hex() for s in paths[0]]

    async with sf() as session:
        market = Market(id=1, event_id="m10", title="T", oracle="0x" + "1" * 40, market_address="0x" + "1" * 40)
        settlement = Settlement(id=1, market_id=1, merkle_root=root, commitments_count=2)
        c0 = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "2" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + leaf0.hex(),
            leaf="0x" + leaf0.hex(),
            leaf_index=0,
        )
        session.add_all([market, settlement, c0])
        # Pre-seed ALL merkle path levels so the stored-path branch is taken
        for level, sibling_hex in enumerate(stored_proof):
            session.add(CommitmentMerklePath(commitment_id=1, level=level, sibling_hash=sibling_hex))
        await session.commit()

    async with sf() as session:
        settlement = await session.get(Settlement, 1)
        commitment = await session.get(Commitment, 1)
        market = await session.get(Market, 1)
        proof = await _build_merkle_proof_for_commitment(session, market, settlement, commitment)

    assert proof == stored_proof


async def test_merkle_proof_computes_and_persists_new_path():
    """No stored path: function computes proof, writes CommitmentMerklePath, returns correct proof."""
    from sqlalchemy import select

    _, sf = await _make_db()
    leaf0 = _make_leaf(0x01)
    leaf1 = _make_leaf(0x02)
    root_bytes, paths = build_merkle_root_and_paths([leaf0, leaf1])
    root = "0x" + root_bytes.hex()

    async with sf() as session:
        market = Market(id=1, event_id="m11", title="T", oracle="0x" + "1" * 40, market_address="0x" + "1" * 40)
        settlement = Settlement(id=1, market_id=1, merkle_root=root, commitments_count=2)
        c0 = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "2" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + leaf0.hex(),
            leaf="0x" + leaf0.hex(),
            leaf_index=0,
        )
        c1 = Commitment(
            id=2,
            market_id=1,
            user_address="0x" + "3" * 40,
            outcome_id=1,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + leaf1.hex(),
            leaf="0x" + leaf1.hex(),
            leaf_index=1,
        )
        session.add_all([market, settlement, c0, c1])
        await session.commit()

    async with sf() as session:
        settlement = await session.get(Settlement, 1)
        commitment = await session.get(Commitment, 1)
        market = await session.get(Market, 1)
        proof = await _build_merkle_proof_for_commitment(session, market, settlement, commitment)
        assert proof, "Proof should be non-empty"
        # Path should now be persisted
        rows = (
            (await session.execute(select(CommitmentMerklePath).where(CommitmentMerklePath.commitment_id == 1)))
            .scalars()
            .all()
        )
        assert rows, "Path should have been persisted"


async def test_merkle_proof_persists_path_only_once():
    """Calling the function twice doesn't create duplicate CommitmentMerklePath rows."""
    from sqlalchemy import select

    _, sf = await _make_db()
    leaf0 = _make_leaf(0x01)
    leaf1 = _make_leaf(0x02)
    root_bytes, _ = build_merkle_root_and_paths([leaf0, leaf1])
    root = "0x" + root_bytes.hex()

    async with sf() as session:
        market = Market(id=1, event_id="m12", title="T", oracle="0x" + "1" * 40, market_address="0x" + "1" * 40)
        settlement = Settlement(id=1, market_id=1, merkle_root=root, commitments_count=2)
        c0 = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "2" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + leaf0.hex(),
            leaf="0x" + leaf0.hex(),
            leaf_index=0,
        )
        c1 = Commitment(
            id=2,
            market_id=1,
            user_address="0x" + "3" * 40,
            outcome_id=1,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + leaf1.hex(),
            leaf="0x" + leaf1.hex(),
            leaf_index=1,
        )
        session.add_all([market, settlement, c0, c1])
        await session.commit()

    # First call — computes and persists the path
    async with sf() as session:
        settlement = await session.get(Settlement, 1)
        commitment = await session.get(Commitment, 1)
        market = await session.get(Market, 1)
        await _build_merkle_proof_for_commitment(session, market, settlement, commitment)
        await session.commit()

    # Count rows after first call
    async with sf() as session:
        rows_after_first = (
            (await session.execute(select(CommitmentMerklePath).where(CommitmentMerklePath.commitment_id == 1)))
            .scalars()
            .all()
        )
        count_after_first = len(rows_after_first)
    assert count_after_first > 0, "Path should be persisted after first call"

    # Second call — should use stored path, not create additional rows
    async with sf() as session:
        settlement = await session.get(Settlement, 1)
        commitment = await session.get(Commitment, 1)
        market = await session.get(Market, 1)
        await _build_merkle_proof_for_commitment(session, market, settlement, commitment)

    async with sf() as session:
        rows_after_second = (
            (await session.execute(select(CommitmentMerklePath).where(CommitmentMerklePath.commitment_id == 1)))
            .scalars()
            .all()
        )
        assert len(rows_after_second) == count_after_first, "Second call must not duplicate path rows"


async def test_merkle_proof_verifies_proof_against_root():
    """Returned proof correctly chains from leaf to root via Poseidon."""
    from shared.poseidon import int_to_bytes32, poseidon_t3

    _, sf = await _make_db()
    leaf0 = _make_leaf(0x01)
    leaf1 = _make_leaf(0x02)
    root_bytes, paths = build_merkle_root_and_paths([leaf0, leaf1])
    root = "0x" + root_bytes.hex()

    async with sf() as session:
        market = Market(id=1, event_id="m13", title="T", oracle="0x" + "1" * 40, market_address="0x" + "1" * 40)
        settlement = Settlement(id=1, market_id=1, merkle_root=root, commitments_count=2)
        c0 = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "2" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + leaf0.hex(),
            leaf="0x" + leaf0.hex(),
            leaf_index=0,
        )
        c1 = Commitment(
            id=2,
            market_id=1,
            user_address="0x" + "3" * 40,
            outcome_id=1,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + leaf1.hex(),
            leaf="0x" + leaf1.hex(),
            leaf_index=1,
        )
        session.add_all([market, settlement, c0, c1])
        await session.commit()

    async with sf() as session:
        settlement = await session.get(Settlement, 1)
        commitment = await session.get(Commitment, 1)
        market = await session.get(Market, 1)
        proof = await _build_merkle_proof_for_commitment(session, market, settlement, commitment)

    # Recompute root from proof
    computed = leaf0
    idx = 0  # leaf_index=0
    for sibling_hex in proof:
        sibling = bytes.fromhex(sibling_hex[2:])
        if idx & 1:
            computed = int_to_bytes32(poseidon_t3(int.from_bytes(sibling, "big"), int.from_bytes(computed, "big")))
        else:
            computed = int_to_bytes32(poseidon_t3(int.from_bytes(computed, "big"), int.from_bytes(sibling, "big")))
        idx //= 2
    assert computed == root_bytes


async def test_merkle_proof_single_leaf_market():
    """Market with 1 commitment (leaf_index=0, count=1) → proof may be empty (root is the leaf)."""
    _, sf = await _make_db()
    leaf0 = _make_leaf(0x42)
    root_bytes, paths = build_merkle_root_and_paths([leaf0])
    root = "0x" + root_bytes.hex()

    async with sf() as session:
        market = Market(id=1, event_id="m14", title="T", oracle="0x" + "1" * 40, market_address="0x" + "1" * 40)
        settlement = Settlement(id=1, market_id=1, merkle_root=root, commitments_count=1)
        c0 = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "2" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + leaf0.hex(),
            leaf="0x" + leaf0.hex(),
            leaf_index=0,
        )
        session.add_all([market, settlement, c0])
        await session.commit()

    async with sf() as session:
        settlement = await session.get(Settlement, 1)
        commitment = await session.get(Commitment, 1)
        market = await session.get(Market, 1)
        # Should not raise
        proof = await _build_merkle_proof_for_commitment(session, market, settlement, commitment)
        assert isinstance(proof, list)


async def test_merkle_proof_raises_batch_root_missing_empty_hex():
    """batch_roots contains an empty string entry → 409 batch_root_missing."""
    import json

    _, sf = await _make_db()
    async with sf() as session:
        market = Market(id=1, event_id="m15", title="T", oracle="0x" + "1" * 40, market_address="0x" + "1" * 40)
        # batch_roots has one entry that is empty string → triggers "batch_root_missing"
        settlement = Settlement(
            id=1,
            market_id=1,
            batch_roots=json.dumps([""]),
            batch_counts=json.dumps([1]),
        )
        commitment = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "2" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + "cc" * 32,
            leaf="0x" + "cc" * 32,
            leaf_index=0,
        )
        session.add_all([market, settlement, commitment])
        await session.commit()

    async with sf() as session:
        settlement = await session.get(Settlement, 1)
        commitment = await session.get(Commitment, 1)
        market = await session.get(Market, 1)
        with pytest.raises(HTTPException) as exc_info:
            await _build_merkle_proof_for_commitment(session, market, settlement, commitment)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "batch_root_missing"


async def test_merkle_proof_multi_batch_selects_correct_batch():
    """3 batches; commitment.leaf_index in batch 2 → only batch 2 leaves used, returns valid proof."""
    import json

    _, sf = await _make_db()
    # Only batch 2 has a real leaf; batches 0 and 1 have placeholder roots
    leaf_batch2 = _make_leaf(0x33)
    root_bytes, paths = build_merkle_root_and_paths([leaf_batch2])
    root_batch2 = "0x" + root_bytes.hex()

    async with sf() as session:
        market = Market(id=1, event_id="m16", title="T", oracle="0x" + "1" * 40, market_address="0x" + "1" * 40)
        settlement = Settlement(
            id=1,
            market_id=1,
            batch_roots=json.dumps(["0x" + "aa" * 32, "0x" + "bb" * 32, root_batch2]),
            batch_counts=json.dumps([1, 1, 1]),  # 1 commitment in each batch
        )
        # Commitment lives in batch 2 (leaf_index = BATCH_SIZE * 2)
        c_batch2 = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "2" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + leaf_batch2.hex(),
            leaf="0x" + leaf_batch2.hex(),
            leaf_index=BATCH_SIZE * 2,
        )
        session.add_all([market, settlement, c_batch2])
        await session.commit()

    async with sf() as session:
        settlement = await session.get(Settlement, 1)
        commitment = await session.get(Commitment, 1)
        market = await session.get(Market, 1)
        # Should NOT raise — batch 2 has valid leaves and matching root
        proof = await _build_merkle_proof_for_commitment(session, market, settlement, commitment)
        assert isinstance(proof, list)
