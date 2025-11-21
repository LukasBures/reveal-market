from __future__ import annotations

import logging
from decimal import Decimal

import httpx
from tenacity import AsyncRetrying, RetryError, retry_if_exception_type, stop_after_attempt, wait_exponential

from .logging_config import log_event
from .types import HedgeAction, OutcomeSide

logger = logging.getLogger("reveal_market.hedger.polymarket")


class PolymarketClient:
    """Lightweight REST/GraphQL client for Polymarket quotes and state."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: int,
        retry_attempts: int,
        retry_backoff_seconds: float,
        client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.client = client or httpx.AsyncClient()

    async def fetch_market_status(self, market_id: str) -> dict:
        return await self._get_json(f"/markets/{market_id}")

    async def fetch_orderbook(self, market_id: str) -> dict:
        return await self._get_json(f"/markets/{market_id}/orderbook")

    async def quote_execution(
        self, market_id: str, outcome: OutcomeSide, action: HedgeAction, size_usd: Decimal
    ) -> dict:
        """Estimate execution quality and slippage for a hedge placement."""

        payload = {"market": market_id, "outcome": outcome.value, "action": action.value, "size": float(size_usd)}
        return await self._get_json("/markets/quote", params=payload)

    async def _get_json(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.retry_attempts),
                wait=wait_exponential(multiplier=self.retry_backoff_seconds, min=0.1, max=2),
                retry=retry_if_exception_type(httpx.HTTPError),
            ):
                with attempt:
                    response = await self.client.get(url, timeout=self.timeout_seconds, params=params)
                    response.raise_for_status()
                    log_event(
                        logger,
                        logging.DEBUG,
                        event="polymarket.http",
                        message="fetched polymarket payload",
                        url=url,
                        status=response.status_code,
                        params=params,
                    )
                    return response.json()
        except RetryError as exc:  # pragma: no cover - network failure
            log_event(
                logger,
                logging.ERROR,
                event="polymarket.http.error",
                message="failed to reach polymarket after retries",
                url=url,
                error=str(exc),
            )
            raise
