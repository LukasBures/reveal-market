from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .types import SettlementBreakdown, TreasurySnapshot


class TreasuryManager:
    """Tracks split ZEN/USDC treasuries and LP revenue allocation."""

    def __init__(self, lp_share_percent: Decimal):
        self.lp_share_percent = self._validate_percent(lp_share_percent)
        self.zen_ledger = Decimal("0")
        self.usdc_ledger = Decimal("0")

    def record_loss(self, stake_zen: Decimal) -> None:
        """Losing stakes accrue to the ZEN ledger."""

        if stake_zen > 0:
            self.zen_ledger += stake_zen

    def record_rake(self, rake_zen: Decimal) -> None:
        if rake_zen > 0:
            self.zen_ledger += rake_zen

    def record_usdc_revenue(self, amount_usdc: Decimal) -> None:
        if amount_usdc > 0:
            self.usdc_ledger += amount_usdc

    def allocate_lp_share(self, platform_usdc_revenue: Decimal) -> Decimal:
        if platform_usdc_revenue <= 0:
            return Decimal("0")
        return (platform_usdc_revenue * self.lp_share_percent).quantize(Decimal("0.00000001"))

    def apply_settlement(self, breakdown: SettlementBreakdown) -> TreasurySnapshot:
        """Apply settlement flows to internal ledgers and return the snapshot."""

        if breakdown.user_outcome == "lose":
            self.record_loss(breakdown.stake_zen)
        self.record_rake(breakdown.rake_zen)
        self.record_usdc_revenue(breakdown.total_platform_usdc_revenue - breakdown.lp_share_usdc)
        return self.snapshot()

    def snapshot(self) -> TreasurySnapshot:
        return TreasurySnapshot(zen_balance=self.zen_ledger, usdc_balance=self.usdc_ledger)

    def _validate_percent(self, value: Decimal) -> Decimal:
        try:
            pct = Decimal(value)
        except InvalidOperation:
            raise ValueError("lp_share_percent must be a decimal")
        if pct < 0 or pct >= Decimal("0.5"):
            raise ValueError("lp_share_percent must be between 0 and 0.5 (exclusive)")
        return pct
