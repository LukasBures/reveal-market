from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx
from tenacity import AsyncRetrying, RetryError, retry_if_exception_type, stop_after_attempt, wait_exponential

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
    ):
        self.feed_url = feed_url
        self.haircut_bps = haircut_bps
        self.timeout_seconds = timeout_seconds
        self.max_age_seconds = max_age_seconds
        self.client = client or httpx.AsyncClient()
        self._quote: FxQuote | None = None
        self._lock = asyncio.Lock()
        self._retry_attempts = retry_attempts

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

    def usd_from_zen(self, zen_amount: Decimal, quote: FxQuote | None = None) -> Decimal:
        quote = quote or self._quote
        if not quote:
            raise ValueError("FX quote is not available; call get_quote() first")
        haircut = (Decimal(10_000 - self.haircut_bps) / Decimal(10_000)).quantize(Decimal("0.0001"))
        return (zen_amount * quote.zen_usd * haircut).quantize(Decimal("0.00000001"))

    def _is_stale(self, quote: FxQuote) -> bool:
        return datetime.now(UTC) - quote.fetched_at > timedelta(seconds=self.max_age_seconds)

    async def _fetch_quote(self) -> FxQuote:
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
            raise RuntimeError(f"Failed to fetch FX price after retries: {exc}") from exc
        except (InvalidOperation, httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(f"Invalid FX feed response: {exc}") from exc

    def stale(self) -> bool:
        return self._quote is None or self._is_stale(self._quote)
