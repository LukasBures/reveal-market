from __future__ import annotations

from decimal import Decimal

import pytest
from app.config import Settings
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

    instr = HedgeInstruction(
        market_id="m1",
        hedge_outcome=OutcomeSide.YES,
        action=HedgeAction.BUY,
        size_usd=Decimal("1"),
        slippage_bps=30,
        reason="test",
        target_coverage=0.9,
        clob_token_id="token-yes",
    )

    result = await service._execute_hedge(instr)
    assert result["status"] == "rejected"
    assert result["reason"] == "fill_below_threshold"


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

    class LowBalanceWallet(StubWallet):
        def has_sufficient_balance(self, required_usdc: Decimal):
            return False, Decimal("0.01")

    service.wallet = LowBalanceWallet()

    commit = CommitEvent(
        market_id="m1",
        stake_zen=Decimal("10"),
        direction=OutcomeSide.YES,
        clob_token_id="token-yes",
    )

    result = await service.ingest_commit(commit)
    assert result["status"] == "rejected"
    assert result["reason"] == "insufficient_usdc"
