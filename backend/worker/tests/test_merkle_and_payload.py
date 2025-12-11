import pytest
from shared.models import Base, Commitment, Settlement
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
    from eth_utils import keccak

    computed = leaves[0]
    idx = 0
    for sibling in paths[0]:
        if idx & 1:
            computed = keccak(sibling + computed)
        else:
            computed = keccak(computed + sibling)
        idx >>= 1
    assert computed == root


def test_build_prover_payload(session):
    # Insert commitments
    leaves = ["0x" + ("a" * 64), "0x" + ("b" * 64)]
    for i, leaf in enumerate(leaves):
        ticket_hash = "0x" + ("1" * 64)
        c = Commitment(
            id=i + 1,
            market_id=1,
            user_address="0x0000000000000000000000000000000000000abc",
            outcome_id=i % 2,
            amount_wei=100 + i,
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
        total_liability=202,
        rake_bps=100,
        winning_outcome_id=1,
        circuit_hash="0xdead",
    )
    session.add(s)
    session.commit()

    payload = build_prover_payload(session, 1)
    assert payload["marketId"] == "1"
    assert payload["merkleRoot"] == "0x" + root.hex()
    assert "tickets" not in payload
    assert "payoutMultiplierWad" not in payload
    assert payload["poolTotals"] == ["100", "101"]


def test_build_prover_payload_missing_data(session):
    session.add(Settlement(id=1, market_id=1))
    session.commit()
    with pytest.raises(SettlementDataMissingError):
        build_prover_payload(session, 1)
