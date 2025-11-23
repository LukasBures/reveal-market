from __future__ import annotations

from decimal import Decimal

from .pricing_engine import PricingEngine
from .treasury_manager import TreasuryManager
from .types import PricingQuote, SettlementBreakdown

USDC_QUANTIZE = Decimal("0.00000001")


class BetProcessorZen:
    """Coordinates user-facing pricing with treasury-aware settlement math."""

    def __init__(self, pricing_engine: PricingEngine, treasury: TreasuryManager):
        self.pricing_engine = pricing_engine
        self.treasury = treasury

    def price_bet(self, stake_zen: Decimal, zen_usd: Decimal) -> PricingQuote:
        return self.pricing_engine.quote_bet(stake_zen, zen_usd)

    def settlement_breakdown(
        self,
        pricing: PricingQuote,
        *,
        hedge_cost_usdc: Decimal,
        expected_usdc_payout_if_win: Decimal,
        user_won: bool,
        hedge_realized_pnl_usdc: Decimal = Decimal("0"),
    ) -> SettlementBreakdown:
        """Return settlement flows for a bet using the dual-ledger rules."""

        hedge_cost_usdc = hedge_cost_usdc.quantize(USDC_QUANTIZE)
        expected_usdc_payout_if_win = expected_usdc_payout_if_win.quantize(USDC_QUANTIZE)
        hedge_realized_pnl_usdc = hedge_realized_pnl_usdc.quantize(USDC_QUANTIZE)

        platform_carry_usdc = (pricing.hedge_usdc * pricing.haircut_percent).quantize(USDC_QUANTIZE)
        platform_usdc_revenue = max(platform_carry_usdc + hedge_realized_pnl_usdc, Decimal("0"))

        if user_won:
            profit_usdc = (expected_usdc_payout_if_win - hedge_cost_usdc).quantize(USDC_QUANTIZE)
            payout_profit_usdc = max(profit_usdc, Decimal("0"))
            outcome = "win"
        else:
            payout_profit_usdc = Decimal("0")
            outcome = "lose"
            platform_usdc_revenue += max(-hedge_cost_usdc, Decimal("0"))

        lp_share_usdc = self.treasury.allocate_lp_share(platform_usdc_revenue)
        repay_amount_usdc = hedge_cost_usdc + lp_share_usdc

        return SettlementBreakdown(
            stake_zen=pricing.stake_zen,
            refund_zen=pricing.refund_zen if user_won else Decimal("0"),
            rake_zen=pricing.rake_zen,
            payout_profit_usdc=payout_profit_usdc,
            borrowed_usdc=hedge_cost_usdc,
            lp_share_usdc=lp_share_usdc,
            repay_amount_usdc=repay_amount_usdc,
            total_platform_usdc_revenue=platform_usdc_revenue,
            user_outcome=outcome,
        )
