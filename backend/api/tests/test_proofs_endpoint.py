from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app import models
from shared import models as shared_models
from shared.cache_async import set_json
from shared.cache_keys import proof_receipt_cache_key


def test_list_proof_receipts_returns_records(client, db_session):
    market = models.Market(
        event_id="evt-proof",
        title="Proof Market",
        category="Test",
        oracle="polymarket",
        status="settled",
        condition_id="0xabc",
        market_address="0x123",
    )
    db_session.add(market)
    db_session.commit()

    settlement = shared_models.Settlement(
        id=1,
        market_id=market.id,
        merkle_root="0xroot",
        commitments_count=1,
        pool_total_yes=10,
        pool_total_no=20,
        total_escrow=30,
        total_liability=30,
        rake_bps=50,
        winning_outcome_id=0,
        circuit_hash="0xhash",
        proof_status=shared_models.SettlementProofStatus.GENERATED.value,
        proof_hash="0xproofhash",
    )
    receipt = shared_models.SettlementReceipt(
        id=1,
        market_id=market.id,
        market_address=market.market_address,
        request_id="req-1",
        proof_hash="0xproofhash",
        public_signals=[
            "0xroot",
            str(market.id),
            "0",
            "30",
            "30",
            "50",
            "10",
            "20",
            "0xhash",
            "0",
        ],
        prover_version="v1",
        circuit_hash="0xhash",
        generated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    db_session.add_all([settlement, receipt])
    db_session.commit()

    cache_payload = {
        "proof": "0xproof",
        "public_signals": receipt.public_signals,
        "generated_at": receipt.generated_at.isoformat(),
    }
    asyncio.run(
        set_json(client.app.cache_client, proof_receipt_cache_key(market.condition_id), cache_payload, ttl_seconds=60)
    )

    response = client.get("/proofs?limit=5&offset=0")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1

    payload = body[0]
    assert payload["requestId"] == "req-1"
    assert payload["marketId"] == market.id
    assert payload["conditionId"] == market.condition_id
    assert payload["marketAddress"] == market.market_address
    assert payload["proofHash"] == "0xproofhash"
    assert payload["proof"] == "0xproof"
    assert payload["publicSignals"] == receipt.public_signals
    assert payload["poolTotalYes"] == "10"
    assert payload["poolTotalNo"] == "20"
    assert payload["winningPool"] == "10"
    assert payload["totalPool"] == "30"


def test_list_proof_receipts_filters(client, db_session):
    market_primary = models.Market(
        event_id="evt-proof",
        title="Proof Market",
        category="Test",
        oracle="polymarket",
        status="settled",
        condition_id="0xabc",
        market_address="0x123",
    )
    market_other = models.Market(
        event_id="evt-other",
        title="Other Market",
        category="Test",
        oracle="polymarket",
        status="settled",
        condition_id="0xdef",
        market_address="0x456",
    )
    db_session.add_all([market_primary, market_other])
    db_session.commit()

    receipt_match = shared_models.SettlementReceipt(
        id=1,
        market_id=market_primary.id,
        market_address=market_primary.market_address,
        request_id="req-keep",
        proof_hash="0xproofhash",
        public_signals=["0xroot", str(market_primary.id), "0", "30", "30", "50", "10", "20", "0xhash", "0"],
        prover_version="v1",
        circuit_hash="0xhash",
        generated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    receipt_other = shared_models.SettlementReceipt(
        id=2,
        market_id=market_other.id,
        market_address=market_other.market_address,
        request_id="req-skip",
        proof_hash="0xother",
        public_signals=["0xroot", str(market_other.id), "0", "30", "30", "50", "10", "20", "0xhash", "0"],
        prover_version="v1",
        circuit_hash="0xhash",
        generated_at=datetime(2024, 1, 2, tzinfo=UTC),
    )
    db_session.add_all([receipt_match, receipt_other])
    db_session.commit()

    response = client.get("/proofs?condition_id=0xabc&event_id=evt-proof&request_id=req-keep")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["requestId"] == "req-keep"
    assert body[0]["eventId"] == "evt-proof"
    assert body[0]["conditionId"] == "0xabc"
