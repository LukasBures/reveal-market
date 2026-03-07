"""Unit tests for claim helper functions in app.routes.trade."""

from __future__ import annotations

# ruff: noqa: S101
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import app.runtime as runtime
import pytest
from app.routes.trade import (
    _claim_rate_and_lock,
    _enqueue_relayer_job,
    _fetch_claimed_tickets,
    _release_claim_lock,
    _sync_claimed_commitments,
    call_relayer,
)
from fastapi import HTTPException
from shared.models import Base, Commitment, Market, Settlement
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# Test-local cache helpers
# ---------------------------------------------------------------------------


class InMemoryCacheWithQueue:
    """Extended in-memory cache supporting incr, expire, and lpush for helper tests."""

    def __init__(self):
        self.store: dict[str, Any] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None, nx: bool | None = None):
        if nx:
            if key in self.store:
                return False
        self.store[key] = value
        return True

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.store.pop(key, None)

    async def incr(self, key: str) -> int:
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    async def expire(self, key: str, seconds: int) -> None:
        pass  # no TTL tracking needed in tests

    async def lpush(self, key: str, *values: str) -> int:
        lst = self.store.setdefault(key, [])
        for v in values:
            lst.insert(0, v)
        return len(lst)


class _AsyncClientStub:
    """Minimal httpx.AsyncClient stub for relayer HTTP mocking."""

    def __init__(self, payload: dict, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    async def post(self, *_args, **_kwargs):
        return self

    def json(self):
        return self.payload


async def _make_async_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(bind=engine, future=True, expire_on_commit=False)
    return engine, sf


# ---------------------------------------------------------------------------
# Group A: _fetch_claimed_tickets
# ---------------------------------------------------------------------------


async def test_fetch_claimed_tickets_empty_ticket_list_returns_empty_dict(monkeypatch):
    """ticket_ids=[] → returns {} without hitting RPC."""
    monkeypatch.setattr(runtime.settings, "rpc_url", "http://rpc", raising=False)
    result = await _fetch_claimed_tickets("0x" + "1" * 40, [])
    assert result == {}


async def test_fetch_claimed_tickets_no_rpc_url_returns_empty_dict(monkeypatch):
    """rpc_url="" → returns {} immediately."""
    monkeypatch.setattr(runtime.settings, "rpc_url", "", raising=False)
    result = await _fetch_claimed_tickets("0x" + "1" * 40, [0, 1])
    assert result == {}


async def test_fetch_claimed_tickets_returns_none_when_contract_raises(monkeypatch):
    """Web3 contract call raises ConnectionError → returns None (graceful degradation)."""
    monkeypatch.setattr(runtime.settings, "rpc_url", "http://rpc", raising=False)

    def _broken_web3(_url):
        raise ConnectionError("connection refused")

    monkeypatch.setattr("app.routes.trade.get_async_web3", _broken_web3)
    result = await _fetch_claimed_tickets("0x" + "1" * 40, [0])
    assert result is None


async def test_fetch_claimed_tickets_mocked_rpc_returns_claimed_status(monkeypatch):
    """Mock Web3 contract returns claimed=True for ticket 0, False for ticket 1."""
    monkeypatch.setattr(runtime.settings, "rpc_url", "http://rpc", raising=False)

    mock_contract = MagicMock()
    # MagicMock returns same return_value regardless of args; use side_effect to vary per call
    mock_contract.functions.claimedTickets.return_value.call = AsyncMock(side_effect=[True, False])

    mock_web3 = MagicMock()
    mock_web3.eth.contract.return_value = mock_contract

    monkeypatch.setattr("app.routes.trade.get_async_web3", lambda _url: mock_web3)
    result = await _fetch_claimed_tickets("0x" + "1" * 40, [0, 1])
    assert result == {0: True, 1: False}


# ---------------------------------------------------------------------------
# Group B: _sync_claimed_commitments
# ---------------------------------------------------------------------------


async def test_sync_claimed_commitments_skips_when_no_rpc_url(monkeypatch):
    """rpc_url="" → returns immediately without any DB writes."""
    monkeypatch.setattr(runtime.settings, "rpc_url", "", raising=False)
    _, sf = await _make_async_db()
    async with sf() as session:
        # No DB writes should happen — empty call is fine
        await _sync_claimed_commitments(session, [])


async def test_sync_claimed_commitments_marks_claimed_at_for_onchain_claimed(monkeypatch):
    """When RPC returns {ticket_id: True}, commitment.claimed_at is set."""
    monkeypatch.setattr(runtime.settings, "rpc_url", "http://rpc", raising=False)

    _, sf = await _make_async_db()
    market_address = "0x" + "A" * 40

    async with sf() as session:
        market = Market(id=1, event_id="m1", title="T", oracle="0x" + "1" * 40, market_address=market_address)
        settlement = Settlement(id=1, market_id=1, merkle_root="0x" + "bb" * 32, winning_outcome_id=0)
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

    # Mock _fetch_claimed_tickets to return {0: True}
    async def _mock_fetch(_market_address, _ticket_ids):
        return {0: True}

    monkeypatch.setattr("app.routes.trade._fetch_claimed_tickets", _mock_fetch)

    async with sf() as session:
        from sqlalchemy import select

        market = (await session.execute(select(Market).where(Market.id == 1))).scalar_one()
        settlement = (await session.execute(select(Settlement).where(Settlement.id == 1))).scalar_one()
        commitment = (await session.execute(select(Commitment).where(Commitment.id == 1))).scalar_one()
        await _sync_claimed_commitments(session, [(commitment, market, settlement)])
        await session.commit()

    async with sf() as session:
        from sqlalchemy import select

        c = (await session.execute(select(Commitment).where(Commitment.id == 1))).scalar_one()
        assert c.claimed_at is not None


async def test_sync_claimed_commitments_skips_already_claimed(monkeypatch):
    """Commitment already has claimed_at → not re-processed."""
    from datetime import UTC, datetime

    monkeypatch.setattr(runtime.settings, "rpc_url", "http://rpc", raising=False)

    _, sf = await _make_async_db()
    already_claimed_at = datetime.now(tz=UTC)

    async with sf() as session:
        market = Market(id=1, event_id="m1", title="T", oracle="0x" + "1" * 40, market_address="0x" + "A" * 40)
        settlement = Settlement(id=1, market_id=1, merkle_root="0x" + "bb" * 32, winning_outcome_id=0)
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
            claimed_at=already_claimed_at,
        )
        session.add_all([market, settlement, commitment])
        await session.commit()

    fetch_calls = []

    async def _mock_fetch(_market_address, _ticket_ids):
        fetch_calls.append(_ticket_ids)
        return {}

    monkeypatch.setattr("app.routes.trade._fetch_claimed_tickets", _mock_fetch)

    async with sf() as session:
        from sqlalchemy import select

        market = (await session.execute(select(Market))).scalar_one()
        settlement = (await session.execute(select(Settlement))).scalar_one()
        commitment = (await session.execute(select(Commitment))).scalar_one()
        await _sync_claimed_commitments(session, [(commitment, market, settlement)])

    # Should be skipped because claimed_at is already set → no RPC call
    assert fetch_calls == []


async def test_sync_claimed_commitments_skips_losing_outcomes(monkeypatch):
    """Commitment outcome_id != winning_outcome_id → skipped entirely."""
    monkeypatch.setattr(runtime.settings, "rpc_url", "http://rpc", raising=False)

    _, sf = await _make_async_db()

    async with sf() as session:
        market = Market(id=1, event_id="m1", title="T", oracle="0x" + "1" * 40, market_address="0x" + "A" * 40)
        settlement = Settlement(id=1, market_id=1, merkle_root="0x" + "bb" * 32, winning_outcome_id=1)
        commitment = Commitment(
            id=1,
            market_id=1,
            user_address="0x" + "2" * 40,
            outcome_id=0,  # losing outcome
            amount_wei=10,
            payout_wei=10,
            salt="0x0",
            ticket_hash="0x" + "cc" * 32,
            leaf="0x" + "cc" * 32,
            leaf_index=0,
        )
        session.add_all([market, settlement, commitment])
        await session.commit()

    fetch_calls = []

    async def _mock_fetch(_market_address, _ticket_ids):
        fetch_calls.append(_ticket_ids)
        return {}

    monkeypatch.setattr("app.routes.trade._fetch_claimed_tickets", _mock_fetch)

    async with sf() as session:
        from sqlalchemy import select

        market = (await session.execute(select(Market))).scalar_one()
        settlement = (await session.execute(select(Settlement))).scalar_one()
        commitment = (await session.execute(select(Commitment))).scalar_one()
        await _sync_claimed_commitments(session, [(commitment, market, settlement)])

    assert fetch_calls == []


async def test_sync_claimed_commitments_handles_none_from_fetch(monkeypatch):
    """When _fetch_claimed_tickets returns None → no crash, no updates."""
    monkeypatch.setattr(runtime.settings, "rpc_url", "http://rpc", raising=False)

    _, sf = await _make_async_db()

    async with sf() as session:
        market = Market(id=1, event_id="m1", title="T", oracle="0x" + "1" * 40, market_address="0x" + "A" * 40)
        settlement = Settlement(id=1, market_id=1, merkle_root="0x" + "bb" * 32, winning_outcome_id=0)
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

    async def _mock_fetch_none(_market_address, _ticket_ids):
        return None  # simulates RPC failure

    monkeypatch.setattr("app.routes.trade._fetch_claimed_tickets", _mock_fetch_none)

    async with sf() as session:
        from sqlalchemy import select

        market = (await session.execute(select(Market))).scalar_one()
        settlement = (await session.execute(select(Settlement))).scalar_one()
        commitment = (await session.execute(select(Commitment))).scalar_one()
        # Must not raise
        await _sync_claimed_commitments(session, [(commitment, market, settlement)])


# ---------------------------------------------------------------------------
# Group C: _claim_rate_and_lock
# ---------------------------------------------------------------------------


async def test_claim_rate_and_lock_acquires_lock_on_first_call(monkeypatch):
    """First call with fresh cache → returns a non-None lock_key."""
    cache = InMemoryCacheWithQueue()
    monkeypatch.setattr(runtime, "cache_client", cache, raising=False)
    monkeypatch.setattr("app.routes.trade.get_cache_client", AsyncMock(return_value=cache))

    lock_key = await _claim_rate_and_lock("mkt-1", "0x" + "A" * 40, 0)
    assert lock_key is not None
    assert "claim:lock:" in lock_key


async def test_claim_rate_and_lock_raises_429_after_limit_exceeded(monkeypatch):
    """Pre-fill rate counter above limit → 429 claim_rate_limited."""
    cache = InMemoryCacheWithQueue()
    monkeypatch.setattr(runtime, "cache_client", cache, raising=False)
    monkeypatch.setattr("app.routes.trade.get_cache_client", AsyncMock(return_value=cache))
    monkeypatch.setattr(runtime.settings, "claim_request_rate_limit_per_minute", 5, raising=False)

    wallet = "0x" + "B" * 40
    # Pre-set counter above limit
    cache.store[f"claim:rate:{wallet.lower()}"] = 6

    with pytest.raises(HTTPException) as exc_info:
        await _claim_rate_and_lock("mkt-2", wallet, 0)
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "claim_rate_limited"


async def test_claim_rate_and_lock_raises_409_when_lock_already_held(monkeypatch):
    """Pre-set lock key in cache → 409 claim_in_progress."""
    cache = InMemoryCacheWithQueue()
    monkeypatch.setattr(runtime, "cache_client", cache, raising=False)
    monkeypatch.setattr("app.routes.trade.get_cache_client", AsyncMock(return_value=cache))

    wallet = "0x" + "C" * 40
    market_id = "mkt-3"
    ticket_id = 7
    lock_key = f"claim:lock:{market_id}:{wallet.lower()}:{ticket_id}"
    cache.store[lock_key] = "1"  # lock already held

    with pytest.raises(HTTPException) as exc_info:
        await _claim_rate_and_lock(market_id, wallet, ticket_id)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "claim_in_progress"


async def test_claim_rate_and_lock_returns_none_when_cache_is_none(monkeypatch):
    """cache=None → returns None without raising."""
    monkeypatch.setattr("app.routes.trade.get_cache_client", AsyncMock(return_value=None))

    result = await _claim_rate_and_lock("mkt-4", "0x" + "D" * 40, 0)
    assert result is None


# ---------------------------------------------------------------------------
# Group D: _release_claim_lock
# ---------------------------------------------------------------------------


async def test_release_claim_lock_deletes_key_from_cache(monkeypatch):
    """Pre-set lock_key in cache → call release → key gone."""
    cache = InMemoryCacheWithQueue()
    monkeypatch.setattr(runtime, "cache_client", cache, raising=False)
    monkeypatch.setattr("app.routes.trade.get_cache_client", AsyncMock(return_value=cache))

    lock_key = "claim:lock:mkt-1:0xwallet:0"
    cache.store[lock_key] = "1"

    await _release_claim_lock(lock_key)
    assert lock_key not in cache.store


async def test_release_claim_lock_noop_when_key_is_none(monkeypatch):
    """lock_key=None → no error, no cache mutation."""
    cache = InMemoryCacheWithQueue()
    monkeypatch.setattr("app.routes.trade.get_cache_client", AsyncMock(return_value=cache))
    await _release_claim_lock(None)  # Should not raise


async def test_release_claim_lock_noop_when_cache_is_none(monkeypatch):
    """cache=None → no error."""
    monkeypatch.setattr("app.routes.trade.get_cache_client", AsyncMock(return_value=None))
    await _release_claim_lock("claim:lock:mkt-1:0xwallet:0")  # Should not raise


# ---------------------------------------------------------------------------
# Group E: call_relayer
# ---------------------------------------------------------------------------


async def test_call_relayer_returns_json_on_200(monkeypatch):
    """Relayer returns 200 → returns parsed JSON dict."""
    monkeypatch.setattr(runtime.settings, "relayer_base_url", "http://relayer", raising=False)

    async def _http(*_a, **_kw):
        return _AsyncClientStub({"result": "ok"}, 200)

    monkeypatch.setattr("app.routes.trade.get_http_client", _http)
    result = await call_relayer("http://relayer/commit", {"data": 1})
    assert result == {"result": "ok"}


async def test_call_relayer_returns_json_on_202(monkeypatch):
    """Relayer returns 202 (queued) → returns parsed JSON dict."""
    monkeypatch.setattr(runtime.settings, "relayer_base_url", "http://relayer", raising=False)

    async def _http(*_a, **_kw):
        return _AsyncClientStub({"job_id": "abc"}, 202)

    monkeypatch.setattr("app.routes.trade.get_http_client", _http)
    result = await call_relayer("http://relayer/commit", {"data": 1})
    assert result == {"job_id": "abc"}


async def test_call_relayer_raises_502_on_non_retryable_error(monkeypatch):
    """Relayer returns 400 → raises HTTPException 502 with detail containing status code."""
    monkeypatch.setattr(runtime.settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(runtime.settings, "relayer_retry_attempts", 0, raising=False)

    async def _http(*_a, **_kw):
        return _AsyncClientStub({"detail": "bad_request"}, 400)

    monkeypatch.setattr("app.routes.trade.get_http_client", _http)

    with pytest.raises(HTTPException) as exc_info:
        await call_relayer("http://relayer/commit", {})
    assert exc_info.value.status_code == 502
    assert "400" in exc_info.value.detail


async def test_call_relayer_raises_503_when_relayer_not_configured(monkeypatch):
    """relayer_base_url="" → raises 503 relayer_unconfigured."""
    monkeypatch.setattr(runtime.settings, "relayer_base_url", "", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        await call_relayer("http://relayer/commit", {})
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "relayer_unconfigured"


# ---------------------------------------------------------------------------
# Group F: _enqueue_relayer_job
# ---------------------------------------------------------------------------


async def test_enqueue_relayer_job_pushes_job_to_cache_queue(monkeypatch):
    """queue_enabled + cache → job pushed to relayer_queue_key list."""
    cache = InMemoryCacheWithQueue()
    monkeypatch.setattr(runtime.settings, "relayer_queue_enabled", True, raising=False)
    monkeypatch.setattr(runtime.settings, "relayer_queue_key", "relayer:queue", raising=False)
    monkeypatch.setattr("app.routes.trade.get_cache_client", AsyncMock(return_value=cache))

    job_id = await _enqueue_relayer_job("commit", "http://relayer/commit", {"ticket": 1})
    assert job_id is not None

    queue = cache.store.get("relayer:queue", [])
    assert len(queue) == 1
    job = json.loads(queue[0])
    assert job["kind"] == "commit"
    assert job["endpoint"] == "http://relayer/commit"
    assert job["attempts"] == 0
    assert "job_id" in job


async def test_enqueue_relayer_job_raises_502_when_queue_disabled(monkeypatch):
    """relayer_queue_enabled=False → raises 502 relayer_unavailable."""
    monkeypatch.setattr(runtime.settings, "relayer_queue_enabled", False, raising=False)

    with pytest.raises(HTTPException) as exc_info:
        await _enqueue_relayer_job("commit", "http://relayer/commit", {})
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "relayer_unavailable"


async def test_enqueue_relayer_job_raises_503_when_cache_unavailable(monkeypatch):
    """cache=None → raises 503 relayer_queue_unavailable."""
    monkeypatch.setattr(runtime.settings, "relayer_queue_enabled", True, raising=False)
    monkeypatch.setattr("app.routes.trade.get_cache_client", AsyncMock(return_value=None))

    with pytest.raises(HTTPException) as exc_info:
        await _enqueue_relayer_job("commit", "http://relayer/commit", {})
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "relayer_queue_unavailable"
