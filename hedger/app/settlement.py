from __future__ import annotations

import logging
import time

import httpx

from .metrics import PROVER_LATENCY_HISTOGRAM, record_settlement_latency
from .storage import HedgerRepository

logger = logging.getLogger("reveal_market.hedger.settlement")


class SettlementCoordinator:
    """Coordinates prover job submission and contract settlement."""

    def __init__(self, base_url: str, timeout_seconds: int, repository: HedgerRepository | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.repository = repository
        self.client = httpx.AsyncClient()

    async def request_settlement(self, market_id: str, payload: dict) -> dict:
        """Send settlement input to the prover and persist a receipt."""

        started = time.perf_counter()
        response = await self.client.post(
            f"{self.base_url}/prove",
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        latency = time.perf_counter() - started
        PROVER_LATENCY_HISTOGRAM.observe(latency)
        record_settlement_latency(latency)
        data = response.json()
        if self.repository:
            await self.repository.record_settlement(
                market_id=market_id,
                outcome=str(payload.get("outcome")),
                proof_payload=data,
                prover_latency_seconds=int(latency),
                submitted_tx=None,
            )
        logger.info(
            "Prover responded",
            extra={"event": "settlement.prover.response", "market_id": market_id, "latency_seconds": latency},
        )
        return data
