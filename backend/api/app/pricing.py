from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from time import monotonic

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from app.config import Settings
from app.schemas import FxQuoteResponse, PricingQuoteResponse

MAX_PERCENT = Decimal("0.25")
_FX_CACHE: dict[str, Decimal | bool | float | str | None] = {}
_FX_HTTP_CLIENT: httpx.AsyncClient | None = None
_FX_CLIENT_TIMEOUT: float | None = None
_FX_CLIENT_CLASS: type[httpx.AsyncClient] = httpx.AsyncClient
_FX_CLIENT_LOCK = asyncio.Lock()

# FX source is pinned to the streamer; override in code if the streamer host changes.
STREAMER_FX_URL = "http://streamer:8100/fx/zen-usd"


def _resolved_fx_url(settings: Settings) -> str:
    """Use the streamer FX endpoint as the single source of truth."""

    return str(settings.fx_feed_url or STREAMER_FX_URL)


def _build_fx_timeout(settings: Settings, timeout_seconds: float) -> httpx.Timeout:
    return httpx.Timeout(
        timeout_seconds,
        connect=settings.fx_connect_timeout_seconds,
        read=settings.fx_read_timeout_seconds,
        write=settings.fx_write_timeout_seconds,
        pool=settings.fx_pool_timeout_seconds,
    )


def _build_fx_limits(settings: Settings) -> httpx.Limits:
    return httpx.Limits(
        max_connections=settings.fx_max_connections,
        max_keepalive_connections=settings.fx_max_keepalive_connections,
    )


async def _get_fx_client(timeout_seconds: float, settings: Settings) -> httpx.AsyncClient:
    """Reuse a single AsyncClient so TLS handshakes are not repeated per request."""

    global _FX_HTTP_CLIENT, _FX_CLIENT_TIMEOUT, _FX_CLIENT_CLASS
    async with _FX_CLIENT_LOCK:
        async_client_cls: type[httpx.AsyncClient] = httpx.AsyncClient
        needs_new = (
            _FX_HTTP_CLIENT is None
            or _FX_CLIENT_TIMEOUT != timeout_seconds
            or _FX_CLIENT_CLASS is not async_client_cls
            or getattr(_FX_HTTP_CLIENT, "is_closed", False)
        )
        if _FX_HTTP_CLIENT is not None and getattr(_FX_HTTP_CLIENT, "is_closed", False):
            # Close leftover transports from tests/reloads.
            await _FX_HTTP_CLIENT.aclose()
            _FX_HTTP_CLIENT = None
        if needs_new:
            _FX_HTTP_CLIENT = async_client_cls(
                timeout=_build_fx_timeout(settings, timeout_seconds),
                limits=_build_fx_limits(settings),
            )
            _FX_CLIENT_TIMEOUT = timeout_seconds
            _FX_CLIENT_CLASS = async_client_cls
        return _FX_HTTP_CLIENT or async_client_cls(timeout=timeout_seconds)


class PricingEngine:
    """Pure math helper for ZEN stake pricing."""

    def __init__(self, settings: Settings):
        self.rake_percent = self._validate_percent(settings.rake_percent, "rake_percent")
        self.haircut_percent = self._validate_percent(
            settings.haircut_percent, "haircut_percent", max_value=Decimal("1")
        )
        self.worsen_percent = self._validate_percent(settings.worsen_percent, "worsen_percent")
        self.edge_percent = self._validate_percent(settings.pricing_edge_percent, "pricing_edge_percent")

    @property
    def total_monetization(self) -> Decimal:
        return self.rake_percent + self.haircut_percent + self.worsen_percent

    def quote(self, stake_zen: Decimal, zen_usd: Decimal, price: Decimal) -> PricingQuoteResponse:
        if stake_zen <= 0:
            raise ValueError("stake_zen must be positive")
        if zen_usd <= 0:
            raise ValueError("zen_usd must be positive")
        if price <= 0:
            raise ValueError("price must be positive")

        displayed_multiplier = Decimal("1") - self.worsen_percent
        rake_zen = (stake_zen * self.rake_percent).quantize(Decimal("0.00000001"))
        refund_zen = (stake_zen - rake_zen).quantize(Decimal("0.00000001"))
        hedge_usdc = (stake_zen * zen_usd * (Decimal("1") - self.haircut_percent)).quantize(Decimal("0.00000001"))
        hedge_usdc = max(hedge_usdc, Decimal("0"))
        # Payout is based on odds with rake first, then haircut applied to the net stake.
        net_stake = stake_zen - rake_zen
        discounted = net_stake * (Decimal("1") - self.haircut_percent)
        discounted = max(discounted, Decimal("0"))
        payout_zen = (discounted / (price * (Decimal("1") + self.edge_percent))).quantize(
            Decimal("0.001"), rounding=ROUND_DOWN
        )

        return PricingQuoteResponse(
            stake_zen=stake_zen,
            zen_usd=zen_usd,
            displayed_odds_multiplier=displayed_multiplier,
            rake_zen=rake_zen,
            refund_zen=refund_zen,
            hedge_usdc=hedge_usdc,
            payout_zen=payout_zen,
            haircut_percent=self.haircut_percent,
            worsen_percent=self.worsen_percent,
            rake_percent=self.rake_percent,
            total_monetization=self.total_monetization,
        )

    @staticmethod
    def _validate_percent(value: float, label: str, max_value: Decimal = MAX_PERCENT) -> Decimal:
        try:
            pct = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"{label} must be a decimal") from exc
        if pct < 0 or pct >= max_value:
            raise ValueError(f"{label} must be between 0 and {max_value} (exclusive)")
        return pct


def _coerce_decimal(value) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        return None


def _coerce_price(value) -> Decimal | None:
    price = _coerce_decimal(value)
    if price is None or price <= 0:
        return None
    return price


def _parse_received_at(payload: dict) -> datetime | None:
    ts = None
    for key in ("received_at", "receivedAt", "fetched_at", "fetchedAt"):
        if isinstance(payload.get(key), str):
            ts = payload.get(key)
            break
    if ts is None:
        return None
    try:
        # Support Z suffix and naive timestamps by normalizing to UTC.
        normalized = ts.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError):
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
    client = await _get_fx_client(settings.fx_timeout_seconds, settings)

    async def _request() -> dict[str, object]:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_random_exponential(multiplier=0.2, max=2.0),
            retry=retry_if_exception_type(httpx.HTTPError),
            reraise=True,
        ):
            with attempt:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
        raise RuntimeError("failed to fetch FX price after retries")

    try:
        data = await _request()
        stale = bool(data.get("fx_stale") or data.get("stale"))
        raw = _extract_fx_price(data)
        received_at = _parse_received_at(data)
        if raw is None:
            raise ValueError("FX feed response missing zen_usd/price")
        zen_usd = raw
        _FX_CACHE.update(
            {
                "zen_usd": zen_usd,
                "stale": stale,
                "expires_at": now + cache_ttl,
                "received_at": received_at.isoformat() if received_at else None,
            }
        )
        return FxQuoteResponse(zen_usd=zen_usd, stale=stale, received_at=received_at)
    except (httpx.HTTPError, ValueError, InvalidOperation, TypeError) as exc:
        if use_cache_on_error and "zen_usd" in _FX_CACHE:
            _FX_CACHE.update({"stale": True, "expires_at": now + cache_ttl})
            fetch_fx_quote._cache_state = dict(_FX_CACHE)  # type: ignore[attr-defined]
            cached_ts = _FX_CACHE.get("received_at")
            parsed_ts = datetime.fromisoformat(str(cached_ts)) if cached_ts else None
            return FxQuoteResponse(
                zen_usd=Decimal(str(_FX_CACHE["zen_usd"])),
                stale=True,
                received_at=parsed_ts,
            )

        if not use_cache_on_error:
            raise exc

        _FX_CACHE.update(
            {
                "zen_usd": Decimal(str(settings.fx_fallback_price)),
                "stale": True,
                "expires_at": now + cache_ttl,
                "received_at": datetime.now(tz=UTC).isoformat(),
            }
        )
        fetch_fx_quote._cache_state = dict(_FX_CACHE)  # type: ignore[attr-defined]
        return FxQuoteResponse(
            zen_usd=Decimal(str(settings.fx_fallback_price)),
            stale=True,
            received_at=datetime.now(tz=UTC),
        )


def build_quote_audit_payload(
    *,
    quote_id: str,
    action: str,
    payload: dict,
    status: str | None = None,
    error: str | None = None,
    context: dict | None = None,
) -> dict[str, object]:
    return {
        "quote_id": quote_id,
        "action": action,
        "user_id": payload.get("user_id"),
        "wallet_address": payload.get("wallet_address"),
        "market_id": payload.get("market_id"),
        "market_address": payload.get("market_address"),
        "outcome_id": payload.get("outcome_id"),
        "chain_id": payload.get("chain_id"),
        "stake_zen": payload.get("stake_zen"),
        "stake_wei": payload.get("stake_wei"),
        "fx_scaled": payload.get("zen_usd_scaled") or payload.get("fx_scaled"),
        "zen_usd": payload.get("zen_usd"),
        "status": status,
        "error": error,
        "context": context,
    }


def fetch_fx_price_sync(settings: Settings) -> tuple[Decimal | None, bool, datetime | None]:
    """Synchronous wrapper around the async FX fetcher to preserve legacy call sites."""

    fx_quote = asyncio.run(fetch_fx_quote(settings))
    return fx_quote.zen_usd, fx_quote.stale, fx_quote.received_at
