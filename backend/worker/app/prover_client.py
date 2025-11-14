from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
from shared.logging import log_event

logger = logging.getLogger("reveal_market.worker.prover")


@dataclass
class SettlementProofRequest:
    event_id: str
    condition_id: str
    total_pool: str
    winning_pool: str
    outcome_hash: str
    market_address: str
    nonce: str = field(default_factory=lambda: uuid4().hex)
    circuit_version: int = 1
    metadata: dict[str, str] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "condition_id": self.condition_id,
            "total_pool": self.total_pool,
            "winning_pool": self.winning_pool,
            "outcome_hash": self.outcome_hash,
            "market_address": self.market_address,
            "nonce": self.nonce,
            "circuit_version": self.circuit_version,
            "metadata": self.metadata,
        }


@dataclass
class SettlementProofResponse:
    proof: str
    public_signals: list[str]
    circuit_hash: str
    generated_at: datetime
    prover_version: str | None
    request_nonce: str

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
            request_nonce=str(payload.get("request_nonce") or ""),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "proof": self.proof,
            "public_signals": self.public_signals,
            "circuit_hash": self.circuit_hash,
            "generated_at": self.generated_at.isoformat(),
            "prover_version": self.prover_version,
            "request_nonce": self.request_nonce,
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
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    def generate_settlement_proof(self, request: SettlementProofRequest) -> SettlementProofResponse:
        """Submit a proof job and synchronously retrieve the receipt."""

        url = f"{self.base_url}/api/v1/proofs/settlement"
        payload = request.to_payload()
        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self._transport) as client:
                response = client.post(url, json=payload)
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


def compute_outcome_hash(event_id: str, condition_id: str, outcomes: list[str] | None) -> str:
    """Derive a deterministic hash tying the market to outcome strings."""

    basis = "|".join(outcomes or [])
    digest = hashlib.sha512(f"{event_id.lower()}|{condition_id.lower()}|{basis}".encode()).hexdigest()
    return f"0x{digest}"
