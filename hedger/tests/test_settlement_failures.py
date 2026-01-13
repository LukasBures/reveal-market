from __future__ import annotations

import httpx
import pytest
from app.settlement import SettlementCoordinator


class _FailingClient:
    async def post(self, _url, json=None, headers=None, timeout=None):
        raise httpx.HTTPError("boom")


@pytest.mark.asyncio
async def test_settlement_request_bubbles_http_error():
    coordinator = SettlementCoordinator(base_url="http://prover", timeout_seconds=1)
    coordinator.client = _FailingClient()  # type: ignore[assignment]

    with pytest.raises(httpx.HTTPError):
        await coordinator.request_settlement("market-1", {"outcome": "YES"})
