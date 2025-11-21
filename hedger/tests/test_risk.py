from __future__ import annotations

from decimal import Decimal

from app.risk import RiskEngine, RiskLimits
from app.types import RiskSeverity


def test_risk_engine_flags_excess_exposure_and_liquidity():
    limits = RiskLimits(
        max_global_exposure_usd=Decimal("100"),
        max_per_market_usd=Decimal("50"),
        coverage_ratio_target=0.9,
        lp_utilization_limit=0.8,
        float_min_zen=Decimal("10"),
    )
    engine = RiskEngine(limits)

    breaches = engine.check_limits(
        market_id="m1",
        market_net_usd=Decimal("60"),
        absolute_market_usd=Decimal("60"),
        total_absolute_usd=Decimal("120"),
        coverage_ratio=0.5,
        lp_utilization=0.9,
        float_balance_zen=Decimal("5"),
    )

    codes = {b.code for b in breaches}
    assert codes == {
        "max_per_market_exceeded",
        "max_global_exceeded",
        "coverage_below_target",
        "lp_utilization_high",
        "float_low",
    }
    severity_by_code = {b.code: b.severity for b in breaches}
    assert severity_by_code["coverage_below_target"] == RiskSeverity.WARN
    # Exposure + float limits should be marked critical.
    assert severity_by_code["max_global_exceeded"] == RiskSeverity.CRITICAL
    assert severity_by_code["max_per_market_exceeded"] == RiskSeverity.CRITICAL
    assert severity_by_code["float_low"] == RiskSeverity.CRITICAL
