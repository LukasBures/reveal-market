from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from eth_abi import encode as abi_encode
from httpx import AsyncClient
from shared.logging import log_event

from . import runtime

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
        proof_calldata = payload.get("proof_calldata")
        proof_args, public_args = _normalize_calldata(proof_calldata)
        proof = _encode_proof_bytes(proof_args) if proof_args else None
        if not proof:
            proof_raw = str(payload.get("proof") or "")
            # Strip NUL padding so DB persistence doesn't fail on invalid UTF-8.
            proof = proof_raw.replace("\x00", "")
        public_signals = payload.get("public_signals") or []
        if not public_signals and public_args:
            public_signals = public_args
        return cls(
            proof=proof,
            public_signals=[str(value) for value in public_signals],
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

    def _headers(self, request_id: str | None = None) -> dict[str, str] | None:
        headers: dict[str, str] = {}
        if self.shared_secret:
            headers["X-Prover-Secret"] = self.shared_secret
        if request_id:
            headers["X-Request-Id"] = request_id
        return headers or None

    def generate_settlement_proof(self, request: SettlementProofRequest | dict[str, Any]) -> SettlementProofResponse:
        """Submit a proof job and synchronously retrieve the receipt.

        .. deprecated::
            This sync method blocks the event loop. Use ``AsyncProverClient.generate_settlement_proof`` instead.
            Kept for backwards-compatible test helpers.
        """

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
                response = client.post(url, json=payload, headers=self._headers(payload.get("request_id")))
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


def _normalize_calldata(proof_calldata: Any) -> tuple[list[str] | None, list[str] | None]:
    if not isinstance(proof_calldata, list) or not proof_calldata:
        return None, None
    if all(isinstance(item, list) for item in proof_calldata):
        proof_args = [str(value) for value in (proof_calldata[0] or [])]
        public_args = [str(value) for value in (proof_calldata[1] or [])] if len(proof_calldata) > 1 else None
        return proof_args, public_args
    if all(isinstance(item, (str, int)) for item in proof_calldata):
        return [str(value) for value in proof_calldata], None
    return None, None


def _encode_proof_bytes(proof_args: list[str] | None) -> str | None:
    if not proof_args or len(proof_args) != 8:
        return None
    try:
        values = [int(value, 0) for value in proof_args]
    except (TypeError, ValueError):
        return None
    a = values[0:2]
    b = [[values[2], values[3]], [values[4], values[5]]]
    c = values[6:8]
    try:
        encoded = abi_encode(["uint256[2]", "uint256[2][2]", "uint256[2]"], [a, b, c])
    except Exception:
        return None
    return f"0x{encoded.hex()}"


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

    def _headers(self, request_id: str | None = None) -> dict[str, str] | None:
        headers: dict[str, str] = {}
        if self.shared_secret:
            headers["X-Prover-Secret"] = self.shared_secret
        if request_id:
            headers["X-Request-Id"] = request_id
        return headers or None

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
            if self._transport is None:
                client = await runtime.get_http_client(self.timeout_seconds)
                response = await client.post(url, json=payload, headers=self._headers(payload.get("request_id")))
            else:
                async with AsyncClient(timeout=self.timeout_seconds, transport=self._transport) as client:
                    response = await client.post(url, json=payload, headers=self._headers(payload.get("request_id")))
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

    async def fetch_health(self) -> dict[str, Any]:
        """Return the prover health payload (used for circuit hash alignment)."""

        url = f"{self.base_url}/healthz"
        try:
            if self._transport is None:
                client = await runtime.get_http_client(self.timeout_seconds)
                response = await client.get(url, headers=self._headers())
            else:
                async with AsyncClient(timeout=self.timeout_seconds, transport=self._transport) as client:
                    response = await client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            log_event(
                logger,
                logging.ERROR,
                event="prover.health.failed",
                message="failed to fetch prover health payload",
                error=str(exc),
            )
            raise ProverError("failed to fetch prover health") from exc
        try:
            payload = response.json()
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                logger,
                logging.ERROR,
                event="prover.health.decode_failed",
                message="failed to decode prover health payload",
                error=str(exc),
            )
            raise ProverError("failed to decode prover health payload") from exc
        if response.status_code >= 400:
            log_event(
                logger,
                logging.WARNING,
                event="prover.health.non_200",
                message="prover health returned non-200 status",
                status=response.status_code,
            )
        payload["_status_code"] = response.status_code
        return payload
