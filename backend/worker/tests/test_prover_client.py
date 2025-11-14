from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
from app.prover_client import ProverClient, ProverError, SettlementProofRequest


def test_prover_client_success():
    generated_at = datetime.now(UTC).isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["event_id"] == "evt-1"
        return httpx.Response(
            status_code=200,
            json={
                "proof": "0xdeadbeef",
                "public_signals": ["1", "2", "3"],
                "circuit_hash": "0x1234",
                "generated_at": generated_at,
                "prover_version": "test",
                "request_nonce": payload["nonce"],
            },
        )

    transport = httpx.MockTransport(handler)
    client = ProverClient("http://prover", timeout_seconds=2.0, transport=transport)
    request = SettlementProofRequest(
        event_id="evt-1",
        condition_id="0xabc",
        total_pool="100",
        winning_pool="50",
        outcome_hash="0xbeef",
        market_address="0x123",
    )
    response = client.generate_settlement_proof(request)
    assert response.proof == "0xdeadbeef"
    assert response.public_signals == ["1", "2", "3"]
    assert response.circuit_hash == "0x1234"
    assert response.prover_version == "test"
    assert response.request_nonce == request.nonce


def test_prover_client_raises_on_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=500, json={"error": "boom"})

    transport = httpx.MockTransport(handler)
    client = ProverClient("http://prover", timeout_seconds=1.0, transport=transport)
    request = SettlementProofRequest(
        event_id="evt-2",
        condition_id="0xdef",
        total_pool="10",
        winning_pool="5",
        outcome_hash="0xbeef",
        market_address="0x456",
    )
    try:
        client.generate_settlement_proof(request)
    except ProverError:
        return
    raise AssertionError("expected ProverError")
