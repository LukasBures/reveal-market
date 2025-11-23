from __future__ import annotations

from decimal import Decimal

import pytest
from app.config import Settings
from app.service import HedgerService
from app.types import HedgeAction, HedgeInstruction, OutcomeSide


class StubPolymarketClient:
    def __init__(self, slippage_bps: int):
        self.slippage_bps = slippage_bps

    async def quote_execution(
        self, market_id: str, outcome: OutcomeSide, action: HedgeAction, size_usd: Decimal
    ) -> dict:
        return {"slippage_bps": self.slippage_bps}


@pytest.mark.asyncio
async def test_execute_hedge_rejects_high_slippage(monkeypatch):
    settings = Settings(
        vault_rpc_url="http://localhost:8545",
        vault_private_key="0x" + "11" * 32,
        vault_sender_address="0x" + "01" * 20,
        lp_vault_address="0x" + "02" * 20,
    )
    service = HedgerService(settings)
    service.lock_manager = None
    service.polymarket_client = StubPolymarketClient(slippage_bps=settings.max_slippage_bps + 50)  # type: ignore[assignment]

    instr = HedgeInstruction(
        market_id="m1",
        hedge_outcome=OutcomeSide.YES,
        action=HedgeAction.BUY,
        size_usd=Decimal("1.0"),
        slippage_bps=30,
        reason="test",
        target_coverage=0.9,
    )

    result = await service._execute_hedge(instr)
    assert result["status"] == "rejected"
    assert result["reason"] == "slippage_limit"
