from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.config import Settings
from app.fx import FxQuote
from app.service import HedgerService
from app.types import CommitEvent, HedgeAction, HedgeInstruction, OutcomeSide


class StubWallet:
    def __init__(self, balance: Decimal = Decimal("100")):
        self.balance = balance
        self.approved = False

    def has_sufficient_balance(self, required_usdc: Decimal):
        return self.balance >= required_usdc, self.balance

    def ensure_allowance(self):
        self.approved = True
        return "0xapprove"


class StubClob:
    def __init__(self, response: dict):
        self.response = response
        self.calls: list[dict] = []

    def place_market_order(self, *, token_id: str, amount_usd: Decimal, action: HedgeAction):
        self.calls.append({"token_id": token_id, "amount_usd": amount_usd, "action": action})
        return self.response


class OneShotLock:
    def __init__(self, key: str):
        self.key = key
        self._entered = False
        self.enter_count = 0

    async def __aenter__(self):
        if self._entered:
            raise RuntimeError(f"lock context reused for {self.key}")
        self._entered = True
        self.enter_count += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False


class RecordingLockManager:
    def __init__(self):
        self.contexts: list[OneShotLock] = []
        self.idempotency_claims: list[str] = []

    async def claim_idempotency(self, key: str) -> bool:
        self.idempotency_claims.append(key)
        return True

    def lock(self, key: str) -> OneShotLock:
        lock = OneShotLock(key)
        self.contexts.append(lock)
        return lock


@pytest.mark.asyncio
async def test_execute_hedge_rejects_when_token_missing():
    settings = Settings(
        hedger_private_key="0x" + "11" * 32,
        polymarket_api_key="key",
        polymarket_api_secret="secret",  # noqa: S106 - test fixture
        polymarket_api_passphrase="passphrase",  # noqa: S106 - test fixture
    )
    service = HedgerService(settings)
    service.lock_manager = None
    service.wallet = StubWallet()
    service.clob = StubClob({"filled_size": "1.0"})

    instr = HedgeInstruction(
        market_id="m1",
        hedge_outcome=OutcomeSide.YES,
        action=HedgeAction.BUY,
        size_usd=Decimal("1"),
        slippage_bps=30,
        reason="test",
        target_coverage=0.9,
        clob_token_id=None,
    )

    result = await service._execute_hedge(instr)
    assert result["status"] == "rejected"
    assert result["reason"] == "clob_token_missing"


@pytest.mark.asyncio
async def test_execute_hedge_rejects_when_fill_below_threshold():
    settings = Settings(
        hedger_private_key="0x" + "11" * 32,
        polymarket_api_key="key",
        polymarket_api_secret="secret",  # noqa: S106 - test fixture
        polymarket_api_passphrase="passphrase",  # noqa: S106 - test fixture
        min_fill_percent=90,
    )
    service = HedgerService(settings)
    service.lock_manager = None
    service.wallet = StubWallet()
    service.clob = StubClob({"filled_size": "0.4"})
    calls: dict[str, Decimal] = {}

    async def _register_fill(market_id: str, size_usd: Decimal, is_unwind: bool = False):
        _ = market_id
        _ = is_unwind
        calls["filled"] = size_usd

    async def _record_instruction(*_args, **_kwargs):
        return None

    async def _record_audit(*_args, **_kwargs):
        return None

    service.exposure_ledger.register_fill = _register_fill  # type: ignore[assignment]
    service.repository.record_hedge_instruction = _record_instruction  # type: ignore[assignment]
    service.repository.record_audit_log = _record_audit  # type: ignore[assignment]

    instr = HedgeInstruction(
        market_id="m1",
        hedge_outcome=OutcomeSide.YES,
        action=HedgeAction.BUY,
        size_usd=Decimal("1"),
        slippage_bps=30,
        reason="test",
        target_coverage=0.9,
        clob_token_id="token-yes",  # noqa: S106 - test fixture, not a secret
    )

    result = await service._execute_hedge(instr)
    assert result["status"] == "rejected"
    assert result["reason"] == "fill_below_threshold"
    assert result["reconciled_fill"] is True
    assert calls["filled"] == Decimal("0.4")


@pytest.mark.asyncio
async def test_ingest_commit_rejects_when_insufficient_usdc():
    settings = Settings(
        hedger_private_key="0x" + "11" * 32,
        polymarket_api_key="key",
        polymarket_api_secret="secret",  # noqa: S106 - test fixture
        polymarket_api_passphrase="passphrase",  # noqa: S106 - test fixture
    )
    service = HedgerService(settings)
    service.lock_manager = None
    service.fx_oracle._quote = FxQuote(zen_usd=Decimal("1.0"), fetched_at=datetime.now(UTC))
    service.fx_oracle._stale_override = False

    class LowBalanceWallet(StubWallet):
        def has_sufficient_balance(self, required_usdc: Decimal):
            return False, Decimal("0.01")

    service.wallet = LowBalanceWallet()

    commit = CommitEvent(
        market_id="m1",
        stake_zen=Decimal("10"),
        direction=OutcomeSide.YES,
        clob_token_id="token-yes",  # noqa: S106 - test fixture, not a secret
    )

    result = await service.ingest_commit(commit)
    assert result["status"] == "rejected"
    assert result["reason"] == "insufficient_usdc"


@pytest.mark.asyncio
async def test_ingest_commit_uses_fresh_lock_contexts_for_preview_and_persist():
    settings = Settings(
        hedger_private_key="0x" + "11" * 32,
        polymarket_api_key="key",
        polymarket_api_secret="secret",  # noqa: S106 - test fixture
        polymarket_api_passphrase="passphrase",  # noqa: S106 - test fixture
    )
    service = HedgerService(settings)
    service.wallet = StubWallet()
    service.clob = None
    service.fx_oracle._quote = FxQuote(zen_usd=Decimal("1.0"), fetched_at=datetime.now(UTC))
    service.fx_oracle._stale_override = False
    lock_manager = RecordingLockManager()
    service.lock_manager = lock_manager

    async def _commit_exists(_idempotency_key: str) -> bool:
        return False

    async def _preview_commit(*_args, **_kwargs):
        return {"market_id": "m1"}, None, []

    async def _record_commit(*_args, **_kwargs):
        return {"market_id": "m1"}, None, []

    service.repository.commit_exists = _commit_exists  # type: ignore[assignment]
    service.exposure_ledger.preview_commit = _preview_commit  # type: ignore[assignment]
    service.exposure_ledger.record_commit = _record_commit  # type: ignore[assignment]

    commit = CommitEvent(
        market_id="m1",
        stake_zen=Decimal("1"),
        direction=OutcomeSide.YES,
        clob_token_id="token-yes",  # noqa: S106 - test fixture, not a secret
    )

    result = await service.ingest_commit(commit)
    assert result.get("status") != "rejected"
    assert len(lock_manager.contexts) == 2
    assert all(lock.enter_count == 1 for lock in lock_manager.contexts)
