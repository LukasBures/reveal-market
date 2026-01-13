from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from app.bridge import BridgeClient
from tenacity import RetryError


class _FailingClient:
    def __init__(self):
        self.calls = 0

    async def post(self, _url, json=None, headers=None, timeout=None):
        self.calls += 1
        raise httpx.HTTPError("boom")


@pytest.mark.asyncio
async def test_bridge_submit_raises_after_retries():
    client = _FailingClient()
    bridge = BridgeClient(base_url="http://bridge", retry_attempts=2, client=client)

    with pytest.raises(RetryError):
        await bridge.bridge_to_zen(
            amount_usdc=Decimal("1"),
            destination="0x" + "1" * 40,
            slippage_bps=50,
            idempotency="key",
        )
    assert client.calls == 2
