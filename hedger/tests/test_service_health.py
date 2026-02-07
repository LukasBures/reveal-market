from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.config import Settings
from app.service import HedgerService


@pytest.mark.asyncio
async def test_health_reports_fx_and_utilization():
    settings = Settings(
        vault_rpc_url="http://localhost:8545",
        vault_private_key="0x" + "11" * 32,
        vault_sender_address="0x" + "01" * 20,
        lp_vault_address="0x" + "02" * 20,
    )
    service = HedgerService(settings)
    now = datetime.now(UTC)

    class DummyRepository:
        async def latest_commit_timestamp(self):
            return now

    class DummyFx:
        def stale(self):
            return True

    class DummyVault:
        async def current_utilization(self):
            return 0.42

    service.repository = DummyRepository()
    service.fx_oracle = DummyFx()
    service.vault_client = DummyVault()

    payload = await service.health()
    assert payload["fx_stale"] is True
    assert payload["latest_commit_at"] == now.isoformat()
    assert payload["lp_utilization"] == 0.42
    assert payload["status"] == "ok"
