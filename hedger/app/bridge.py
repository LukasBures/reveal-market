from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import httpx
from tenacity import AsyncRetrying, RetryError, retry_if_exception_type, stop_after_attempt, wait_exponential

from .local_logging import log_event

logger = logging.getLogger("reveal_market.hedger.bridge")


class BridgeClient:
    """
    Minimal bridge client used to move liquidity between USDC and ZEN rails.

    The API contract is intentionally lightweight: submit a direction + amount with an optional idempotency key.
    Retries should not create duplicate transfers. Production operators should front this with auth and rate limits.
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: int = 15,
        retry_attempts: int = 3,
        retry_backoff_seconds: float = 0.5,
        client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.client = client or httpx.AsyncClient()

    async def bridge_to_zen(
        self, amount_usdc: Decimal, destination: str, *, slippage_bps: int, idempotency: str | None
    ):
        return await self._submit(
            {
                "direction": "usdc_to_zen",
                "amount": str(amount_usdc),
                "destination": destination,
                "max_slippage_bps": slippage_bps,
            },
            idempotency=idempotency,
        )

    async def bridge_to_usdc(
        self, amount_zen: Decimal, destination: str, *, slippage_bps: int, idempotency: str | None
    ):
        return await self._submit(
            {
                "direction": "zen_to_usdc",
                "amount": str(amount_zen),
                "destination": destination,
                "max_slippage_bps": slippage_bps,
            },
            idempotency=idempotency,
        )

    async def _submit(self, payload: dict[str, Any], *, idempotency: str | None) -> dict:
        url = self.base_url if self.base_url.endswith("/submit") else f"{self.base_url}/submit"
        headers = {}
        if idempotency:
            headers["Idempotency-Key"] = idempotency
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.retry_attempts),
                wait=wait_exponential(multiplier=self.retry_backoff_seconds, min=0.1, max=2),
                retry=retry_if_exception_type(httpx.HTTPError),
            ):
                with attempt:
                    response = await self.client.post(url, json=payload, headers=headers, timeout=self.timeout_seconds)
                    response.raise_for_status()
                    log_event(
                        logger,
                        logging.INFO,
                        event="bridge.submit",
                        message="bridge transfer submitted",
                        payload=payload,
                        status=response.status_code,
                        idempotency=idempotency,
                    )
                    return response.json()
        except RetryError as exc:  # pragma: no cover - network failure path
            log_event(
                logger,
                logging.ERROR,
                event="bridge.submit.failed",
                message="bridge submission failed after retries",
                payload=payload,
                error=str(exc),
                idempotency=idempotency,
            )
            raise
        raise RuntimeError("bridge submission failed")
