"""Tests for run_settlement_jobs edge cases in worker settlement pipeline."""

from __future__ import annotations

# ruff: noqa: S101
import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import app.database as db
import app.market_sync as market_sync
import app.runtime as runtime_module
from app import settlement as settlement_module
from eth_account import Account
from pydantic import SecretStr
from shared import models as shared_models
from shared.models import Base, Market, Settlement
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def create_async_in_memory_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(bind=engine, future=True, expire_on_commit=False)
    return engine, sf


class DummyRedis:
    """Redis stub for settlement tests, compatible with invalidate_cache_tags and retry helpers."""

    def __init__(self):
        self.store: dict[str, Any] = {}
        self._ttls: dict[str, int | None] = {}

    async def set(self, key: str, value: Any, ex: int | None = None, nx: bool = False):
        if nx and key in self.store:
            return False
        self.store[key] = value
        self._ttls[key] = ex
        return True

    async def get(self, key: str):
        return self.store.get(key)

    async def delete(self, *keys: str):
        for key in keys:
            self.store.pop(key, None)

    async def expire(self, key: str, ttl_seconds: int):
        self._ttls[key] = ttl_seconds
        return 1

    async def lpush(self, key: str, *values: Any):
        lst = self.store.setdefault(key, [])
        for v in values:
            lst.insert(0, v)

    async def ltrim(self, key: str, start: int, end: int):
        lst = self.store.get(key, [])
        if isinstance(lst, list):
            self.store[key] = lst[start : end + 1]

    async def llen(self, key: str):
        return len(self.store.get(key, []))

    async def scan_iter(self, match: str):
        prefix = match[:-1] if match.endswith("*") else match
        for key in list(self.store.keys()):
            if key.startswith(prefix):
                yield key

    async def sscan_iter(self, key: str, count: int | None = None):
        members = self.store.get(key, set())
        if isinstance(members, set):
            for member in members:
                yield member

    async def sadd(self, key: str, *values: str):
        bucket = self.store.setdefault(key, set())
        if not isinstance(bucket, set):
            bucket = set()
            self.store[key] = bucket
        before = len(bucket)
        bucket.update(values)
        return len(bucket) - before

    async def smembers(self, key: str):
        members = self.store.get(key)
        if isinstance(members, set):
            return set(members)
        return set()

    async def hgetall(self, key: str) -> dict:
        val = self.store.get(key, {})
        return val if isinstance(val, dict) else {}

    async def hset(self, key: str, mapping: dict | None = None, **kwargs) -> int:
        existing = self.store.setdefault(key, {})
        if not isinstance(existing, dict):
            existing = {}
            self.store[key] = existing
        update = mapping or kwargs
        existing.update(update)
        return len(update)

    # lock release helper used by _release_settlement_lock via Lua script
    async def execute_command(self, *args, **kwargs):  # pragma: no cover
        return None


# ---------------------------------------------------------------------------
# Tests: Guard conditions
# ---------------------------------------------------------------------------


async def test_settlement_jobs_no_settlements_returns_zero(monkeypatch):
    """Empty DB → run_settlement_jobs returns 0."""
    signer = Account.create()
    monkeypatch.setattr(
        runtime_module.settings,
        "settlement_signer_private_key",
        SecretStr(signer._private_key.hex()),
        raising=False,
    )
    monkeypatch.setattr(runtime_module.settings, "rpc_url", "http://fake-rpc", raising=False)
    monkeypatch.setattr(runtime_module.settings, "settlement_rpc_url", None, raising=False)

    engine, sf = await create_async_in_memory_db()
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", sf, raising=False)

    mock_web3 = MagicMock()
    monkeypatch.setattr("app.settlement.get_async_web3", lambda _: mock_web3)

    redis = DummyRedis()
    summary = market_sync.SyncSummary()
    result = await settlement_module.run_settlement_jobs(summary, redis)
    assert result == 0


async def test_settlement_jobs_skips_when_lock_held(monkeypatch):
    """Settlement submission lock already held → settlement skipped; returns 0."""
    signer = Account.create()
    monkeypatch.setattr(
        runtime_module.settings,
        "settlement_signer_private_key",
        SecretStr(signer._private_key.hex()),
        raising=False,
    )
    monkeypatch.setattr(runtime_module.settings, "rpc_url", "http://fake-rpc", raising=False)
    monkeypatch.setattr(runtime_module.settings, "settlement_rpc_url", None, raising=False)

    engine, sf = await create_async_in_memory_db()
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", sf, raising=False)

    mock_web3 = MagicMock()
    monkeypatch.setattr("app.settlement.get_async_web3", lambda _: mock_web3)
    # Lock already held → returns (None, key)
    monkeypatch.setattr("app.settlement._acquire_settlement_submission_lock", AsyncMock(return_value=(None, "key")))

    async with sf() as session:
        market = Market(
            event_id="evt-locked",
            title="T",
            category="sports",
            oracle="polymarket",
            status="settled",
            resolution_status="final",
            market_address="0x" + "A" * 40,
            resolved_at=datetime.now(UTC),
        )
        session.add(market)
        await session.flush()
        settlement = Settlement(
            market_id=market.id,
            proof_status="generated",
            submission_status="none",
            merkle_root="0x" + "bb" * 32,
            winning_outcome_id=0,
        )
        session.add(settlement)
        await session.commit()

    redis = DummyRedis()
    summary = market_sync.SyncSummary()
    result = await settlement_module.run_settlement_jobs(summary, redis)
    assert result == 0


async def test_settlement_jobs_skips_when_market_address_missing(monkeypatch):
    """Market.market_address=None → settlement skipped."""
    signer = Account.create()
    monkeypatch.setattr(
        runtime_module.settings,
        "settlement_signer_private_key",
        SecretStr(signer._private_key.hex()),
        raising=False,
    )
    monkeypatch.setattr(runtime_module.settings, "rpc_url", "http://fake-rpc", raising=False)
    monkeypatch.setattr(runtime_module.settings, "settlement_rpc_url", None, raising=False)

    engine, sf = await create_async_in_memory_db()
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", sf, raising=False)

    mock_web3 = MagicMock()
    monkeypatch.setattr("app.settlement.get_async_web3", lambda _: mock_web3)
    monkeypatch.setattr("app.settlement._acquire_settlement_submission_lock", AsyncMock(return_value=("tok", "key")))
    monkeypatch.setattr("app.settlement._release_settlement_submission_lock", AsyncMock())

    async with sf() as session:
        market = Market(
            event_id="evt-no-addr",
            title="T",
            category="sports",
            oracle="polymarket",
            status="settled",
            resolution_status="final",
            market_address=None,
            resolved_at=datetime.now(UTC),
        )
        session.add(market)
        await session.flush()
        settlement = Settlement(
            market_id=market.id,
            proof_status="generated",
            submission_status="none",
            merkle_root="0x" + "bb" * 32,
            winning_outcome_id=0,
        )
        session.add(settlement)
        await session.commit()

    redis = DummyRedis()
    summary = market_sync.SyncSummary()
    result = await settlement_module.run_settlement_jobs(summary, redis)
    assert result == 0


# ---------------------------------------------------------------------------
# Tests: Failure modes
# ---------------------------------------------------------------------------


async def test_settlement_jobs_marks_failed_on_oracle_mismatch(monkeypatch):
    """Oracle address != signer address → submission_status = 'failed', error = 'oracle_mismatch'."""
    signer = Account.create()
    other_oracle = Account.create()
    monkeypatch.setattr(
        runtime_module.settings,
        "settlement_signer_private_key",
        SecretStr(signer._private_key.hex()),
        raising=False,
    )
    monkeypatch.setattr(runtime_module.settings, "rpc_url", "http://fake-rpc", raising=False)
    monkeypatch.setattr(runtime_module.settings, "settlement_rpc_url", None, raising=False)

    engine, sf = await create_async_in_memory_db()
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", sf, raising=False)

    mock_web3 = MagicMock()
    mock_contract = MagicMock()
    mock_contract.functions.oracle.return_value.call = AsyncMock(return_value=other_oracle.address)
    monkeypatch.setattr("app.settlement.get_async_web3", lambda _: mock_web3)
    monkeypatch.setattr("app.settlement._build_market_contract", lambda *_: mock_contract)
    monkeypatch.setattr("app.settlement._acquire_settlement_submission_lock", AsyncMock(return_value=("tok", "key")))
    monkeypatch.setattr("app.settlement._release_settlement_submission_lock", AsyncMock())

    async with sf() as session:
        market = Market(
            event_id="evt-oracle",
            title="T",
            category="sports",
            oracle="polymarket",
            status="settled",
            resolution_status="final",
            market_address="0x" + "A" * 40,
            resolved_at=datetime.now(UTC),
        )
        session.add(market)
        await session.flush()
        settlement = Settlement(
            market_id=market.id,
            proof_status="generated",
            submission_status="none",
            merkle_root="0x" + "bb" * 32,
            winning_outcome_id=0,
        )
        session.add(settlement)
        await session.commit()
        market_id = market.id

    redis = DummyRedis()
    summary = market_sync.SyncSummary()
    await settlement_module.run_settlement_jobs(summary, redis)

    async with sf() as session:
        s = (await session.execute(select(Settlement).where(Settlement.market_id == market_id))).scalar_one()
        assert s.submission_status == shared_models.SettlementSubmissionStatus.FAILED.value
        assert s.submission_error == "oracle_mismatch"


async def test_settlement_jobs_marks_failed_on_missing_batch_roots(monkeypatch):
    """No batch_roots and no merkle_root → submission_status='failed', error='missing_batch_roots'."""
    signer = Account.create()
    monkeypatch.setattr(
        runtime_module.settings,
        "settlement_signer_private_key",
        SecretStr(signer._private_key.hex()),
        raising=False,
    )
    monkeypatch.setattr(runtime_module.settings, "rpc_url", "http://fake-rpc", raising=False)
    monkeypatch.setattr(runtime_module.settings, "settlement_rpc_url", None, raising=False)

    engine, sf = await create_async_in_memory_db()
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", sf, raising=False)

    mock_web3 = MagicMock()
    mock_contract = MagicMock()
    mock_contract.functions.oracle.return_value.call = AsyncMock(return_value=signer.address)
    monkeypatch.setattr("app.settlement.get_async_web3", lambda _: mock_web3)
    monkeypatch.setattr("app.settlement._build_market_contract", lambda *_: mock_contract)
    monkeypatch.setattr("app.settlement._acquire_settlement_submission_lock", AsyncMock(return_value=("tok", "key")))
    monkeypatch.setattr("app.settlement._release_settlement_submission_lock", AsyncMock())
    monkeypatch.setattr("app.settlement._upsert_settlement_from_chain", AsyncMock(return_value=None))

    async with sf() as session:
        market = Market(
            event_id="evt-no-roots",
            title="T",
            category="sports",
            oracle="polymarket",
            status="settled",
            resolution_status="final",
            market_address="0x" + "A" * 40,
            resolved_at=datetime.now(UTC),
        )
        session.add(market)
        await session.flush()
        settlement = Settlement(
            market_id=market.id,
            proof_status="generated",
            submission_status="none",
            batch_roots=None,
            merkle_root=None,
            winning_outcome_id=0,
        )
        session.add(settlement)
        await session.commit()
        market_id = market.id

    redis = DummyRedis()
    summary = market_sync.SyncSummary()
    await settlement_module.run_settlement_jobs(summary, redis)

    async with sf() as session:
        s = (await session.execute(select(Settlement).where(Settlement.market_id == market_id))).scalar_one()
        assert s.submission_status == shared_models.SettlementSubmissionStatus.FAILED.value
        assert s.submission_error == "missing_batch_roots"


async def test_settlement_jobs_marks_failed_on_missing_proof_receipt(monkeypatch):
    """batch_roots set but no matching SettlementReceipt → 'missing_proof_receipt'."""
    signer = Account.create()
    monkeypatch.setattr(
        runtime_module.settings,
        "settlement_signer_private_key",
        SecretStr(signer._private_key.hex()),
        raising=False,
    )
    monkeypatch.setattr(runtime_module.settings, "rpc_url", "http://fake-rpc", raising=False)
    monkeypatch.setattr(runtime_module.settings, "settlement_rpc_url", None, raising=False)

    engine, sf = await create_async_in_memory_db()
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", sf, raising=False)

    mock_web3 = MagicMock()
    mock_contract = MagicMock()
    mock_contract.functions.oracle.return_value.call = AsyncMock(return_value=signer.address)
    monkeypatch.setattr("app.settlement.get_async_web3", lambda _: mock_web3)
    monkeypatch.setattr("app.settlement._build_market_contract", lambda *_: mock_contract)
    monkeypatch.setattr("app.settlement._acquire_settlement_submission_lock", AsyncMock(return_value=("tok", "key")))
    monkeypatch.setattr("app.settlement._release_settlement_submission_lock", AsyncMock())
    monkeypatch.setattr("app.settlement._upsert_settlement_from_chain", AsyncMock(return_value=None))

    async with sf() as session:
        market = Market(
            event_id="evt-no-proof",
            title="T",
            category="sports",
            oracle="polymarket",
            status="settled",
            resolution_status="final",
            market_address="0x" + "A" * 40,
            resolved_at=datetime.now(UTC),
        )
        session.add(market)
        await session.flush()
        settlement = Settlement(
            market_id=market.id,
            proof_status="generated",
            submission_status="none",
            batch_roots=json.dumps(["0x" + "aa" * 32]),
            batch_counts=json.dumps([1]),
            winning_outcome_id=0,
        )
        session.add(settlement)
        await session.commit()
        market_id = market.id

    redis = DummyRedis()
    summary = market_sync.SyncSummary()
    await settlement_module.run_settlement_jobs(summary, redis)

    async with sf() as session:
        s = (await session.execute(select(Settlement).where(Settlement.market_id == market_id))).scalar_one()
        assert s.submission_status == shared_models.SettlementSubmissionStatus.FAILED.value
        assert s.submission_error == "missing_proof_receipt"


# ---------------------------------------------------------------------------
# Tests: Happy path confirmation
# ---------------------------------------------------------------------------


async def test_settlement_jobs_enqueues_relayer_claims_after_confirmation(monkeypatch):
    """Confirmed settlement triggers relayer claim enqueue and returns count=1."""
    signer = Account.create()
    monkeypatch.setattr(
        runtime_module.settings,
        "settlement_signer_private_key",
        SecretStr(signer._private_key.hex()),
        raising=False,
    )
    monkeypatch.setattr(runtime_module.settings, "rpc_url", "http://fake-rpc", raising=False)
    monkeypatch.setattr(runtime_module.settings, "settlement_rpc_url", None, raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_enabled", True, raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_key", "relayer:queue", raising=False)

    engine, sf = await create_async_in_memory_db()
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", sf, raising=False)

    mock_web3 = MagicMock()
    mock_contract = MagicMock()
    mock_contract.functions.oracle.return_value.call = AsyncMock(return_value=signer.address)
    monkeypatch.setattr("app.settlement.get_async_web3", lambda _: mock_web3)
    monkeypatch.setattr("app.settlement._build_market_contract", lambda *_: mock_contract)
    monkeypatch.setattr("app.settlement._acquire_settlement_submission_lock", AsyncMock(return_value=("tok", "key")))
    monkeypatch.setattr("app.settlement._release_settlement_submission_lock", AsyncMock())
    monkeypatch.setattr("app.settlement._upsert_settlement_from_chain", AsyncMock(return_value=None))
    monkeypatch.setattr("app.settlement._maybe_post_result", AsyncMock())
    monkeypatch.setattr(
        "app.settlement._submit_verify_and_settle_batched", AsyncMock(return_value=("0x" + "ab" * 32, None))
    )
    monkeypatch.setattr("app.settlement._wait_for_submission_receipt", AsyncMock(return_value=42))

    enqueue_calls = []

    async def _mock_enqueue(redis, market, settlement):
        enqueue_calls.append(market.event_id)
        return 1

    monkeypatch.setattr("app.settlement._enqueue_relayer_claims", _mock_enqueue)

    batch_root = "0x" + "aa" * 32
    root_signal = str(int("aa" * 32, 16))

    async with sf() as session:
        market = Market(
            event_id="evt-confirm",
            title="T",
            category="sports",
            oracle="polymarket",
            status="settled",
            resolution_status="final",
            market_address="0x" + "A" * 40,
            resolved_at=datetime.now(UTC),
        )
        session.add(market)
        await session.flush()
        settlement = Settlement(
            market_id=market.id,
            proof_status="generated",
            submission_status="none",
            batch_roots=json.dumps([batch_root]),
            batch_counts=json.dumps([1]),
            winning_outcome_id=0,
        )
        session.add(settlement)
        await session.flush()
        receipt = shared_models.SettlementReceipt(
            market_id=market.id,
            request_id="req-confirm-test",
            batch_index=0,
            proof='{"pi_a":[],"pi_b":[],"pi_c":[]}',
            public_signals=[root_signal],
        )
        session.add(receipt)
        await session.commit()
        market_id = market.id

    redis = DummyRedis()
    summary = market_sync.SyncSummary()
    result = await settlement_module.run_settlement_jobs(summary, redis)

    assert result == 2  # 1 confirmed settlement + 1 enqueued relayer claim
    assert len(enqueue_calls) == 1

    async with sf() as session:
        s = (await session.execute(select(Settlement).where(Settlement.market_id == market_id))).scalar_one()
        assert s.submission_status == shared_models.SettlementSubmissionStatus.CONFIRMED.value
        assert s.settlement_block_number == 42


async def test_settlement_jobs_sets_processing_status_before_submission(monkeypatch):
    """submission_status is set to PROCESSING before _submit_verify_and_settle_batched is called."""
    signer = Account.create()
    monkeypatch.setattr(
        runtime_module.settings,
        "settlement_signer_private_key",
        SecretStr(signer._private_key.hex()),
        raising=False,
    )
    monkeypatch.setattr(runtime_module.settings, "rpc_url", "http://fake-rpc", raising=False)
    monkeypatch.setattr(runtime_module.settings, "settlement_rpc_url", None, raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_enabled", False, raising=False)

    engine, sf = await create_async_in_memory_db()
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", sf, raising=False)

    mock_web3 = MagicMock()
    mock_contract = MagicMock()
    mock_contract.functions.oracle.return_value.call = AsyncMock(return_value=signer.address)
    monkeypatch.setattr("app.settlement.get_async_web3", lambda _: mock_web3)
    monkeypatch.setattr("app.settlement._build_market_contract", lambda *_: mock_contract)
    monkeypatch.setattr("app.settlement._acquire_settlement_submission_lock", AsyncMock(return_value=("tok", "key")))
    monkeypatch.setattr("app.settlement._release_settlement_submission_lock", AsyncMock())
    monkeypatch.setattr("app.settlement._upsert_settlement_from_chain", AsyncMock(return_value=None))
    monkeypatch.setattr("app.settlement._maybe_post_result", AsyncMock())
    monkeypatch.setattr("app.settlement._wait_for_submission_receipt", AsyncMock(return_value=10))

    captured_statuses = []
    market_id_holder = [None]

    async def _mock_submit(*args, **kwargs):
        # At this point settlement should already be PROCESSING in DB
        async with sf() as check_session:
            from sqlalchemy import select

            s = (
                await check_session.execute(
                    select(shared_models.Settlement).where(shared_models.Settlement.market_id == market_id_holder[0])
                )
            ).scalar_one()
            captured_statuses.append(s.submission_status)
        return ("0x" + "ab" * 32, None)

    monkeypatch.setattr("app.settlement._submit_verify_and_settle_batched", _mock_submit)

    batch_root = "0x" + "aa" * 32
    root_signal = str(int("aa" * 32, 16))

    async with sf() as session:
        market = Market(
            event_id="evt-processing",
            title="T",
            category="sports",
            oracle="polymarket",
            status="settled",
            resolution_status="final",
            market_address="0x" + "A" * 40,
            resolved_at=datetime.now(UTC),
        )
        session.add(market)
        await session.flush()
        market_id_holder[0] = market.id
        settlement = shared_models.Settlement(
            market_id=market.id,
            proof_status="generated",
            submission_status="none",
            batch_roots=json.dumps([batch_root]),
            batch_counts=json.dumps([1]),
            winning_outcome_id=0,
        )
        session.add(settlement)
        await session.flush()
        receipt = shared_models.SettlementReceipt(
            market_id=market.id,
            request_id="req-proc-test",
            batch_index=0,
            proof='{"pi_a":[],"pi_b":[],"pi_c":[]}',
            public_signals=[root_signal],
        )
        session.add(receipt)
        await session.commit()

    redis = DummyRedis()
    from app import market_sync

    summary = market_sync.SyncSummary()
    await settlement_module.run_settlement_jobs(summary, redis)

    assert len(captured_statuses) == 1
    assert captured_statuses[0] == shared_models.SettlementSubmissionStatus.PROCESSING.value


async def test_settlement_jobs_sets_failed_on_receipt_timeout(monkeypatch):
    """_wait_for_submission_receipt raises → submission_status=failed, error contains 'receipt_wait_failed'."""
    signer = Account.create()
    monkeypatch.setattr(
        runtime_module.settings,
        "settlement_signer_private_key",
        SecretStr(signer._private_key.hex()),
        raising=False,
    )
    monkeypatch.setattr(runtime_module.settings, "rpc_url", "http://fake-rpc", raising=False)
    monkeypatch.setattr(runtime_module.settings, "settlement_rpc_url", None, raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_enabled", False, raising=False)

    engine, sf = await create_async_in_memory_db()
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", sf, raising=False)

    mock_web3 = MagicMock()
    mock_contract = MagicMock()
    mock_contract.functions.oracle.return_value.call = AsyncMock(return_value=signer.address)
    monkeypatch.setattr("app.settlement.get_async_web3", lambda _: mock_web3)
    monkeypatch.setattr("app.settlement._build_market_contract", lambda *_: mock_contract)
    monkeypatch.setattr("app.settlement._acquire_settlement_submission_lock", AsyncMock(return_value=("tok", "key")))
    monkeypatch.setattr("app.settlement._release_settlement_submission_lock", AsyncMock())
    monkeypatch.setattr("app.settlement._upsert_settlement_from_chain", AsyncMock(return_value=None))
    monkeypatch.setattr("app.settlement._maybe_post_result", AsyncMock())
    monkeypatch.setattr(
        "app.settlement._submit_verify_and_settle_batched", AsyncMock(return_value=("0x" + "ab" * 32, None))
    )
    # receipt wait times out
    monkeypatch.setattr("app.settlement._wait_for_submission_receipt", AsyncMock(side_effect=TimeoutError("timed out")))

    batch_root = "0x" + "aa" * 32
    root_signal = str(int("aa" * 32, 16))

    async with sf() as session:
        market = Market(
            event_id="evt-timeout",
            title="T",
            category="sports",
            oracle="polymarket",
            status="settled",
            resolution_status="final",
            market_address="0x" + "A" * 40,
            resolved_at=datetime.now(UTC),
        )
        session.add(market)
        await session.flush()
        settlement = shared_models.Settlement(
            market_id=market.id,
            proof_status="generated",
            submission_status="none",
            batch_roots=json.dumps([batch_root]),
            batch_counts=json.dumps([1]),
            winning_outcome_id=0,
        )
        session.add(settlement)
        await session.flush()
        receipt = shared_models.SettlementReceipt(
            market_id=market.id,
            request_id="req-timeout-test",
            batch_index=0,
            proof='{"pi_a":[],"pi_b":[],"pi_c":[]}',
            public_signals=[root_signal],
        )
        session.add(receipt)
        await session.commit()
        market_id = market.id

    redis = DummyRedis()
    from app import market_sync

    summary = market_sync.SyncSummary()
    await settlement_module.run_settlement_jobs(summary, redis)

    async with sf() as session:
        from sqlalchemy import select

        s = (
            await session.execute(
                select(shared_models.Settlement).where(shared_models.Settlement.market_id == market_id)
            )
        ).scalar_one()
        assert s.submission_status == shared_models.SettlementSubmissionStatus.FAILED.value
        assert "receipt_wait_failed" in (s.submission_error or "")


async def test_settlement_jobs_processes_queued_status_settlement(monkeypatch):
    """Settlement with submission_status='queued' is picked up and confirmed."""
    signer = Account.create()
    monkeypatch.setattr(
        runtime_module.settings,
        "settlement_signer_private_key",
        SecretStr(signer._private_key.hex()),
        raising=False,
    )
    monkeypatch.setattr(runtime_module.settings, "rpc_url", "http://fake-rpc", raising=False)
    monkeypatch.setattr(runtime_module.settings, "settlement_rpc_url", None, raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_enabled", False, raising=False)

    engine, sf = await create_async_in_memory_db()
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", sf, raising=False)

    mock_web3 = MagicMock()
    mock_contract = MagicMock()
    mock_contract.functions.oracle.return_value.call = AsyncMock(return_value=signer.address)
    monkeypatch.setattr("app.settlement.get_async_web3", lambda _: mock_web3)
    monkeypatch.setattr("app.settlement._build_market_contract", lambda *_: mock_contract)
    monkeypatch.setattr("app.settlement._acquire_settlement_submission_lock", AsyncMock(return_value=("tok", "key")))
    monkeypatch.setattr("app.settlement._release_settlement_submission_lock", AsyncMock())
    monkeypatch.setattr("app.settlement._upsert_settlement_from_chain", AsyncMock(return_value=None))
    monkeypatch.setattr("app.settlement._maybe_post_result", AsyncMock())
    monkeypatch.setattr(
        "app.settlement._submit_verify_and_settle_batched", AsyncMock(return_value=("0x" + "cd" * 32, None))
    )
    monkeypatch.setattr("app.settlement._wait_for_submission_receipt", AsyncMock(return_value=55))

    batch_root = "0x" + "aa" * 32
    root_signal = str(int("aa" * 32, 16))

    async with sf() as session:
        market = Market(
            event_id="evt-queued",
            title="T",
            category="sports",
            oracle="polymarket",
            status="settled",
            resolution_status="final",
            market_address="0x" + "A" * 40,
            resolved_at=datetime.now(UTC),
        )
        session.add(market)
        await session.flush()
        # Settlement starts as "queued" — should be picked up just like "none"
        settlement = shared_models.Settlement(
            market_id=market.id,
            proof_status="generated",
            submission_status=shared_models.SettlementSubmissionStatus.QUEUED.value,
            batch_roots=json.dumps([batch_root]),
            batch_counts=json.dumps([1]),
            winning_outcome_id=0,
        )
        session.add(settlement)
        await session.flush()
        receipt = shared_models.SettlementReceipt(
            market_id=market.id,
            request_id="req-queued-test",
            batch_index=0,
            proof='{"pi_a":[],"pi_b":[],"pi_c":[]}',
            public_signals=[root_signal],
        )
        session.add(receipt)
        await session.commit()
        market_id = market.id

    redis = DummyRedis()
    from app import market_sync

    summary = market_sync.SyncSummary()
    result = await settlement_module.run_settlement_jobs(summary, redis)
    assert result == 1

    async with sf() as session:
        from sqlalchemy import select

        s = (
            await session.execute(
                select(shared_models.Settlement).where(shared_models.Settlement.market_id == market_id)
            )
        ).scalar_one()
        assert s.submission_status == shared_models.SettlementSubmissionStatus.CONFIRMED.value


async def test_settlement_jobs_exponential_backoff_skips_recent_failure(monkeypatch):
    """Pre-populated failure state (next_ts in future) causes settlement to be skipped."""
    import time

    signer = Account.create()
    monkeypatch.setattr(
        runtime_module.settings,
        "settlement_signer_private_key",
        SecretStr(signer._private_key.hex()),
        raising=False,
    )
    monkeypatch.setattr(runtime_module.settings, "rpc_url", "http://fake-rpc", raising=False)
    monkeypatch.setattr(runtime_module.settings, "settlement_rpc_url", None, raising=False)

    engine, sf = await create_async_in_memory_db()
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", sf, raising=False)

    mock_web3 = MagicMock()
    monkeypatch.setattr("app.settlement.get_async_web3", lambda _: mock_web3)
    monkeypatch.setattr("app.settlement._acquire_settlement_submission_lock", AsyncMock(return_value=("tok", "key")))
    monkeypatch.setattr("app.settlement._release_settlement_submission_lock", AsyncMock())

    async with sf() as session:
        market = Market(
            event_id="evt-backoff",
            title="T",
            category="sports",
            oracle="polymarket",
            status="settled",
            resolution_status="final",
            market_address="0x" + "A" * 40,
            resolved_at=datetime.now(UTC),
        )
        session.add(market)
        await session.flush()
        settlement = shared_models.Settlement(
            market_id=market.id,
            proof_status="generated",
            submission_status="none",
            batch_roots=json.dumps(["0x" + "aa" * 32]),
            batch_counts=json.dumps([1]),
            winning_outcome_id=0,
        )
        session.add(settlement)
        await session.commit()
        market_id = market.id

    # Pre-populate Redis with failure state: next retry far in the future
    redis = DummyRedis()
    retry_prefix = "reveal_market_worker:settlement_submit:fail"
    retry_key = f"{retry_prefix}:{market_id}"
    far_future = str(time.time() + 86400)  # 24 hours from now
    await redis.hset(
        retry_key,
        mapping={
            "attempts": "3",
            "next_ts": far_future,
            "first_ts": str(time.time()),
            "last_error": "oracle_mismatch",
        },
    )

    from app import market_sync

    summary = market_sync.SyncSummary()
    result = await settlement_module.run_settlement_jobs(summary, redis)
    # should_attempt returns False → settlement skipped → returns 0
    assert result == 0


async def test_settlement_jobs_winning_outcome_resolved_from_db(monkeypatch):
    """settlement.winning_outcome_id=None but _resolve_winning_outcome returns 1 → settlement proceeds."""
    signer = Account.create()
    monkeypatch.setattr(
        runtime_module.settings,
        "settlement_signer_private_key",
        SecretStr(signer._private_key.hex()),
        raising=False,
    )
    monkeypatch.setattr(runtime_module.settings, "rpc_url", "http://fake-rpc", raising=False)
    monkeypatch.setattr(runtime_module.settings, "settlement_rpc_url", None, raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_enabled", False, raising=False)

    engine, sf = await create_async_in_memory_db()
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", sf, raising=False)

    mock_web3 = MagicMock()
    mock_contract = MagicMock()
    mock_contract.functions.oracle.return_value.call = AsyncMock(return_value=signer.address)
    monkeypatch.setattr("app.settlement.get_async_web3", lambda _: mock_web3)
    monkeypatch.setattr("app.settlement._build_market_contract", lambda *_: mock_contract)
    monkeypatch.setattr("app.settlement._acquire_settlement_submission_lock", AsyncMock(return_value=("tok", "key")))
    monkeypatch.setattr("app.settlement._release_settlement_submission_lock", AsyncMock())
    monkeypatch.setattr("app.settlement._upsert_settlement_from_chain", AsyncMock(return_value=None))
    monkeypatch.setattr("app.settlement._maybe_post_result", AsyncMock())
    monkeypatch.setattr(
        "app.settlement._submit_verify_and_settle_batched", AsyncMock(return_value=("0x" + "ef" * 32, None))
    )
    monkeypatch.setattr("app.settlement._wait_for_submission_receipt", AsyncMock(return_value=77))
    # Simulate DB resolution returning winning_outcome_id=1
    monkeypatch.setattr("app.settlement._resolve_winning_outcome", AsyncMock(return_value=1))

    batch_root = "0x" + "aa" * 32
    root_signal = str(int("aa" * 32, 16))

    async with sf() as session:
        market = Market(
            event_id="evt-resolve",
            title="T",
            category="sports",
            oracle="polymarket",
            status="settled",
            resolution_status="final",
            market_address="0x" + "A" * 40,
            resolved_at=datetime.now(UTC),
        )
        session.add(market)
        await session.flush()
        settlement = shared_models.Settlement(
            market_id=market.id,
            proof_status="generated",
            submission_status="none",
            batch_roots=json.dumps([batch_root]),
            batch_counts=json.dumps([1]),
            winning_outcome_id=None,  # unknown — should be resolved from DB
        )
        session.add(settlement)
        await session.flush()
        receipt = shared_models.SettlementReceipt(
            market_id=market.id,
            request_id="req-resolve-test",
            batch_index=0,
            proof='{"pi_a":[],"pi_b":[],"pi_c":[]}',
            public_signals=[root_signal],
        )
        session.add(receipt)
        await session.commit()
        market_id = market.id

    redis = DummyRedis()
    from app import market_sync

    summary = market_sync.SyncSummary()
    result = await settlement_module.run_settlement_jobs(summary, redis)
    assert result == 1

    async with sf() as session:
        from sqlalchemy import select

        s = (
            await session.execute(
                select(shared_models.Settlement).where(shared_models.Settlement.market_id == market_id)
            )
        ).scalar_one()
        assert s.winning_outcome_id == 1
        assert s.submission_status == shared_models.SettlementSubmissionStatus.CONFIRMED.value


async def test_settlement_jobs_previous_tx_fails_receipt_then_resubmits(monkeypatch):
    """Existing settlement_tx_hash fails receipt check → cleared and resubmitted → confirmed."""
    signer = Account.create()
    monkeypatch.setattr(
        runtime_module.settings,
        "settlement_signer_private_key",
        SecretStr(signer._private_key.hex()),
        raising=False,
    )
    monkeypatch.setattr(runtime_module.settings, "rpc_url", "http://fake-rpc", raising=False)
    monkeypatch.setattr(runtime_module.settings, "settlement_rpc_url", None, raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_enabled", False, raising=False)

    engine, sf = await create_async_in_memory_db()
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", sf, raising=False)

    mock_web3 = MagicMock()
    mock_contract = MagicMock()
    mock_contract.functions.oracle.return_value.call = AsyncMock(return_value=signer.address)
    monkeypatch.setattr("app.settlement.get_async_web3", lambda _: mock_web3)
    monkeypatch.setattr("app.settlement._build_market_contract", lambda *_: mock_contract)
    monkeypatch.setattr("app.settlement._acquire_settlement_submission_lock", AsyncMock(return_value=("tok", "key")))
    monkeypatch.setattr("app.settlement._release_settlement_submission_lock", AsyncMock())
    monkeypatch.setattr("app.settlement._upsert_settlement_from_chain", AsyncMock(return_value=None))
    monkeypatch.setattr("app.settlement._maybe_post_result", AsyncMock())

    new_tx = "0x" + "cd" * 32
    submit_mock = AsyncMock(return_value=(new_tx, None))
    monkeypatch.setattr("app.settlement._submit_verify_and_settle_batched", submit_mock)

    # First call (old tx) raises; second call (new tx) succeeds
    wait_mock = AsyncMock(side_effect=[Exception("not mined"), 88])
    monkeypatch.setattr("app.settlement._wait_for_submission_receipt", wait_mock)

    batch_root = "0x" + "aa" * 32
    root_signal = str(int("aa" * 32, 16))
    old_tx = "0x" + "ab" * 32  # pre-existing tx hash

    async with sf() as session:
        market = Market(
            event_id="evt-retry-tx",
            title="T",
            category="sports",
            oracle="polymarket",
            status="settled",
            resolution_status="final",
            market_address="0x" + "A" * 40,
            resolved_at=datetime.now(UTC),
        )
        session.add(market)
        await session.flush()
        settlement = shared_models.Settlement(
            market_id=market.id,
            proof_status="generated",
            submission_status=shared_models.SettlementSubmissionStatus.FAILED.value,
            settlement_tx_hash=old_tx,  # pre-existing tx to re-check
            batch_roots=json.dumps([batch_root]),
            batch_counts=json.dumps([1]),
            winning_outcome_id=0,
        )
        session.add(settlement)
        await session.flush()
        receipt = shared_models.SettlementReceipt(
            market_id=market.id,
            request_id="req-retry-tx-test",
            batch_index=0,
            proof='{"pi_a":[],"pi_b":[],"pi_c":[]}',
            public_signals=[root_signal],
        )
        session.add(receipt)
        await session.commit()
        market_id = market.id

    redis = DummyRedis()
    from app import market_sync

    summary = market_sync.SyncSummary()
    result = await settlement_module.run_settlement_jobs(summary, redis)
    assert result == 1

    async with sf() as session:
        from sqlalchemy import select

        s = (
            await session.execute(
                select(shared_models.Settlement).where(shared_models.Settlement.market_id == market_id)
            )
        ).scalar_one()
        assert s.submission_status == shared_models.SettlementSubmissionStatus.CONFIRMED.value
        assert s.settlement_block_number == 88
    # _submit was called exactly once (after old tx failed receipt check)
    assert submit_mock.call_count == 1
    assert wait_mock.call_count == 2


async def test_settlement_jobs_increments_submitted_count(monkeypatch):
    """Two settled markets both confirmed → returns 2."""
    signer = Account.create()
    monkeypatch.setattr(
        runtime_module.settings,
        "settlement_signer_private_key",
        SecretStr(signer._private_key.hex()),
        raising=False,
    )
    monkeypatch.setattr(runtime_module.settings, "rpc_url", "http://fake-rpc", raising=False)
    monkeypatch.setattr(runtime_module.settings, "settlement_rpc_url", None, raising=False)
    monkeypatch.setattr(runtime_module.settings, "relayer_queue_enabled", False, raising=False)

    engine, sf = await create_async_in_memory_db()
    monkeypatch.setattr(db, "engine", engine, raising=False)
    monkeypatch.setattr(db, "SessionLocal", sf, raising=False)

    mock_web3 = MagicMock()
    mock_contract = MagicMock()
    mock_contract.functions.oracle.return_value.call = AsyncMock(return_value=signer.address)
    monkeypatch.setattr("app.settlement.get_async_web3", lambda _: mock_web3)
    monkeypatch.setattr("app.settlement._build_market_contract", lambda *_: mock_contract)
    monkeypatch.setattr("app.settlement._acquire_settlement_submission_lock", AsyncMock(return_value=("tok", "key")))
    monkeypatch.setattr("app.settlement._release_settlement_submission_lock", AsyncMock())
    monkeypatch.setattr("app.settlement._upsert_settlement_from_chain", AsyncMock(return_value=None))
    monkeypatch.setattr("app.settlement._maybe_post_result", AsyncMock())
    monkeypatch.setattr(
        "app.settlement._submit_verify_and_settle_batched", AsyncMock(return_value=("0x" + "ab" * 32, None))
    )
    monkeypatch.setattr("app.settlement._wait_for_submission_receipt", AsyncMock(return_value=99))

    batch_root = "0x" + "aa" * 32
    root_signal = str(int("aa" * 32, 16))

    async with sf() as session:
        for i in range(2):
            market = Market(
                event_id=f"evt-count-{i}",
                title=f"T{i}",
                category="sports",
                oracle="polymarket",
                status="settled",
                resolution_status="final",
                market_address=f"0x{'A' * 38}{i:02d}",
                resolved_at=datetime.now(UTC),
            )
            session.add(market)
            await session.flush()
            settlement = Settlement(
                market_id=market.id,
                proof_status="generated",
                submission_status="none",
                batch_roots=json.dumps([batch_root]),
                batch_counts=json.dumps([1]),
                winning_outcome_id=0,
            )
            session.add(settlement)
            await session.flush()
            receipt = shared_models.SettlementReceipt(
                market_id=market.id,
                request_id=f"req-count-{i}",
                batch_index=0,
                proof='{"pi_a":[],"pi_b":[],"pi_c":[]}',
                public_signals=[root_signal],
            )
            session.add(receipt)
        await session.commit()

    redis = DummyRedis()
    summary = market_sync.SyncSummary()
    result = await settlement_module.run_settlement_jobs(summary, redis)
    assert result == 2
