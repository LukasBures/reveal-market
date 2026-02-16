from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal

import pytest
from app.exposure import ExposureLedger
from app.risk import RiskEngine, RiskLimits
from app.types import CommitEvent, FxQuote, OutcomeSide


class StubFx:
    def __init__(self, price: Decimal):
        self.quote = FxQuote(zen_usd=price, fetched_at=datetime.now(UTC))

    async def get_quote(self) -> FxQuote:
        return self.quote

    def usd_from_zen(self, zen_amount: Decimal, quote: FxQuote | None = None, apply_haircut: bool = True) -> Decimal:
        quote = quote or self.quote
        # Apply a 5% haircut on top of the provided price.
        return (zen_amount * quote.zen_usd * Decimal("0.95")).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)


@pytest.mark.asyncio
async def test_record_commit_updates_exposure_and_builds_instruction():
    limits = RiskLimits(
        max_global_exposure_usd=Decimal("100000"),
        max_per_market_usd=Decimal("10000"),
        coverage_ratio_target=0.98,
        float_min_zen=Decimal("100"),
    )
    ledger = ExposureLedger(
        fx_oracle=StubFx(Decimal("0.20")),
        limits=limits,
        risk_engine=RiskEngine(limits),
        repository=None,
    )
    commit = CommitEvent(
        market_id="market-1",
        stake_zen=Decimal("10"),
        direction=OutcomeSide.YES,
        committed_at=datetime.now(UTC),
    )

    snapshot, instruction, breaches = await ledger.record_commit(commit)

    assert breaches[0].code == "coverage_below_target"
    assert breaches[0].market_id == "market-1"
    assert snapshot.market_id == "market-1"
    assert snapshot.yes_zen == Decimal("10")
    assert snapshot.no_zen == Decimal("0")
    assert snapshot.net_zen == Decimal("10")
    # 10 ZEN * $0.20 * 0.95 haircut = $1.9
    assert snapshot.yes_usd == Decimal("1.9000")
    assert instruction is not None
    assert instruction.market_id == "market-1"
    assert instruction.size_usd.quantize(Decimal("0.0001")) == Decimal("1.8620")


@pytest.mark.asyncio
async def test_instruction_direction_and_fill_updates_coverage():
    limits = RiskLimits(
        max_global_exposure_usd=Decimal("100000"),
        max_per_market_usd=Decimal("10000"),
        coverage_ratio_target=0.9,
        float_min_zen=Decimal("100"),
    )
    ledger = ExposureLedger(
        fx_oracle=StubFx(Decimal("0.50")),
        limits=limits,
        risk_engine=RiskEngine(limits),
        repository=None,
    )
    commit = CommitEvent(
        market_id="market-yes",
        stake_zen=Decimal("2"),
        direction=OutcomeSide.YES,
        committed_at=datetime.now(UTC),
    )
    snapshot, instruction, breaches = await ledger.record_commit(commit)
    assert snapshot.net_usd > 0
    assert instruction is not None
    assert instruction.hedge_outcome == OutcomeSide.YES
    assert instruction.action == "sell"
    assert snapshot.coverage_ratio < 1

    updated = await ledger.register_fill(commit.market_id, size_usd=instruction.size_usd)
    assert updated is not None
    assert updated.hedged_usd == instruction.size_usd
    assert updated.coverage_ratio <= 1


@pytest.mark.asyncio
async def test_overhedged_triggers_unwind_instruction():
    limits = RiskLimits(
        max_global_exposure_usd=Decimal("100000"),
        max_per_market_usd=Decimal("10000"),
        coverage_ratio_target=0.5,
        float_min_zen=Decimal("100"),
    )
    ledger = ExposureLedger(
        fx_oracle=StubFx(Decimal("1")),
        limits=limits,
        risk_engine=RiskEngine(limits),
        repository=None,
    )
    commit = CommitEvent(
        market_id="m-unwind",
        stake_zen=Decimal("10"),
        direction=OutcomeSide.NO,
        committed_at=datetime.now(UTC),
    )
    snapshot, instruction, _ = await ledger.record_commit(commit)
    assert instruction is not None
    # Simulate we fully hedged and then some (over 100%).
    await ledger.register_fill(commit.market_id, size_usd=Decimal("6"))
    unwind_instruction = ledger._plan_instruction(ledger._markets[commit.market_id])  # type: ignore[attr-defined]
    assert unwind_instruction is not None
    assert unwind_instruction.is_unwind is True
    # For NO exposure, unwind action should be SELL.
    assert unwind_instruction.action == "sell"
