import pytest
from shared.models import Base, Commitment, Settlement
from shared.poseidon import int_to_bytes32, poseidon_t3
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from worker.app.merkle import build_merkle_root_and_paths
from worker.app.proof_builder import SettlementDataMissingError, build_prover_payload


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    sess = session_local()
    try:
        yield sess
    finally:
        sess.close()
        engine.dispose()


def test_merkle_root_and_paths():
    leaves = [b"a" * 32, b"b" * 32, b"c" * 32]
    root, paths = build_merkle_root_and_paths(leaves)
    assert root and len(paths) == 3
    # Recompute root for leaf 0 using path
    computed = leaves[0]
    idx = 0
    for sibling in paths[0]:
        if idx & 1:
            computed = int_to_bytes32(poseidon_t3(int.from_bytes(sibling, "big"), int.from_bytes(computed, "big")))
        else:
            computed = int_to_bytes32(poseidon_t3(int.from_bytes(computed, "big"), int.from_bytes(sibling, "big")))
        idx >>= 1
    assert computed == root


def test_build_prover_payload(session):
    # Insert commitments
    leaves = ["0x" + ("a" * 64), "0x" + ("b" * 64)]
    for i, leaf in enumerate(leaves):
        ticket_hash = f"0x{i + 1:064x}"
        c = Commitment(
            id=i + 1,
            market_id=1,
            user_address="0x0000000000000000000000000000000000000abc",
            outcome_id=i % 2,
            amount_wei=100 + i,
            payout_wei=120 + i,
            salt="0x1",
            ticket_hash=ticket_hash,
            leaf=leaf,
            leaf_index=i,
        )
        session.add(c)
    session.commit()

    # Settlement row
    # Compute canonical root for these leaves.
    root, _ = build_merkle_root_and_paths([bytes.fromhex(leaf.removeprefix("0x")) for leaf in leaves])
    s = Settlement(
        id=1,
        market_id=1,
        merkle_root="0x" + root.hex(),
        commitments_count=2,
        pool_total_yes=100,
        pool_total_no=101,
        total_escrow=201,
        total_liability=121,
        rake_bps=100,
        winning_outcome_id=1,
        circuit_hash="0xdead",
    )
    session.add(s)
    session.commit()

    payloads = build_prover_payload(session, 1)
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["marketId"] == "1"
    assert payload["merkleRoot"] == "0x" + root.hex()
    assert payload["batchIndex"] == "0"
    assert payload["commitmentsCount"] == "2"
    assert payload["tickets"]
    assert "payoutMultiplierWad" not in payload
    assert payload["poolTotals"] == ["100", "101"]


def test_build_prover_payload_missing_data(session):
    session.add(Settlement(id=1, market_id=1))
    session.commit()
    with pytest.raises(SettlementDataMissingError):
        build_prover_payload(session, 1)


# ---------------------------------------------------------------------------
# Regression: Bug 1 — worker claim payload must include ``payout``
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_claim_payload_includes_payout():
    """_build_relayer_claim_payloads must include the ``payout`` field.

    The relayer requires ``payout`` via ``_require_field``.  Without it every
    worker-initiated auto-claim is rejected.
    """
    from unittest.mock import AsyncMock, patch

    from shared.models import Base, Commitment, Market, Settlement
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, future=True, expire_on_commit=False)

    leaf_hex = "0x" + "ab" * 32
    leaf_bytes = bytes.fromhex(leaf_hex[2:])
    root, paths = build_merkle_root_and_paths([leaf_bytes])
    merkle_root = "0x" + root.hex()
    dummy_proof = ["0x" + sibling.hex() for sibling in paths[0]]

    async with session_factory() as session:
        market = Market(
            id=1,
            event_id="payout-test",
            title="Payout Test",
            oracle="0x" + "1" * 40,
            market_address="0x" + "2" * 40,
            status="commit",
        )
        settlement = Settlement(
            id=1,
            market_id=1,
            merkle_root=merkle_root,
            commitments_count=1,
            winning_outcome_id=0,
        )
        commitment = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "3" * 40,
            outcome_id=0,
            amount_wei=1_000_000_000_000_000_000,
            payout_wei=1_500_000_000_000_000_000,
            salt="0x" + "4" * 64,
            ticket_hash=leaf_hex,
            leaf=leaf_hex,
            leaf_index=0,
        )
        session.add_all([market, settlement, commitment])
        await session.commit()

    with patch(
        "app.settlement._build_merkle_proof_for_commitment",
        new_callable=AsyncMock,
        return_value=dummy_proof,
    ):
        from app.settlement import _build_relayer_claim_payloads

        async with session_factory() as session:
            payloads = await _build_relayer_claim_payloads(session, market, settlement)

    assert len(payloads) == 1
    payload = payloads[0]
    assert "payout" in payload, "worker claim payload must include 'payout'"
    assert payload["payout"] == 1_500_000_000_000_000_000
    assert payload["amount"] == 1_000_000_000_000_000_000
