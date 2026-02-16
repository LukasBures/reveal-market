from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.config import Settings
from app.service import HedgerService
from app.storage import HedgerRepository
from app.types import CommitEvent, OutcomeSide


class StubSettler:
    def __init__(self):
        self.requests: list[dict] = []

    async def request_settlement(self, market_id: str, payload: dict) -> dict:
        self.requests.append({"market_id": market_id, "payload": payload})
        return {"ok": True, "market_id": market_id}


@pytest.mark.asyncio
async def test_builds_prover_payload_and_marks_resolved(tmp_path):
    settings = Settings(
        hedger_private_key="0x" + "11" * 32,
    )
    service = HedgerService(settings)
    service.repository = HedgerRepository(f"sqlite+aiosqlite:///{tmp_path}/settle.db")  # type: ignore
    await service.repository.create_schema()
    service.settlement = StubSettler()  # type: ignore
    # Seed commits
    await service.repository.record_commit(
        CommitEvent(
            market_id="m3",
            stake_zen=Decimal("2"),
            direction=OutcomeSide.YES,
            committed_at=datetime.now(UTC),
        ),
        stake_usd=Decimal("1"),
    )
    await service.repository.record_commit(
        CommitEvent(
            market_id="m3",
            stake_zen=Decimal("3"),
            direction=OutcomeSide.NO,
            committed_at=datetime.now(UTC),
        ),
        stake_usd=Decimal("1.5"),
    )

    result = await service.settle_market("m3", OutcomeSide.NO)

    assert result["status"] == "resolved"
    # Settlement payload contains totals per outcome and commit count.
    payload = result["payload"]
    assert payload["commit_count"] == 2
    assert payload["total_yes_zen"] == "2.00000000"
    assert payload["total_no_zen"] == "3.00000000"
    assert await service.repository.is_market_resolved("m3") is True
