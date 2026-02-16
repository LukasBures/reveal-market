from __future__ import annotations

from decimal import Decimal

import pytest
from app.config import Settings
from app.service import HedgerService


class StubBridge:
    def __init__(self):
        self.calls: list[dict] = []

    async def bridge_to_zen(self, amount, destination, *, slippage_bps, idempotency):
        self.calls.append(
            {
                "direction": "usdc_to_zen",
                "amount": amount,
                "destination": destination,
                "slippage": slippage_bps,
                "idempotency": idempotency,
            }
        )
        return {"status": "ok"}

    async def bridge_to_usdc(self, amount, destination, *, slippage_bps, idempotency):
        self.calls.append(
            {
                "direction": "zen_to_usdc",
                "amount": amount,
                "destination": destination,
                "slippage": slippage_bps,
                "idempotency": idempotency,
            }
        )
        return {"status": "ok"}


@pytest.mark.asyncio
async def test_request_bridge_dispatches_to_client():
    settings = Settings(
        hedger_private_key="0x" + "11" * 32,
        polymarket_api_key="key",
        polymarket_api_secret="secret",  # noqa: S106 - test fixture
        polymarket_api_passphrase="passphrase",  # noqa: S106 - test fixture
    )
    service = HedgerService(settings)
    bridge = StubBridge()
    service.bridge_client = bridge  # type: ignore[assignment]

    destination = "0x" + "3" * 40
    result = await service.request_bridge("usdc_to_zen", Decimal("5"), destination, slippage_bps=25)
    assert result["status"] == "ok"
    assert bridge.calls[0]["direction"] == "usdc_to_zen"

    result = await service.request_bridge("zen_to_usdc", Decimal("2"), destination, slippage_bps=30)
    assert result["status"] == "ok"
    assert bridge.calls[1]["direction"] == "zen_to_usdc"
