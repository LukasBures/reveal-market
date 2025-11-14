from __future__ import annotations

from datetime import UTC, datetime, timedelta

import app.main as api_main
from app import models
from shared.cache_keys import resolution_cache_key


def _make_market(event_id: str, title: str, **extra) -> models.Market:
    now = datetime.now(UTC)
    defaults = {
        "category": "finance",
        "oracle": "0xabc",
        "status": "commit",
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(extra)
    return models.Market(event_id=event_id, title=title, **defaults)


def test_market_metadata_enrichment_applies_description_and_tokens(client, db_session):
    extra_data = {
        "description": "Detailed narrative from Polymarket.",
        "resolution_source": "https://example.com/source",
        "clob_pair_id": "123",
        "clob_token_ids": ["A", "B"],
    }
    db_session.add(
        _make_market(
            "evt-meta",
            "Metadata Market",
            category="crypto",
            extra_data=extra_data,
            tags=["btc"],
        )
    )
    db_session.commit()

    response = client.get("/markets")
    assert response.status_code == 200
    payload = {item["event_id"]: item for item in response.json()}
    enriched = payload["evt-meta"]
    assert enriched["description"] == "Detailed narrative from Polymarket."
    assert enriched["resolution_source"] == "https://example.com/source"
    assert enriched["clob_pair_id"] == "123"
    assert enriched["clob_token_ids"] == ["A", "B"]


def test_allowlists_filter_markets_by_category_and_tag(monkeypatch, client, db_session):
    db_session.add_all(
        [
            _make_market(
                "evt-allowed",
                "Allowed Finance",
                category="Finance",
                tags=["btc", "macro"],
            ),
            _make_market(
                "evt-blocked",
                "Blocked Sports",
                category="Sports",
                tags=["nba"],
            ),
        ]
    )
    db_session.commit()

    monkeypatch.setattr(api_main.settings, "market_category_allowlist", ["Finance"], raising=False)
    monkeypatch.setattr(api_main.settings, "market_tag_allowlist", ["btc"], raising=False)

    response = client.get("/markets")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["event_id"] == "evt-allowed"


def test_resolution_endpoint_returns_cached_isoformat(client, db_session):
    condition_id = "0x" + "a" * 64
    checked_at = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    block_ts = checked_at + timedelta(hours=1)
    resolution = models.Resolution(
        condition_id=condition_id.lower(),
        source="conditional_tokens",
        resolved=True,
        payouts=[0, 1],
        winners=[{"index": 1, "label": "Yes", "payout": 1}],
        outcomes=["No", "Yes"],
        oracle="0xfeed",
        question_id="0x" + "b" * 64,
        transaction_hash="0x" + "c" * 64,
        block_number=42,
        block_timestamp=block_ts,
        checked_at=checked_at,
    )
    market = _make_market(
        "evt-resolution",
        "Resolution Market",
        condition_id=condition_id.lower(),
        outcomes=["No", "Yes"],
    )
    db_session.add_all([resolution, market])
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
