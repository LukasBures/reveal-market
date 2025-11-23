from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .types import PricingQuote

MAX_PERCENT = Decimal("0.25")


class PricingEngine:
    """Deterministic pricing for ZEN-facing bets with USDC hedging."""

    def __init__(self, *, haircut_percent: Decimal, worsen_percent: Decimal, rake_percent: Decimal):
        self.haircut_percent = self._validate_percent(haircut_percent, "haircut_percent")
        self.worsen_percent = self._validate_percent(worsen_percent, "worsen_percent")
        self.rake_percent = self._validate_percent(rake_percent, "rake_percent")

    @property
    def total_monetisation(self) -> Decimal:
        return self.haircut_percent + self.worsen_percent + self.rake_percent

    def quote_bet(self, stake_zen: Decimal, zen_usd: Decimal) -> PricingQuote:
        if stake_zen <= 0:
            raise ValueError("stake_zen must be positive")
        if zen_usd <= 0:
            raise ValueError("zen_usd price must be positive")

        displayed_multiplier = Decimal("1") - self.worsen_percent
        rake_zen = (stake_zen * self.rake_percent).quantize(Decimal("0.00000001"))
        refund_zen = (stake_zen - rake_zen).quantize(Decimal("0.00000001"))
        hedge_usdc = (stake_zen * zen_usd * (Decimal("1") - self.haircut_percent)).quantize(Decimal("0.00000001"))
        hedge_usdc = max(hedge_usdc, Decimal("0"))

        return PricingQuote(
            stake_zen=stake_zen,
            zen_usd=zen_usd,
            displayed_odds_multiplier=displayed_multiplier,
            rake_zen=rake_zen,
            refund_zen=refund_zen,
            hedge_usdc=hedge_usdc,
            haircut_percent=self.haircut_percent,
            worsen_percent=self.worsen_percent,
            rake_percent=self.rake_percent,
            total_monetisation=self.total_monetisation,
        )

    def _validate_percent(self, value: Decimal, label: str) -> Decimal:
        try:
            percent = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"{label} must be a decimal percentage") from exc
        if percent < 0 or percent >= MAX_PERCENT:
            raise ValueError(f"{label} must be between 0 and {MAX_PERCENT} (exclusive)")
        return percent
