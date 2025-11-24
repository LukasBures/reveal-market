from __future__ import annotations

from decimal import Decimal, InvalidOperation

import httpx

from app.config import Settings
from app.schemas import FxQuoteResponse, PricingQuoteResponse

MAX_PERCENT = Decimal("0.25")


class PricingEngine:
    """Pure math helper for ZEN stake pricing."""

    def __init__(self, settings: Settings):
        self.rake_percent = self._validate_percent(settings.rake_percent, "rake_percent")
        self.haircut_percent = self._validate_percent(settings.haircut_percent, "haircut_percent")
        self.worsen_percent = self._validate_percent(settings.worsen_percent, "worsen_percent")

    @property
    def total_monetisation(self) -> Decimal:
        return self.rake_percent + self.haircut_percent + self.worsen_percent

    def quote(self, stake_zen: Decimal, zen_usd: Decimal) -> PricingQuoteResponse:
        if stake_zen <= 0:
            raise ValueError("stake_zen must be positive")
        if zen_usd <= 0:
            raise ValueError("zen_usd must be positive")

        displayed_multiplier = Decimal("1") - self.worsen_percent
        rake_zen = (stake_zen * self.rake_percent).quantize(Decimal("0.00000001"))
        refund_zen = (stake_zen - rake_zen).quantize(Decimal("0.00000001"))
        hedge_usdc = (stake_zen * zen_usd * (Decimal("1") - self.haircut_percent)).quantize(Decimal("0.00000001"))
        hedge_usdc = max(hedge_usdc, Decimal("0"))

        return PricingQuoteResponse(
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

    def _validate_percent(self, value: float, label: str) -> Decimal:
        try:
            pct = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"{label} must be a decimal") from exc
        if pct < 0 or pct >= MAX_PERCENT:
            raise ValueError(f"{label} must be between 0 and {MAX_PERCENT} (exclusive)")
        return pct


def _coerce_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_fx_price(payload: dict) -> float | None:
    """Extract a USD price from common FX payload shapes."""
    if not isinstance(payload, dict):
        return None

    # Direct keys from common feeds.
    for key in ("price", "zen_usd", "zenUSD", "fx_zen_usd"):
        price = _coerce_float(payload.get(key))
        if price is not None:
            return price

    fx_block = payload.get("fx")
    if isinstance(fx_block, dict):
        price = _coerce_float(fx_block.get("zen_usd"))
        if price is not None:
            return price

    # Nested maps such as Coingecko: {"horizen": {"usd": 7.5}}
    for value in payload.values():
        if isinstance(value, dict):
            for nested_key in ("usd", "price", "zen_usd", "zenUSD"):
                price = _coerce_float(value.get(nested_key))
                if price is not None:
                    return price
    return None


async def fetch_fx_quote(settings: Settings) -> FxQuoteResponse:
    """Fetch the latest ZEN/USD price from the configured feed."""

    async with httpx.AsyncClient(timeout=settings.fx_timeout_seconds) as client:
        response = await client.get(str(settings.fx_feed_url))
        response.raise_for_status()
        data = response.json()
        stale = bool(data.get("fx_stale") or data.get("stale"))
        raw = _extract_fx_price(data)
        if raw is None:
            raise ValueError("FX feed response missing zen_usd/price")
        zen_usd = float(raw)
    return FxQuoteResponse(zen_usd=zen_usd, stale=stale)
