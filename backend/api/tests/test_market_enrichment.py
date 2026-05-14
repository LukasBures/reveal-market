from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import app.server as api_main
from app import models
from shared import models as shared_models
from shared.cache_async import set_json
from shared.cache_keys import market_stats_cache_key, resolution_cache_key
from sqlalchemy import select


def _make_market(event_id: str, title: str, **extra) -> models.Market:
    now = datetime.now(UTC)
    defaults = {
        "category": "finance",
        "oracle": "0xabc",
        "status": "commit",
        "created_at": now,
        "updated_at": now,
        "closes_at": now + timedelta(hours=12),
    }
    defaults.update(extra)
    return models.Market(event_id=event_id, title=title, **defaults)


def test_market_metadata_enrichment_applies_description_and_tokens(client, db_session):
    db_session.add(
        _make_market(
            "evt-meta",
            "Metadata Market",
            category="crypto",
        )
    )
    db_session.flush()
    market_id = db_session.execute(select(models.Market.id).where(models.Market.event_id == "evt-meta")).scalar_one()
    db_session.add_all(
        [
            shared_models.MarketOutcome(market_id=market_id, outcome_id=0, label="Yes", price=0.4),
            shared_models.MarketOutcome(market_id=market_id, outcome_id=1, label="No", price=0.6),
        ]
    )
    db_session.add(shared_models.MarketTag(market_id=market_id, tag="btc"))
    db_session.add_all(
        [
            shared_models.MarketClobToken(market_id=market_id, token_id="A", side="yes"),  # noqa: S106
            shared_models.MarketClobToken(market_id=market_id, token_id="B", side="no"),  # noqa: S106
        ]
    )
    db_session.add(
        shared_models.MarketGammaMetadata(
            market_id=market_id,
            description="Detailed narrative from Polymarket.",
            resolution_source="https://example.com/source",
            clob_token_id_yes="A",  # noqa: S106
            clob_token_id_no="B",  # noqa: S106
            order_price_min_tick_size=Decimal("0.001"),
            order_min_size=Decimal("5"),
        )
    )
    db_session.commit()

    response = client.get("/events", params={"status": "commit"})
    assert response.status_code == 200
    payload = {item["event_id"]: item for item in response.json()}
    enriched = payload["evt-meta"]["markets"][0]
    assert enriched["description"] == "Detailed narrative from Polymarket."
    assert enriched["resolution_source"] == "https://example.com/source"
    assert enriched["clob_token_ids"] == ["A", "B"]


def test_market_stats_cache_overrides_db_values(client, db_session):
    market = _make_market(
        "evt-stats",
        "Stats Market",
        category="news",
        liquidity_usd=10.0,
        volume_24h_usd=5.0,
        orderbook_volume_usd=3.0,
    )
    db_session.add(market)
    db_session.flush()
    db_session.add(
        shared_models.MarketGammaMetadata(
            market_id=market.id,
            best_bid=0.1,
            best_ask=0.2,
            spread=0.1,
            volume=100.0,
        )
    )
    db_session.commit()

    cache_payload = {
        "best_bid": 0.9,
        "best_ask": 0.95,
        "spread": 0.05,
        "volume": 250.0,
        "open_interest": 42.0,
        "liquidity_usd": 99.0,
        "volume_24h_usd": 88.0,
        "orderbook_volume_usd": 77.0,
        "trades_quantity": 12,
    }
    asyncio.run(
        set_json(client.app.cache_client, market_stats_cache_key(market.event_id), cache_payload, ttl_seconds=60)
    )

    response = client.get("/events")
    assert response.status_code == 200
    payload = {item["event_id"]: item for item in response.json()}
    enriched = payload["evt-stats"]["markets"][0]
    assert enriched["best_bid"] == cache_payload["best_bid"]
    assert enriched["best_ask"] == cache_payload["best_ask"]
    assert enriched["spread"] == cache_payload["spread"]
    assert enriched["volume"] == cache_payload["volume"]
    assert enriched["open_interest"] == cache_payload["open_interest"]
    assert enriched["liquidity_usd"] == cache_payload["liquidity_usd"]
    assert enriched["volume_24h_usd"] == cache_payload["volume_24h_usd"]
    assert enriched["orderbook_volume_usd"] == cache_payload["orderbook_volume_usd"]
    assert enriched["trades_quantity"] == cache_payload["trades_quantity"]


def test_category_allowlist_filters_markets(monkeypatch, client, db_session):
    db_session.add_all(
        [
            _make_market(
                "evt-allowed",
                "Allowed Finance",
                category="Finance",
            ),
            _make_market(
                "evt-blocked",
                "Blocked Sports",
                category="Sports",
            ),
        ]
    )
    db_session.commit()

    monkeypatch.setattr(api_main.settings, "market_category_allowlist", ["Finance"], raising=False)

    response = client.get("/events")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["event_id"] == "evt-allowed"


def test_resolution_endpoint_returns_cached_isoformat(client, db_session):
    condition_id = "0x" + "a" * 64
    checked_at = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    block_ts = checked_at + timedelta(hours=1)
    market = _make_market(
        "evt-resolution",
        "Resolution Market",
        condition_id=condition_id.lower(),
    )
    db_session.add(market)
    db_session.flush()
    market_id = db_session.execute(
        select(models.Market.id).where(models.Market.event_id == "evt-resolution")
    ).scalar_one()
    resolution = models.Resolution(
        condition_id=condition_id.lower(),
        event_id="evt-resolution",
        market_id=market_id,
        source="conditional_tokens",
        resolved=True,
        payouts=[0, 1],
        winners=[{"index": 1, "label": "Yes", "payout": 1}],
        oracle="0xfeed",
        question_id="0x" + "b" * 64,
        transaction_hash="0x" + "c" * 64,
        block_number=42,
        block_timestamp=block_ts,
        checked_at=checked_at,
    )
    db_session.add(resolution)
    db_session.flush()
    db_session.add_all(
        [
            shared_models.MarketOutcome(market_id=market_id, outcome_id=0, label="No", price=0.4),
            shared_models.MarketOutcome(market_id=market_id, outcome_id=1, label="Yes", price=0.6),
        ]
    )
    db_session.commit()

    first = client.get(f"/resolution/{condition_id}")
    assert first.status_code == 200
    payload = first.json()
    assert payload["checkedAt"].startswith("2024-01-01T12:00:00")
    assert payload["blockTimestamp"].startswith("2024-01-01T13:00:00")
    cache_key = resolution_cache_key(condition_id.lower())
    assert cache_key in api_main.cache_client.store

    # Remove the DB record to prove the cached payload is used on the second request.
    db_session.delete(resolution)
    db_session.commit()

    second = client.get(f"/resolution/{condition_id}")
    assert second.status_code == 200
    assert second.json() == payload


def test_settlement_statuses_surface_in_market_and_resolution(client, db_session):
    condition_id = "0x" + "b" * 64
    market = _make_market(
        "evt-settlement",
        "Settlement Status",
        category="finance",
        oracle="0xstatus",
        status="settled",
        condition_id=condition_id.lower(),
    )
    db_session.add(market)
    db_session.flush()
    db_session.add(
        models.Resolution(
            condition_id=condition_id.lower(),
            source="conditional_tokens",
            resolved=True,
            payouts=[0, 1],
            winners=[{"index": 1, "label": "Yes", "payout": 1}],
            oracle=market.oracle,
            question_id=condition_id.lower(),
            event_id=market.event_id,
            market_id=market.id,
            checked_at=datetime(2024, 2, 1, 12, 0, tzinfo=UTC),
        )
    )
    settlement = shared_models.Settlement(
        id=1,
        market_id=market.id,
        proof_status=shared_models.SettlementProofStatus.GENERATED.value,
        proof_request_id="req-123",
        proof_hash="0xproof",
        submission_status=shared_models.SettlementSubmissionStatus.QUEUED.value,
        settlement_tx_hash="0xtx",
        settlement_submitted_at=datetime(2024, 2, 1, 12, 0, tzinfo=UTC),
        merkle_root="0xmerkle",
    )
    db_session.add(settlement)
    db_session.commit()

    market_payload = client.get(f"/events/by-key/{market.event_id}").json()
    assert market_payload["markets"][0]["proof_status"] == shared_models.SettlementProofStatus.GENERATED.value
    assert market_payload["markets"][0]["proof_request_id"] == "req-123"
    assert market_payload["markets"][0]["submission_status"] == shared_models.SettlementSubmissionStatus.QUEUED.value
    assert market_payload["markets"][0]["settlement_tx_hash"] == "0xtx"

    resolution_payload = client.get(f"/resolution/{condition_id}").json()
    assert resolution_payload["proofStatus"] == shared_models.SettlementProofStatus.GENERATED.value
    assert resolution_payload["submissionStatus"] == shared_models.SettlementSubmissionStatus.QUEUED.value
    assert resolution_payload["settlementTxHash"] == "0xtx"
