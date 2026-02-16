from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.config import Settings
from app.service import HedgerService


@pytest.mark.asyncio
async def test_health_reports_fx_and_utilization():
    settings = Settings(
        hedger_private_key="0x" + "11" * 32,
    )
    service = HedgerService(settings)
    now = datetime.now(UTC)

    class DummyRepository:
        async def latest_commit_timestamp(self):
            return now

    class DummyFx:
        def stale(self):
            return True

    service.repository = DummyRepository()
    service.fx_oracle = DummyFx()
    service.wallet = None

    payload = await service.health()
    assert payload["fx_stale"] is True
    assert payload["latest_commit_at"] == now.isoformat()
    assert payload["wallet_unavailable"] is True
    assert payload["status"] == "degraded"
