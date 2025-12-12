from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.storage import HedgerRepository
from app.types import CommitEvent, HedgeAction, HedgeInstruction, OutcomeSide


@pytest.mark.asyncio
async def test_repository_aggregates_roundtrip(tmp_path):
    repo = HedgerRepository(f"sqlite+aiosqlite:///{tmp_path}/hedger.db")
    await repo.create_schema()

    commit_yes = CommitEvent(
        market_id="m1",
        stake_zen=Decimal("10"),
        direction=OutcomeSide.YES,
        committed_at=datetime.now(UTC),
    )
    commit_no = CommitEvent(
        market_id="m1",
        stake_zen=Decimal("4"),
        direction=OutcomeSide.NO,
        committed_at=datetime.now(UTC),
    )
    await repo.record_commit(commit_yes, stake_usd=Decimal("2.5"))
    await repo.record_commit(commit_no, stake_usd=Decimal("1.0"))

    instruction = HedgeInstruction(
        market_id="m1",
        hedge_outcome=OutcomeSide.YES,
        action=HedgeAction.BUY,
        size_usd=Decimal("1.25"),
        slippage_bps=15,
        reason="unit_test",
        target_coverage=0.9,
    )
    await repo.record_hedge_instruction(instruction, response_payload={"ok": True})

    aggregates = await repo.load_commit_aggregates()
    totals = await repo.load_hedge_totals()

    assert "m1" in aggregates
    agg = aggregates["m1"]
    assert agg["yes_zen"] == Decimal("10")
    assert agg["no_zen"] == Decimal("4")
    assert agg["yes_usd"] == Decimal("2.5")
    assert agg["no_usd"] == Decimal("1.0")
    assert totals["m1"] == Decimal("1.25")
    assert agg["last_update"] is not None


@pytest.mark.asyncio
async def test_repository_commit_idempotency(tmp_path):
    repo = HedgerRepository(f"sqlite+aiosqlite:///{tmp_path}/idem.db")
    await repo.create_schema()
    commit = CommitEvent(
        market_id="m2",
        stake_zen=Decimal("1"),
        direction=OutcomeSide.YES,
        committed_at=datetime.now(UTC),
        idempotency_key="unique-key",
    )
    await repo.record_commit(commit, stake_usd=Decimal("0.5"))
    assert await repo.commit_exists("unique-key") is True
    assert await repo.commit_exists("other-key") is False
