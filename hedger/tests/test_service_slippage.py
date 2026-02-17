from __future__ import annotations

from decimal import Decimal

import pytest
from app.config import Settings
from app.service import HedgerService
from app.types import HedgeAction, HedgeInstruction, OutcomeSide


@pytest.mark.asyncio
async def test_execute_hedge_rejects_when_clob_missing(monkeypatch):
    settings = Settings(
        hedger_private_key="0x" + "11" * 32,
        polymarket_api_key="key",
        polymarket_api_secret="secret",  # noqa: S106 - test fixture
        polymarket_api_passphrase="passphrase",  # noqa: S106 - test fixture
    )
    service = HedgerService(settings)
    service.lock_manager = None
    service.clob = None

    class DummyWallet:
        def has_sufficient_balance(self, required_usdc: Decimal):
            return True, Decimal("100")

        def ensure_allowance(self):
            return None

    service.wallet = DummyWallet()

    instr = HedgeInstruction(
        market_id="123",
        clob_token_id="123",  # noqa: S106 - test fixture, not a secret
        hedge_outcome=OutcomeSide.YES,
        action=HedgeAction.BUY,
        size_usd=Decimal("1.0"),
        slippage_bps=30,
        reason="test",
        target_coverage=0.9,
    )

    result = await service._execute_hedge(instr)
    assert result["status"] == "rejected"
    assert result["reason"] == "clob_unavailable"
