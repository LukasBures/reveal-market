from __future__ import annotations

import pytest
from app.settlement import LockBatchDataError, _build_batch_roots_from_commitments
from shared.merkle import build_merkle_root_and_paths
from shared.models import Commitment
from shared.poseidon import compute_leaf, int_to_hex32


def _make_commitment(ticket_id: int, outcome_id: int, amount: int, user: str, salt: str) -> Commitment:
    leaf_int = compute_leaf(ticket_id, outcome_id, amount, user, salt)
    leaf_hex = int_to_hex32(leaf_int)
    return Commitment(
        market_id=1,
        user_address=user,
        outcome_id=outcome_id,
        amount_wei=amount,
        salt=salt,
        ticket_hash=leaf_hex,
        leaf=leaf_hex,
        leaf_index=ticket_id,
    )


def test_build_batch_roots_from_commitments_matches_merkle():
    commitments = [
        _make_commitment(
            ticket_id=0,
            outcome_id=0,
            amount=10,
            user="0x0000000000000000000000000000000000000001",
            salt="0x" + "1" * 64,
        ),
        _make_commitment(
            ticket_id=1,
            outcome_id=1,
            amount=20,
            user="0x0000000000000000000000000000000000000002",
            salt="0x" + "2" * 64,
        ),
    ]
    batch_roots, batch_counts, total_count, merkle_root = _build_batch_roots_from_commitments(commitments)

    leaves = [bytes.fromhex(c.leaf.removeprefix("0x")) for c in commitments]
    expected_root, _ = build_merkle_root_and_paths(leaves)
    assert batch_roots == ["0x" + expected_root.hex()]
    assert batch_counts == [2]
    assert total_count == 2
    assert merkle_root == batch_roots[0]


def test_build_batch_roots_requires_leaf_index():
    commitment = _make_commitment(
        ticket_id=0,
        outcome_id=0,
        amount=10,
        user="0x0000000000000000000000000000000000000001",
        salt="0x" + "1" * 64,
    )
    commitment.leaf_index = None

    with pytest.raises(LockBatchDataError):
        _build_batch_roots_from_commitments([commitment])
