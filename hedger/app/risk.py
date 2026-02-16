from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from .types import RiskBreach, RiskReport, RiskSeverity


@dataclass(slots=True)
class RiskLimits:
    max_global_exposure_usd: Decimal
    max_per_market_usd: Decimal
    coverage_ratio_target: float
    float_min_zen: Decimal


class RiskEngine:
    """Evaluates whether hedging/risk constraints are satisfied."""

    def __init__(self, limits: RiskLimits):
        self.limits = limits

    def check_limits(
        self,
        *,
        market_id: str,
        market_net_usd: Decimal,
        absolute_market_usd: Decimal,
        total_absolute_usd: Decimal,
        coverage_ratio: float,
        float_balance_zen: Decimal,
    ) -> list[RiskBreach]:
        breaches: list[RiskBreach] = []
        if absolute_market_usd > self.limits.max_per_market_usd:
            breaches.append(
                RiskBreach(
                    code="max_per_market_exceeded",
                    severity=(
                        RiskSeverity.WARN
                        if absolute_market_usd <= self.limits.max_per_market_usd * Decimal("1.1")
                        else RiskSeverity.CRITICAL
                    ),
                    message="Per-market exposure cap exceeded",
                    market_id=market_id,
                    detail={"market_net_usd": str(market_net_usd), "limit": str(self.limits.max_per_market_usd)},
                )
            )
        if total_absolute_usd > self.limits.max_global_exposure_usd:
            breaches.append(
                RiskBreach(
                    code="max_global_exceeded",
                    severity=RiskSeverity.CRITICAL,
                    message="Global exposure cap exceeded",
                    detail={
                        "total_absolute_usd": str(total_absolute_usd),
                        "limit": str(self.limits.max_global_exposure_usd),
                    },
                )
            )
        if coverage_ratio < self.limits.coverage_ratio_target:
            breaches.append(
                RiskBreach(
                    code="coverage_below_target",
                    severity=RiskSeverity.WARN,
                    message="Hedging coverage is below target",
                    market_id=market_id,
                    detail={"coverage_ratio": coverage_ratio, "target": self.limits.coverage_ratio_target},
                )
            )
        if float_balance_zen < self.limits.float_min_zen:
            breaches.append(
                RiskBreach(
                    code="float_low",
                    severity=RiskSeverity.CRITICAL,
                    message="ZEN float below safety threshold",
                    detail={"float_balance_zen": str(float_balance_zen), "limit": str(self.limits.float_min_zen)},
                )
            )
        return breaches

    def report(self, breaches: Iterable[RiskBreach]) -> RiskReport:
        return RiskReport(
            breaches=list(breaches),
            max_global_exposure_usd=self.limits.max_global_exposure_usd,
            max_per_market_usd=self.limits.max_per_market_usd,
            coverage_ratio_target=self.limits.coverage_ratio_target,
            float_min_zen=self.limits.float_min_zen,
        )
