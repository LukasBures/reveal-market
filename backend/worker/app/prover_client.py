from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from httpx import AsyncClient
from shared.logging import log_event

logger = logging.getLogger("reveal_market.worker.prover")


@dataclass
class SettlementProofRequest:
    market_id: str
    merkle_root: str
    winning_outcome_id: int
    pool_totals: list[str]
    total_escrow: str
    total_liability: str
    rake_bps: int
    circuit_hash: str
    batch_index: str
    commitments_count: str
    tickets: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        return {
            "marketId": self.market_id,
            "merkleRoot": self.merkle_root,
            "winningOutcomeId": str(self.winning_outcome_id),
            "poolTotals": self.pool_totals,
            "totalEscrow": self.total_escrow,
            "totalLiability": self.total_liability,
            "rakeBps": str(self.rake_bps),
            "circuitHash": self.circuit_hash,
            "batchIndex": self.batch_index,
            "commitmentsCount": self.commitments_count,
            "tickets": self.tickets,
        }


@dataclass
class SettlementProofResponse:
    proof: str
    public_signals: list[str]
    circuit_hash: str
    generated_at: datetime
    prover_version: str | None
    request_id: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SettlementProofResponse:
        generated_at_raw = payload.get("generated_at")
        generated_at = (
            datetime.fromisoformat(generated_at_raw) if isinstance(generated_at_raw, str) else datetime.now(UTC)
        )
        return cls(
            proof=str(payload.get("proof") or ""),
            public_signals=list(payload.get("public_signals") or []),
            circuit_hash=str(payload.get("circuit_hash") or ""),
            generated_at=generated_at,
            prover_version=payload.get("prover_version"),
            request_id=str(payload.get("request_id") or ""),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "proof": self.proof,
            "public_signals": self.public_signals,
            "circuit_hash": self.circuit_hash,
            "generated_at": self.generated_at.isoformat(),
            "prover_version": self.prover_version,
            "request_id": self.request_id,
        }


class ProverError(RuntimeError):
    """Raised when the prover service rejects a request."""


class ProverClient:
    """HTTP client talking to the dedicated proof generator."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 5.0,
        shared_secret: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.shared_secret = shared_secret
        self._transport = transport

    def _headers(self) -> dict[str, str] | None:
        if self.shared_secret:
            return {"X-Prover-Secret": self.shared_secret}
        return None

    def generate_settlement_proof(self, request: SettlementProofRequest | dict[str, Any]) -> SettlementProofResponse:
        """Submit a proof job and synchronously retrieve the receipt."""

        url = f"{self.base_url}/api/v1/proofs/settlement"
        if isinstance(request, SettlementProofRequest):
            payload = request.to_payload()
        else:
            allowed_fields = {
                "marketId",
                "merkleRoot",
                "winningOutcomeId",
                "poolTotals",
                "totalEscrow",
                "totalLiability",
                "rakeBps",
                "circuitHash",
                "batchIndex",
                "commitmentsCount",
                "tickets",
            }
            payload = {k: v for k, v in request.items() if k in allowed_fields}
        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self._transport) as client:
                response = client.post(url, json=payload, headers=self._headers())
                response.raise_for_status()
        except httpx.HTTPError as exc:
            log_event(
                logger,
                logging.ERROR,
                event="prover.request.failed",
                message="prover rejected settlement proof request",
                error=str(exc),
            )
            raise ProverError("failed to generate proof") from exc
        data = response.json()
        return SettlementProofResponse.from_payload(data)


class AsyncProverClient:
    """Async HTTP client for the proof generator."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 5.0,
        shared_secret: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.shared_secret = shared_secret
        self._transport = transport

    def _headers(self) -> dict[str, str] | None:
        if self.shared_secret:
            return {"X-Prover-Secret": self.shared_secret}
        return None

    async def generate_settlement_proof(
        self, request: SettlementProofRequest | dict[str, Any]
    ) -> SettlementProofResponse:
        url = f"{self.base_url}/api/v1/proofs/settlement"
        if isinstance(request, SettlementProofRequest):
            payload = request.to_payload()
        else:
            allowed_fields = {
                "marketId",
                "merkleRoot",
                "winningOutcomeId",
                "poolTotals",
                "totalEscrow",
                "totalLiability",
                "rakeBps",
                "circuitHash",
                "batchIndex",
                "commitmentsCount",
                "tickets",
            }
            payload = {k: v for k, v in request.items() if k in allowed_fields}
        try:
            async with AsyncClient(timeout=self.timeout_seconds, transport=self._transport) as client:
                response = await client.post(url, json=payload, headers=self._headers())
                response.raise_for_status()
        except httpx.HTTPError as exc:
            log_event(
                logger,
                logging.ERROR,
                event="prover.request.failed",
                message="prover rejected settlement proof request",
                error=str(exc),
            )
            raise ProverError("failed to generate proof") from exc
        data = response.json()
        return SettlementProofResponse.from_payload(data)
