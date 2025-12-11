from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
from app.prover_client import ProverClient, ProverError, SettlementProofRequest


def test_prover_client_success():
    generated_at = datetime.now(UTC).isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["marketId"] == "0x123"
        assert "tickets" not in payload
        assert "payoutMultiplierWad" not in payload
        return httpx.Response(
            status_code=200,
            json={
                "proof": "0xdeadbeef",
                "public_signals": ["1", "2", "3"],
                "circuit_hash": "0x1234",
                "generated_at": generated_at,
                "prover_version": "test",
                "request_id": "req-1",
            },
        )

    transport = httpx.MockTransport(handler)
    client = ProverClient("http://prover", timeout_seconds=2.0, transport=transport)
    request = SettlementProofRequest(
        market_id="0x123",
        merkle_root="0xroot",
        winning_outcome_id=0,
        pool_totals=["70", "30"],
        total_escrow="100",
        total_liability="90",
        rake_bps=100,
        circuit_hash="0x1234",
    )
    response = client.generate_settlement_proof(request)
    assert response.proof == "0xdeadbeef"
    assert response.public_signals == ["1", "2", "3"]
    assert response.circuit_hash == "0x1234"
    assert response.prover_version == "test"
    assert response.request_id == "req-1"


def test_prover_client_raises_on_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=500, json={"error": "boom"})

    transport = httpx.MockTransport(handler)
    client = ProverClient("http://prover", timeout_seconds=1.0, transport=transport)
    request = SettlementProofRequest(
        market_id="0x123",
        merkle_root="0xroot",
        winning_outcome_id=1,
        pool_totals=["10", "0"],
        total_escrow="10",
        total_liability="10",
        rake_bps=0,
        circuit_hash="0x1234",
    )
    try:
        client.generate_settlement_proof(request)
    except ProverError:
        return
    raise AssertionError("expected ProverError")
