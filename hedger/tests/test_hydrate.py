from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.exposure import ExposureLedger
from app.risk import RiskEngine, RiskLimits


@pytest.mark.asyncio
async def test_hydrate_restores_market_state():
    limits = RiskLimits(
        max_global_exposure_usd=Decimal("100000"),
        max_per_market_usd=Decimal("10000"),
        coverage_ratio_target=0.98,
        float_min_zen=Decimal("100"),
    )
    ledger = ExposureLedger(
        fx_oracle=None,  # not used during hydration
        limits=limits,
        risk_engine=RiskEngine(limits),
        repository=None,
    )
    await ledger.hydrate_market(
        "m1",
        yes_zen=Decimal("5"),
        no_zen=Decimal("3"),
        yes_usd=Decimal("1.0"),
        no_usd=Decimal("0.5"),
        hedged_usd=Decimal("1.2"),
        last_update=datetime.now(UTC),
    )

    snapshots = await ledger.snapshot()
    assert len(snapshots) == 1
    snap = snapshots[0]
    assert snap.market_id == "m1"
    assert snap.yes_zen == Decimal("5")
    assert snap.no_zen == Decimal("3")
    assert snap.hedged_usd == Decimal("1.2")
    assert snap.coverage_ratio == pytest.approx(1.0)  # hedged exceeds abs(net_usd) -> capped at 1
