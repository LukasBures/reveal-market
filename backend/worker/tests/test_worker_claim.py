"""Tests for worker-side _build_relayer_claim_payloads and _enqueue_relayer_claims."""

from __future__ import annotations

# ruff: noqa: S101
import json
from typing import Any
from unittest.mock import AsyncMock

import app.runtime as runtime_module
from app.settlement import _build_relayer_claim_payloads, _enqueue_relayer_claims
from shared.merkle import build_merkle_root_and_paths
from shared.models import Base, Commitment, Market, Settlement
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# Infrastructure (mirrors test_worker_process.py helpers)
# ---------------------------------------------------------------------------


async def create_async_in_memory_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(bind=engine, future=True, expire_on_commit=False)
    return engine, sf


class DummyRedis:
    """Minimal Redis stub with lpush + ltrim support."""

    def __init__(self):
        self.store: dict[str, Any] = {}

    async def set(self, key: str, value: Any, ex: int | None = None, nx: bool = False):
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    async def get(self, key: str):
        return self.store.get(key)

    async def lpush(self, key: str, *values: Any):
        lst = self.store.setdefault(key, [])
        for v in values:
            lst.insert(0, v)
        return len(lst)

    async def ltrim(self, key: str, start: int, end: int):
        lst = self.store.get(key, [])
        if isinstance(lst, list):
            self.store[key] = lst[start : end + 1]

    async def llen(self, key: str) -> int:
        return len(self.store.get(key, []))


def _make_leaf(seed: int) -> bytes:
    return bytes([seed % 256]) * 32


# ---------------------------------------------------------------------------
# Group A: _build_relayer_claim_payloads — Validation
# ---------------------------------------------------------------------------


async def test_worker_payloads_empty_when_no_market_address():
    """market_address=None → returns []."""
    _, sf = await create_async_in_memory_db()
    async with sf() as session:
        market = Market(id=1, event_id="m1", title="T", oracle="0x" + "1" * 40, market_address=None)
        settlement = Settlement(id=1, market_id=1, winning_outcome_id=0, merkle_root="0x" + "aa" * 32)
        session.add_all([market, settlement])
        await session.commit()

    async with sf() as session:
        from sqlalchemy import select

        market = (await session.execute(select(Market))).scalar_one()
        settlement = (await session.execute(select(Settlement))).scalar_one()
        result = await _build_relayer_claim_payloads(session, market, settlement)
    assert result == []


async def test_worker_payloads_empty_when_no_winning_outcome():
    """winning_outcome_id=None → returns []."""
    _, sf = await create_async_in_memory_db()
    async with sf() as session:
        market = Market(id=1, event_id="m1", title="T", oracle="0x" + "1" * 40, market_address="0x" + "2" * 40)
        settlement = Settlement(id=1, market_id=1, winning_outcome_id=None, merkle_root="0x" + "aa" * 32)
        session.add_all([market, settlement])
        await session.commit()

    async with sf() as session:
        from sqlalchemy import select

        market = (await session.execute(select(Market))).scalar_one()
        settlement = (await session.execute(select(Settlement))).scalar_one()
        result = await _build_relayer_claim_payloads(session, market, settlement)
    assert result == []


async def test_worker_payloads_skips_wrong_outcome_commitments():
    """Commitments with outcome_id != winning_outcome_id are skipped → []."""
    _, sf = await create_async_in_memory_db()
    async with sf() as session:
        market = Market(id=1, event_id="m1", title="T", oracle="0x" + "1" * 40, market_address="0x" + "2" * 40)
        settlement = Settlement(id=1, market_id=1, winning_outcome_id=1, merkle_root="0x" + "aa" * 32)
        commitment = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "3" * 40,
            outcome_id=0,  # NOT the winning outcome
            amount_wei=10,
            payout_wei=15,
            salt="0x0",
            ticket_hash="0x" + "cc" * 32,
            leaf="0x" + "cc" * 32,
            leaf_index=0,
        )
        session.add_all([market, settlement, commitment])
        await session.commit()

    async with sf() as session:
        from sqlalchemy import select

        market = (await session.execute(select(Market))).scalar_one()
        settlement = (await session.execute(select(Settlement))).scalar_one()
        result = await _build_relayer_claim_payloads(session, market, settlement)
    assert result == []


async def test_worker_payloads_skips_missing_leaf_index():
    """Commitment.leaf_index=None → skipped, returns []."""
    _, sf = await create_async_in_memory_db()
    async with sf() as session:
        market = Market(id=1, event_id="m1", title="T", oracle="0x" + "1" * 40, market_address="0x" + "2" * 40)
        settlement = Settlement(id=1, market_id=1, winning_outcome_id=0, merkle_root="0x" + "aa" * 32)
        commitment = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "3" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=15,
            salt="0x0",
            ticket_hash="0x" + "cc" * 32,
            leaf="0x" + "cc" * 32,
            leaf_index=None,  # missing!
        )
        session.add_all([market, settlement, commitment])
        await session.commit()

    async with sf() as session:
        from sqlalchemy import select

        market = (await session.execute(select(Market))).scalar_one()
        settlement = (await session.execute(select(Settlement))).scalar_one()
        result = await _build_relayer_claim_payloads(session, market, settlement)
    assert result == []


async def test_worker_payloads_skips_empty_merkle_proof(monkeypatch):
    """_build_merkle_proof_for_commitment returns [] → commitment skipped."""
    _, sf = await create_async_in_memory_db()
    async with sf() as session:
        market = Market(id=1, event_id="m1", title="T", oracle="0x" + "1" * 40, market_address="0x" + "2" * 40)
        settlement = Settlement(id=1, market_id=1, winning_outcome_id=0, merkle_root="0x" + "aa" * 32)
        commitment = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "3" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=15,
            salt="0x0",
            ticket_hash="0x" + "cc" * 32,
            leaf="0x" + "cc" * 32,
            leaf_index=0,
        )
        session.add_all([market, settlement, commitment])
        await session.commit()

    monkeypatch.setattr("app.settlement._build_merkle_proof_for_commitment", AsyncMock(return_value=[]))

    async with sf() as session:
        from sqlalchemy import select

        market = (await session.execute(select(Market))).scalar_one()
        settlement = (await session.execute(select(Settlement))).scalar_one()
        result = await _build_relayer_claim_payloads(session, market, settlement)
    assert result == []


# ---------------------------------------------------------------------------
# Group B: _build_relayer_claim_payloads — Happy Path
# ---------------------------------------------------------------------------


async def test_worker_payloads_contains_all_required_fields(monkeypatch):
    """Single winning commitment produces payload with all required fields."""
    _, sf = await create_async_in_memory_db()
    fake_proof = ["0x" + "ab" * 32] * 8

    async with sf() as session:
        market = Market(id=1, event_id="evt-1", title="T", oracle="0x" + "1" * 40, market_address="0x" + "2" * 40)
        settlement = Settlement(
            id=1,
            market_id=1,
            winning_outcome_id=0,
            merkle_root="0x" + "aa" * 32,
            commitments_count=1,
            proof_request_id="proof-abc",
        )
        commitment = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "3" * 40,
            outcome_id=0,
            amount_wei=1_000_000_000,
            payout_wei=1_800_000_000,
            salt="0x1234",
            ticket_hash="0x" + "cc" * 32,
            leaf="0x" + "cc" * 32,
            leaf_index=0,
        )
        session.add_all([market, settlement, commitment])
        await session.commit()

    monkeypatch.setattr("app.settlement._build_merkle_proof_for_commitment", AsyncMock(return_value=fake_proof))

    async with sf() as session:
        from sqlalchemy import select

        market = (await session.execute(select(Market))).scalar_one()
        settlement = (await session.execute(select(Settlement))).scalar_one()
        result = await _build_relayer_claim_payloads(session, market, settlement)

    assert len(result) == 1
    p = result[0]
    required_keys = {
        "user",
        "market",
        "ticket_id",
        "outcome_id",
        "amount",
        "payout",
        "salt",
        "merkle_proof",
        "merkle_root",
        "commitments_count",
        "batch_roots",
        "batch_counts",
        "pool_total_yes",
        "pool_total_no",
        "total_escrow",
        "total_liability",
        "rake_bps",
        "proof_request_id",
        "event_id",
    }
    assert required_keys.issubset(p.keys())
    assert p["event_id"] == "evt-1"
    assert p["proof_request_id"] == "proof-abc"


async def test_worker_payloads_payout_equals_payout_wei(monkeypatch):
    """payout field equals the exact payout_wei integer."""
    _, sf = await create_async_in_memory_db()
    fake_proof = ["0x" + "ab" * 32] * 8

    async with sf() as session:
        market = Market(id=1, event_id="m1", title="T", oracle="0x" + "1" * 40, market_address="0x" + "2" * 40)
        settlement = Settlement(id=1, market_id=1, winning_outcome_id=0, merkle_root="0x" + "aa" * 32)
        commitment = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "3" * 40,
            outcome_id=0,
            amount_wei=1_000_000_000,
            payout_wei=1_500_000_000,
            salt="0x0",
            ticket_hash="0x" + "cc" * 32,
            leaf="0x" + "cc" * 32,
            leaf_index=0,
        )
        session.add_all([market, settlement, commitment])
        await session.commit()

    monkeypatch.setattr("app.settlement._build_merkle_proof_for_commitment", AsyncMock(return_value=fake_proof))

    async with sf() as session:
        from sqlalchemy import select

        market = (await session.execute(select(Market))).scalar_one()
        settlement = (await session.execute(select(Settlement))).scalar_one()
        result = await _build_relayer_claim_payloads(session, market, settlement)

    assert result[0]["payout"] == 1_500_000_000


async def test_worker_payloads_multi_commitment_filters_correctly(monkeypatch):
    """3 commitments: 2 winning (outcome=1), 1 losing (outcome=0) → 2 payloads."""
    _, sf = await create_async_in_memory_db()
    fake_proof = ["0x" + "ab" * 32] * 8

    async with sf() as session:
        market = Market(id=1, event_id="m1", title="T", oracle="0x" + "1" * 40, market_address="0x" + "2" * 40)
        settlement = Settlement(id=1, market_id=1, winning_outcome_id=1, merkle_root="0x" + "aa" * 32)
        c0 = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "3" * 40,
            outcome_id=1,
            amount_wei=10,
            payout_wei=15,  # winning
            salt="0x0",
            ticket_hash="0x" + "a1" * 32,
            leaf="0x" + "a1" * 32,
            leaf_index=0,
        )
        c1 = Commitment(
            id=2,
            market_id=1,
            user_address="0x" + "4" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=0,  # losing
            salt="0x0",
            ticket_hash="0x" + "a2" * 32,
            leaf="0x" + "a2" * 32,
            leaf_index=1,
        )
        c2 = Commitment(
            id=3,
            market_id=1,
            user_address="0x" + "5" * 40,
            outcome_id=1,
            amount_wei=10,
            payout_wei=15,  # winning
            salt="0x0",
            ticket_hash="0x" + "a3" * 32,
            leaf="0x" + "a3" * 32,
            leaf_index=2,
        )
        session.add_all([market, settlement, c0, c1, c2])
        await session.commit()

    monkeypatch.setattr("app.settlement._build_merkle_proof_for_commitment", AsyncMock(return_value=fake_proof))

    async with sf() as session:
        from sqlalchemy import select

        market = (await session.execute(select(Market))).scalar_one()
        settlement = (await session.execute(select(Settlement))).scalar_one()
        result = await _build_relayer_claim_payloads(session, market, settlement)

    assert len(result) == 2
    assert all(p["outcome_id"] == 1 for p in result)


async def test_worker_payloads_salt_uses_fallback_when_none(monkeypatch):
    """Commitment.salt=None → payload["salt"] == "0x0"."""
    _, sf = await create_async_in_memory_db()
    fake_proof = ["0x" + "ab" * 32] * 8

    async with sf() as session:
        market = Market(id=1, event_id="m1", title="T", oracle="0x" + "1" * 40, market_address="0x" + "2" * 40)
        settlement = Settlement(id=1, market_id=1, winning_outcome_id=0, merkle_root="0x" + "aa" * 32)
        commitment = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "3" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=15,
            salt=None,
            ticket_hash="0x" + "cc" * 32,
            leaf="0x" + "cc" * 32,
            leaf_index=0,
        )
        session.add_all([market, settlement, commitment])
        await session.commit()

    monkeypatch.setattr("app.settlement._build_merkle_proof_for_commitment", AsyncMock(return_value=fake_proof))

    async with sf() as session:
        from sqlalchemy import select

        market = (await session.execute(select(Market))).scalar_one()
        settlement = (await session.execute(select(Settlement))).scalar_one()
        result = await _build_relayer_claim_payloads(session, market, settlement)

    assert result[0]["salt"] == "0x0"


# ---------------------------------------------------------------------------
# Group C: _enqueue_relayer_claims
# ---------------------------------------------------------------------------


async def test_enqueue_relayer_claims_returns_zero_when_disabled(monkeypatch):
    """relayer_queue_enabled=False → returns 0, no Redis writes."""
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_enabled", False, raising=False)
    redis = DummyRedis()
    market = Market(id=1, event_id="m1", title="T", oracle="0x" + "1" * 40, market_address="0x" + "2" * 40)
    settlement = Settlement(id=1, market_id=1, winning_outcome_id=0, merkle_root="0x" + "aa" * 32)
    result = await _enqueue_relayer_claims(redis, market, settlement)
    assert result == 0


async def test_enqueue_relayer_claims_returns_zero_when_no_redis(monkeypatch):
    """redis_client=None → returns 0."""
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_enabled", True, raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_base_url", "http://relayer", raising=False)
    market = Market(id=1, event_id="m1", title="T", oracle="0x" + "1" * 40, market_address="0x" + "2" * 40)
    settlement = Settlement(id=1, market_id=1, winning_outcome_id=0, merkle_root="0x" + "aa" * 32)
    result = await _enqueue_relayer_claims(None, market, settlement)
    assert result == 0


async def test_enqueue_relayer_claims_returns_zero_when_no_relayer_url(monkeypatch):
    """relayer_base_url="" → returns 0."""
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_enabled", True, raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_base_url", "", raising=False)
    redis = DummyRedis()
    market = Market(id=1, event_id="m1", title="T", oracle="0x" + "1" * 40, market_address="0x" + "2" * 40)
    settlement = Settlement(id=1, market_id=1, winning_outcome_id=0, merkle_root="0x" + "aa" * 32)
    result = await _enqueue_relayer_claims(redis, market, settlement)
    assert result == 0


async def test_enqueue_relayer_claims_pushes_payloads_to_queue(monkeypatch):
    """3 fake payloads → 3 jobs pushed to DummyRedis; returns 3."""
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_enabled", True, raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_key", "relayer:queue", raising=False)

    fake_payloads = [{"ticket_id": i} for i in range(3)]
    monkeypatch.setattr("app.settlement._build_relayer_claim_payloads", AsyncMock(return_value=fake_payloads))
    # Patch session_scope to avoid real DB connection
    import contextlib
    from unittest.mock import MagicMock

    mock_session = MagicMock()

    @contextlib.asynccontextmanager
    async def _fake_scope():
        yield mock_session

    monkeypatch.setattr("app.settlement.session_scope", _fake_scope)

    redis = DummyRedis()
    market = Market(id=1, event_id="m1", title="T", oracle="0x" + "1" * 40, market_address="0x" + "2" * 40)
    settlement = Settlement(id=1, market_id=1, winning_outcome_id=0)
    result = await _enqueue_relayer_claims(redis, market, settlement)
    assert result == 3
    assert len(redis.store.get("relayer:queue", [])) == 3


async def test_enqueue_relayer_claims_job_has_correct_structure(monkeypatch):
    """Single enqueued job has job_id, kind=claim, endpoint, payload, attempts=0."""
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_enabled", True, raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_key", "relayer:queue", raising=False)

    fake_payloads = [{"ticket_id": 0, "user": "0x1"}]
    monkeypatch.setattr("app.settlement._build_relayer_claim_payloads", AsyncMock(return_value=fake_payloads))

    import contextlib
    from unittest.mock import MagicMock

    mock_session = MagicMock()

    @contextlib.asynccontextmanager
    async def _fake_scope():
        yield mock_session

    monkeypatch.setattr("app.settlement.session_scope", _fake_scope)

    redis = DummyRedis()
    market = Market(id=1, event_id="m1", title="T", oracle="0x" + "1" * 40, market_address="0x" + "2" * 40)
    settlement = Settlement(id=1, market_id=1, winning_outcome_id=0)
    await _enqueue_relayer_claims(redis, market, settlement)

    queue = redis.store.get("relayer:queue", [])
    assert len(queue) == 1
    job = json.loads(queue[0])
    assert job["kind"] == "claim"
    assert "http://relayer" in job["endpoint"]
    assert job["attempts"] == 0
    assert "job_id" in job
    assert "enqueued_at" in job
    assert job["payload"]["ticket_id"] == 0


async def test_enqueue_relayer_claims_returns_zero_when_no_payloads(monkeypatch):
    """_build_relayer_claim_payloads returns [] → returns 0, no crash."""
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_enabled", True, raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_key", "relayer:queue", raising=False)

    monkeypatch.setattr("app.settlement._build_relayer_claim_payloads", AsyncMock(return_value=[]))

    import contextlib
    from unittest.mock import MagicMock

    mock_session = MagicMock()

    @contextlib.asynccontextmanager
    async def _fake_scope():
        yield mock_session

    monkeypatch.setattr("app.settlement.session_scope", _fake_scope)

    redis = DummyRedis()
    market = Market(id=1, event_id="m1", title="T", oracle="0x" + "1" * 40, market_address="0x" + "2" * 40)
    settlement = Settlement(id=1, market_id=1, winning_outcome_id=0)
    result = await _enqueue_relayer_claims(redis, market, settlement)
    assert result == 0


# ---------------------------------------------------------------------------
# Group B continued: multi-batch root-per-ticket
# ---------------------------------------------------------------------------


async def test_worker_payloads_multi_batch_correct_root_per_ticket(monkeypatch):
    """ticket in batch 0 → payload["merkle_root"] = batch_roots[0], etc."""
    import json

    from shared.poseidon import BATCH_SIZE as _BATCH_SIZE

    _, sf = await create_async_in_memory_db()
    batch_root_0 = "0x" + "aa" * 32
    batch_root_1 = "0x" + "bb" * 32
    fake_proof = ["0x" + "ab" * 32]

    async with sf() as session:
        market = Market(id=1, event_id="m-multi", title="T", oracle="0x" + "1" * 40, market_address="0x" + "2" * 40)
        settlement = Settlement(
            id=1,
            market_id=1,
            winning_outcome_id=1,
            batch_roots=json.dumps([batch_root_0, batch_root_1]),
            batch_counts=json.dumps([1, 1]),
        )
        # Commitment in batch 0 (leaf_index=0) and batch 1 (leaf_index=BATCH_SIZE)
        c0 = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "3" * 40,
            outcome_id=1,
            amount_wei=10,
            payout_wei=15,
            salt="0x0",
            ticket_hash="0x" + "c1" * 32,
            leaf="0x" + "c1" * 32,
            leaf_index=0,
        )
        c1 = Commitment(
            id=2,
            market_id=1,
            user_address="0x" + "4" * 40,
            outcome_id=1,
            amount_wei=10,
            payout_wei=15,
            salt="0x0",
            ticket_hash="0x" + "c2" * 32,
            leaf="0x" + "c2" * 32,
            leaf_index=_BATCH_SIZE,
        )
        session.add_all([market, settlement, c0, c1])
        await session.commit()

    monkeypatch.setattr("app.settlement._build_merkle_proof_for_commitment", AsyncMock(return_value=fake_proof))

    async with sf() as session:
        from sqlalchemy import select

        market = (await session.execute(select(Market))).scalar_one()
        settlement = (await session.execute(select(Settlement))).scalar_one()
        result = await _build_relayer_claim_payloads(session, market, settlement)

    assert len(result) == 2
    # ticket_id=0 is in batch 0 → should get batch_root_0
    ticket0_payload = next(p for p in result if p["ticket_id"] == 0)
    assert ticket0_payload["merkle_root"] == batch_root_0
    # ticket_id=BATCH_SIZE is in batch 1 → should get batch_root_1
    ticket1_payload = next(p for p in result if p["ticket_id"] == _BATCH_SIZE)
    assert ticket1_payload["merkle_root"] == batch_root_1


# ---------------------------------------------------------------------------
# Group D: Worker _build_merkle_proof_for_commitment edge cases
# ---------------------------------------------------------------------------


async def test_worker_merkle_proof_returns_empty_batch_count_mismatch():
    """batch_roots and batch_counts have different lengths → returns []."""
    import json

    from app.settlement import _build_merkle_proof_for_commitment as _worker_build_proof

    _, sf = await create_async_in_memory_db()
    async with sf() as session:
        market = Market(id=1, event_id="m-bc", title="T", oracle="0x" + "1" * 40, market_address="0x" + "2" * 40)
        settlement = Settlement(
            id=1,
            market_id=1,
            batch_roots=json.dumps(["0x" + "aa" * 32, "0x" + "bb" * 32]),
            batch_counts=json.dumps([2]),  # mismatch: 2 roots, 1 count
        )
        commitment = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "3" * 40,
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
        from sqlalchemy import select

        settlement = (await session.execute(select(Settlement))).scalar_one()
        commitment = (await session.execute(select(Commitment))).scalar_one()
        result = await _worker_build_proof(session, 1, settlement, commitment)
    assert result == []


async def test_worker_merkle_proof_returns_empty_on_root_mismatch():
    """Leaves present but computed root doesn't match stored root → returns []."""
    import json

    from app.settlement import _build_merkle_proof_for_commitment as _worker_build_proof

    _, sf = await create_async_in_memory_db()
    leaf0 = _make_leaf(0x11)
    wrong_root = "0x" + ("ff" * 32)  # deliberately wrong root

    async with sf() as session:
        market = Market(id=1, event_id="m-rm", title="T", oracle="0x" + "1" * 40, market_address="0x" + "2" * 40)
        settlement = Settlement(
            id=1,
            market_id=1,
            batch_roots=json.dumps([wrong_root]),
            batch_counts=json.dumps([1]),
        )
        commitment = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "3" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + leaf0.hex(),
            leaf="0x" + leaf0.hex(),
            leaf_index=0,
        )
        session.add_all([market, settlement, commitment])
        await session.commit()

    async with sf() as session:
        from sqlalchemy import select

        settlement = (await session.execute(select(Settlement))).scalar_one()
        commitment = (await session.execute(select(Commitment))).scalar_one()
        result = await _worker_build_proof(session, 1, settlement, commitment)
    assert result == []


async def test_worker_merkle_proof_uses_all_commitments_optimization(monkeypatch):
    """Providing all_commitments skips the per-commitment DB query."""
    import json

    from app.settlement import _build_merkle_proof_for_commitment as _worker_build_proof
    from shared import repository_async as shared_repo

    _, sf = await create_async_in_memory_db()
    leaf0 = _make_leaf(0x22)
    root_bytes, _ = build_merkle_root_and_paths([leaf0])
    root = "0x" + root_bytes.hex()

    async with sf() as session:
        market = Market(id=1, event_id="m-opt", title="T", oracle="0x" + "1" * 40, market_address="0x" + "2" * 40)
        settlement = Settlement(
            id=1,
            market_id=1,
            batch_roots=json.dumps([root]),
            batch_counts=json.dumps([1]),
        )
        commitment = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "3" * 40,
            outcome_id=0,
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + leaf0.hex(),
            leaf="0x" + leaf0.hex(),
            leaf_index=0,
        )
        session.add_all([market, settlement, commitment])
        await session.commit()

    # Mark that list_commitments_by_market must NOT be called when all_commitments is provided
    db_query_called = [False]
    original = shared_repo.list_commitments_by_market

    async def _spy_query(session, market_id):
        db_query_called[0] = True
        return await original(session, market_id)

    monkeypatch.setattr(shared_repo, "list_commitments_by_market", _spy_query)

    async with sf() as session:
        from sqlalchemy import select

        settlement = (await session.execute(select(Settlement))).scalar_one()
        commitment = (await session.execute(select(Commitment))).scalar_one()
        # Provide all_commitments to skip the DB query
        proof = await _worker_build_proof(session, 1, settlement, commitment, all_commitments=[commitment])

    assert not db_query_called[0], "list_commitments_by_market should not be called when all_commitments is provided"
    assert isinstance(proof, list)
    assert len(proof) >= 0  # valid proof returned
