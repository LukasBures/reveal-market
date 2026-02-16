from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.exposure import ExposureLedger
from app.risk import RiskEngine, RiskLimits
from app.types import CommitEvent, FxQuote, OutcomeSide


class _StubFx:
    def __init__(self, price: Decimal):
        self.quote = FxQuote(zen_usd=price, fetched_at=datetime.now(UTC))

    async def get_quote(self) -> FxQuote:
        return self.quote

    def usd_from_zen(self, zen_amount: Decimal, quote: FxQuote | None = None, apply_haircut: bool = True) -> Decimal:
        quote = quote or self.quote
        return (zen_amount * quote.zen_usd).quantize(Decimal("0.0001"))


@pytest.mark.asyncio
async def test_exposure_caps_surface_breaches():
    limits = RiskLimits(
        max_global_exposure_usd=Decimal("3"),
        max_per_market_usd=Decimal("3"),
        coverage_ratio_target=0.9,
        float_min_zen=Decimal("0"),
    )
    ledger = ExposureLedger(
        fx_oracle=_StubFx(Decimal("1")),
        limits=limits,
        risk_engine=RiskEngine(limits),
        repository=None,
    )
    commit = CommitEvent(
        market_id="m1",
        stake_zen=Decimal("4"),
        direction=OutcomeSide.YES,
        committed_at=datetime.now(UTC),
    )

    _snapshot, _instruction, breaches = await ledger.record_commit(commit)
    codes = {b.code for b in breaches}
    assert "max_per_market_exceeded" in codes
    assert "max_global_exceeded" in codes
