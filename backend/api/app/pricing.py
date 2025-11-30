from __future__ import annotations

from decimal import Decimal, InvalidOperation
from time import monotonic

import httpx
from tenacity import AsyncRetrying, Retrying, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from app.config import Settings
from app.schemas import FxQuoteResponse, PricingQuoteResponse

MAX_PERCENT = Decimal("0.25")
_FX_CACHE: dict[str, Decimal | bool | float] = {}

# FX source is pinned to the streamer; override in code if the streamer host changes.
STREAMER_FX_URL = "http://streamer:8100/fx/zen-usd"


def _resolved_fx_url(settings: Settings) -> str:
    """Use the streamer FX endpoint as the single source of truth."""

    return STREAMER_FX_URL


class PricingEngine:
    """Pure math helper for ZEN stake pricing."""

    def __init__(self, settings: Settings):
        self.rake_percent = self._validate_percent(settings.rake_percent, "rake_percent")
        self.haircut_percent = self._validate_percent(settings.haircut_percent, "haircut_percent")
        self.worsen_percent = self._validate_percent(settings.worsen_percent, "worsen_percent")

    @property
    def total_monetization(self) -> Decimal:
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
            total_monetization=self.total_monetization,
        )

    @staticmethod
    def _validate_percent(value: float, label: str) -> Decimal:
        try:
            pct = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"{label} must be a decimal") from exc
        if pct < 0 or pct >= MAX_PERCENT:
            raise ValueError(f"{label} must be between 0 and {MAX_PERCENT} (exclusive)")
        return pct


def _coerce_decimal(value) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        return None


def _extract_fx_price(payload: dict) -> Decimal | None:
    """Extract a USD price from common FX payload shapes."""
    if not isinstance(payload, dict):
        return None

    # Direct keys from common feeds.
    for key in ("price", "zen_usd", "zenUSD", "fx_zen_usd"):
        price = _coerce_decimal(payload.get(key))
        if price is not None:
            return price

    fx_block = payload.get("fx")
    if isinstance(fx_block, dict):
        price = _coerce_decimal(fx_block.get("zen_usd"))
        if price is not None:
            return price

    # Nested maps such as Coingecko: {"horizen": {"usd": 7.5}}
    for value in payload.values():
        if isinstance(value, dict):
            for nested_key in ("usd", "price", "zen_usd", "zenUSD"):
                price = _coerce_decimal(value.get(nested_key))
                if price is not None:
                    return price
    return None


async def fetch_fx_quote(settings: Settings, *, use_cache_on_error: bool = True) -> FxQuoteResponse:
    """Fetch the latest ZEN/USD price from the configured feed."""

    now = monotonic()
    cache_ttl = float(settings.fx_cache_ttl_seconds)
    url = _resolved_fx_url(settings)

    async def _request() -> dict:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_random_exponential(multiplier=0.2, max=2.0),
            retry=retry_if_exception_type(httpx.HTTPError),
            reraise=True,
        ):
            with attempt:
                async with httpx.AsyncClient(timeout=settings.fx_timeout_seconds) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    return response.json()

    try:
        data = await _request()
        stale = bool(data.get("fx_stale") or data.get("stale"))
        raw = _extract_fx_price(data)
        if raw is None:
            raise ValueError("FX feed response missing zen_usd/price")
        zen_usd = raw
        _FX_CACHE.update({"zen_usd": zen_usd, "stale": stale, "expires_at": now + cache_ttl})
        return FxQuoteResponse(zen_usd=zen_usd, stale=stale)
    except (httpx.HTTPError, ValueError, InvalidOperation, TypeError):
        if use_cache_on_error and "zen_usd" in _FX_CACHE:
            _FX_CACHE.update({"stale": True, "expires_at": now + cache_ttl})
            fetch_fx_quote._cache_state = dict(_FX_CACHE)  # type: ignore[attr-defined]
            return FxQuoteResponse(zen_usd=Decimal(str(_FX_CACHE["zen_usd"])), stale=True)

        _FX_CACHE.update(
            {"zen_usd": Decimal(str(settings.fx_fallback_price)), "stale": True, "expires_at": now + cache_ttl}
        )
        fetch_fx_quote._cache_state = dict(_FX_CACHE)  # type: ignore[attr-defined]
        return FxQuoteResponse(zen_usd=Decimal(str(settings.fx_fallback_price)), stale=True)


def fetch_fx_price_sync(settings: Settings) -> tuple[Decimal | None, bool]:
    """Synchronous FX fetch with bounded retries and stale flag."""

    now = monotonic()
    url = _resolved_fx_url(settings)
    expires_at = _FX_CACHE.get("expires_at")
    if expires_at and expires_at > now and "zen_usd" in _FX_CACHE:
        price = _FX_CACHE.get("zen_usd")
        stale = bool(_FX_CACHE.get("stale"))
        return Decimal(str(price)) if price is not None else None, stale

    retryer = Retrying(
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(multiplier=0.2, max=2.0),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )

    with httpx.Client(timeout=settings.fx_timeout_seconds) as client:
        for attempt in retryer:
            with attempt:
                response = client.get(url)
                response.raise_for_status()
                data = response.json()
                stale = bool(data.get("fx_stale") or data.get("stale"))
                raw = _extract_fx_price(data)
                if raw is None:
                    raise ValueError("FX feed response missing zen_usd/price")
                _FX_CACHE.update(
                    {"zen_usd": raw, "stale": stale, "expires_at": now + float(settings.fx_cache_ttl_seconds)}
                )
                return raw, stale
    return None, True
