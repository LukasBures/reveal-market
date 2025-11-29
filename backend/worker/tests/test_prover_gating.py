from __future__ import annotations

from app.main import maybe_generate_settlement_proof, settings
from app.polymarket import MarketPayload


def test_maybe_generate_settlement_proof_gated_by_auto_settlement(monkeypatch):
    # Ensure flags gate proof generation even if prover is configured.
    monkeypatch.setattr(settings, "prover_enabled", True, raising=False)
    monkeypatch.setattr(settings, "auto_settlement_enabled", False, raising=False)
    monkeypatch.setattr("app.main.PROVER_CLIENT", object(), raising=False)

    market_snapshot = {"event_id": "evt-1", "id": "1"}
    market_payload = MarketPayload(
        event_id="evt-1",
        title="Test",
        slug="test",
        oracle="polymarket",
        status="commit",
    )

    assert (
        maybe_generate_settlement_proof(
            None, market_snapshot=market_snapshot, market_payload=market_payload, condition_id="0x1"
        )
        is False
    )
