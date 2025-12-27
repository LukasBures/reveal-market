from __future__ import annotations

import pytest
from app import proofs
from app.polymarket import MarketPayload

pytestmark = pytest.mark.asyncio


async def test_maybe_generate_settlement_proof_requires_client(monkeypatch):
    # Proof generation should skip when the prover client is unavailable.
    monkeypatch.setattr(proofs.runtime, "PROVER_CLIENT", None, raising=False)

    market_snapshot = {"event_id": "evt-1", "id": "1"}
    market_payload = MarketPayload(
        event_id="evt-1",
        title="Test",
        slug="test",
        oracle="polymarket",
        status="commit",
    )

    assert (
        await proofs.maybe_generate_settlement_proof(
            None, market_snapshot=market_snapshot, market_payload=market_payload, condition_id="0x1"
        )
        is False
    )
