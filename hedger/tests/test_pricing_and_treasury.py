from __future__ import annotations

from decimal import Decimal

from app.bet_processor_zen import BetProcessorZen
from app.pricing_engine import PricingEngine
from app.treasury_manager import TreasuryManager


def test_pricing_quote_math():
    engine = PricingEngine(
        haircut_percent=Decimal("0.8"), worsen_percent=Decimal("0.03"), rake_percent=Decimal("0.02")
    )
    quote = engine.quote_bet(Decimal("10"), Decimal("0.20"))

    assert quote.displayed_odds_multiplier == Decimal("0.97")
    assert quote.rake_zen == Decimal("0.20000000")
    assert quote.refund_zen == Decimal("9.80000000")
    assert quote.hedge_usdc == Decimal("0.40000000")
    assert quote.total_monetization == Decimal("0.85")


def test_treasury_and_settlement_breakdown_win_flow():
    engine = PricingEngine(
        haircut_percent=Decimal("0.8"), worsen_percent=Decimal("0.03"), rake_percent=Decimal("0.02")
    )
    treasury = TreasuryManager(lp_share_percent=Decimal("0.18"))
    processor = BetProcessorZen(engine, treasury)
    quote = engine.quote_bet(Decimal("5"), Decimal("0.50"))

    breakdown = processor.settlement_breakdown(
        quote,
        hedge_cost_usdc=Decimal("2.25"),
        expected_usdc_payout_if_win=Decimal("2.75"),
        user_won=True,
        hedge_realized_pnl_usdc=Decimal("0.10"),
    )
    assert breakdown.refund_zen == quote.refund_zen
    assert breakdown.payout_profit_usdc == Decimal("0.50")
    snapshot = treasury.apply_settlement(breakdown)
    # Rake plus any losing stakes (none here) accrue to ZEN ledger.
    assert snapshot.zen_balance == quote.rake_zen
    assert snapshot.usdc_balance > Decimal("0")


def test_treasury_and_settlement_breakdown_loss_flow():
    engine = PricingEngine(
        haircut_percent=Decimal("0.8"), worsen_percent=Decimal("0.03"), rake_percent=Decimal("0.02")
    )
    treasury = TreasuryManager(lp_share_percent=Decimal("0.18"))
    processor = BetProcessorZen(engine, treasury)
    quote = engine.quote_bet(Decimal("3"), Decimal("0.40"))

    breakdown = processor.settlement_breakdown(
        quote,
        hedge_cost_usdc=Decimal("1.08"),
        expected_usdc_payout_if_win=Decimal("1.50"),
        user_won=False,
        hedge_realized_pnl_usdc=Decimal("0.20"),
    )
    assert breakdown.refund_zen == Decimal("0")
    assert breakdown.payout_profit_usdc == Decimal("0")
    snapshot = treasury.apply_settlement(breakdown)
    # ZEN ledger should capture the stake + rake
    assert snapshot.zen_balance >= quote.stake_zen
