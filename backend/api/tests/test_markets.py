from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import app.main as api_main

from app import models


def _make_market(event_id: str, title: str, *, category: str, oracle: str, status: str) -> models.Market:
    now = datetime.now(tz=timezone.utc)
    return models.Market(
        event_id=event_id,
        title=title,
        category=category,
        oracle=oracle,
        status=status,
        created_at=now,
        updated_at=now,
    )


def test_list_markets_supports_filters(client, db_session):
    db_session.add_all(
        [
            _make_market("evt-1", "Alpha Market", category="sports", oracle="0xaaa", status="commit"),
            _make_market("evt-2", "Beta Trade", category="crypto", oracle="0xbbb", status="settled"),
            _make_market("evt-3", "Gamma Alpha", category="sports", oracle="0xaaa", status="commit"),
        ]
    )
    db_session.commit()

    all_markets = client.get("/markets").json()
    assert {m["event_id"] for m in all_markets} == {"evt-1", "evt-2", "evt-3"}

    filtered_status = client.get("/markets", params={"status": "commit"}).json()
    assert {m["event_id"] for m in filtered_status} == {"evt-1", "evt-3"}

    filtered_category = client.get("/markets", params={"category": "crypto"}).json()
    assert [m["event_id"] for m in filtered_category] == ["evt-2"]

    filtered_oracle = client.get("/markets", params={"oracle": "0xaaa"}).json()
    assert {m["event_id"] for m in filtered_oracle} == {"evt-1", "evt-3"}

    filtered_search = client.get("/markets", params={"search": "Alpha"}).json()
    assert {m["event_id"] for m in filtered_search} == {"evt-1", "evt-3"}


def test_create_and_read_market(client):
    payload = {
        "event_id": "evt-100",
        "title": "New Market",
        "category": "sports",
        "oracle": "0xabc123",
        "status": "commit",
    }

    create_response = client.post("/markets", json=payload)
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["event_id"] == payload["event_id"]
    assert created["title"] == payload["title"]
    assert created["status"] == payload["status"]

    read_response = client.get(f"/markets/{payload['event_id']}")
    assert read_response.status_code == 200
    retrieved = read_response.json()
    assert retrieved["event_id"] == payload["event_id"]
    assert retrieved["title"] == payload["title"]


def test_patch_market_and_stats(client, db_session):
    market = _make_market("evt-200", "Patch Me", category="culture", oracle="0xccc", status="commit")
    db_session.add(market)
    db_session.commit()

    patch_payload = {
        "title": "Patched Title",
        "status": "settled",
        "extra_data": {"note": "updated"},
    }

    patch_response = client.patch(f"/markets/{market.event_id}", json=patch_payload)
    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["title"] == "Patched Title"
    assert patched["status"] == "settled"
    assert patched["extra_data"] == {"note": "updated"}

    stats_response = client.get("/markets/stats")
    assert stats_response.status_code == 200
    stats = {entry["status"]: entry["count"] for entry in stats_response.json()}
    assert stats.get("settled") == 1


def test_onchain_markets_unconfigured(client):
    response = client.get("/markets/onchain")
    assert response.status_code == 503


def test_onchain_markets_success(client, monkeypatch):
    async def fake_fetch(settings):
        return ["0x1111111111111111111111111111111111111111"]

    monkeypatch.setattr(api_main, "fetch_factory_markets", fake_fetch)
    monkeypatch.setattr(
        api_main,
        "get_settings",
        lambda: SimpleNamespace(factory_address="0x123", rpc_url="https://unit.test"),
    )

    response = client.get("/markets/onchain")
    assert response.status_code == 200
    assert response.json()["markets"] == ["0x1111111111111111111111111111111111111111"]
