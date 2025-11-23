from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

try:
    import httpx
except ImportError:  # pragma: no cover - handled via runtime guard
    httpx = None  # type: ignore[assignment]
try:
    from tenacity import AsyncRetrying, RetryError, retry_if_exception_type, stop_after_attempt, wait_exponential
except ImportError:  # pragma: no cover - handled at runtime when _fetch_quote used
    AsyncRetrying = None  # type: ignore[assignment]
    RetryError = None  # type: ignore[assignment]
    retry_if_exception_type = stop_after_attempt = wait_exponential = None  # type: ignore[assignment]

from .types import FxQuote

logger = logging.getLogger("reveal_market.hedger.fx")


class FxOracle:
    """Stores FX quotes and enforces staleness before sizing hedges."""

    def __init__(
        self,
        *,
        feed_url: str,
        haircut_bps: int,
        timeout_seconds: int,
        max_age_seconds: int,
        client: httpx.AsyncClient | None = None,
        retry_attempts: int = 3,
        fallback_zen_usd: Decimal = Decimal("1"),
    ):
        if client is None and httpx is None:
            raise ImportError("httpx is required for FxOracle; install hedger dependencies (uv sync --project hedger)")
        if AsyncRetrying is None:
            raise ImportError(
                "tenacity is required for FxOracle; install hedger dependencies (uv sync --project hedger)"
            )
        self.feed_url = feed_url
        self.haircut_bps = haircut_bps
        self.timeout_seconds = timeout_seconds
        self.max_age_seconds = max_age_seconds
        self.client = client or httpx.AsyncClient()
        self._quote: FxQuote | None = None
        self._lock = asyncio.Lock()
        self._retry_attempts = retry_attempts
        self._fallback_zen_usd = fallback_zen_usd

    async def get_quote(self) -> FxQuote:
        async with self._lock:
            if self._quote and not self._is_stale(self._quote):
                return self._quote
            quote = await self._fetch_quote()
            self._quote = quote
            return quote

    async def refresh(self) -> FxQuote:
        async with self._lock:
            quote = await self._fetch_quote()
            self._quote = quote
            return quote

    def usd_from_zen(self, zen_amount: Decimal, quote: FxQuote | None = None, apply_haircut: bool = True) -> Decimal:
        quote = quote or self._quote
        if not quote:
            raise ValueError("FX quote is not available; call get_quote() first")
        haircut = Decimal(10_000 - self.haircut_bps) / Decimal(10_000) if apply_haircut else Decimal(1)
        haircut = haircut.quantize(Decimal("0.0001"))
        return (zen_amount * quote.zen_usd * haircut).quantize(Decimal("0.00000001"))

    def _is_stale(self, quote: FxQuote) -> bool:
        return datetime.now(UTC) - quote.fetched_at > timedelta(seconds=self.max_age_seconds)

    async def _fetch_quote(self) -> FxQuote:
        fallback_quote = FxQuote(zen_usd=self._fallback_zen_usd, fetched_at=datetime.now(UTC))
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._retry_attempts),
                wait=wait_exponential(min=0.1, max=2),
                retry=retry_if_exception_type(Exception),
            ):
                with attempt:
                    response = await self.client.get(self.feed_url, timeout=self.timeout_seconds)
                    response.raise_for_status()
                    data = response.json()
                    price = data.get("price") or data.get("zen_usd") or data.get("zenUSD")
                    if price is None:
                        raise ValueError("FX feed response missing zen_usd/price")
                    zen_usd = Decimal(str(price))
                    quote = FxQuote(zen_usd=zen_usd, fetched_at=datetime.now(UTC))
                    logger.debug(
                        "Fetched FX price",
                        extra={
                            "event": "fx.refresh",
                            "zen_usd": str(zen_usd),
                            "feed_url": self.feed_url,
                        },
                    )
                    return quote
        except RetryError as exc:
            logger.warning(
                "FX feed unavailable; using fallback price",
                extra={
                    "event": "fx.refresh.fallback",
                    "feed_url": self.feed_url,
                    "fallback_zen_usd": str(self._fallback_zen_usd),
                    "error": str(exc),
                },
            )
            return fallback_quote
        except (InvalidOperation, httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "FX feed returned invalid response; using fallback price",
                extra={
                    "event": "fx.refresh.fallback",
                    "feed_url": self.feed_url,
                    "fallback_zen_usd": str(self._fallback_zen_usd),
                    "error": str(exc),
                },
            )
            return fallback_quote

    def stale(self) -> bool:
        return self._quote is None or self._is_stale(self._quote)
