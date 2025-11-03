from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import app.main as api_main

from app import models


def _make_market(
    event_id: str,
    title: str,
    *,
    category: str,
    oracle: str,
    status: str,
    rake_bps: int | None = None,
) -> models.Market:
    now = datetime.now(tz=timezone.utc)
    return models.Market(
        event_id=event_id,
        title=title,
        category=category,
        oracle=oracle,
        status=status,
        rake_bps=rake_bps,
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
    assert created["rake_bps"] is None

    read_response = client.get(f"/markets/{payload['event_id']}")
    assert read_response.status_code == 200
    retrieved = read_response.json()
    assert retrieved["event_id"] == payload["event_id"]
    assert retrieved["title"] == payload["title"]
    assert retrieved["rake_bps"] is None


def test_create_market_with_rake(client):
    payload = {
        "event_id": "evt-101",
        "title": "Custom Rake",
        "category": "sports",
        "oracle": "0xabc123",
        "status": "commit",
        "rake_bps": 75,
    }

    response = client.post("/markets", json=payload)
    assert response.status_code == 201
    created = response.json()
    assert created["rake_bps"] == 75

    fetched = client.get(f"/markets/{payload['event_id']}").json()
    assert fetched["rake_bps"] == 75


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
    assert patched["rake_bps"] is None

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


def test_resolution_endpoint_unconfigured(client):
    response = client.get("/resolution/0xabc")
    assert response.status_code == 503


def test_resolution_endpoint_returns_summary(client, db_session, monkeypatch):
    market = _make_market(
        "evt-300",
        "Resolved Market",
        category="news",
        oracle="0xabc",
        status="commit",
    )
    market.condition_id = "0x1111111111111111111111111111111111111111111111111111111111111111"
    market.outcomes = ["Yes", "No"]
    market.outcome_prices = [0.45, 0.55]
    db_session.add(market)
    db_session.commit()

    from datetime import datetime, timezone

    class FakeClient:
        def __init__(self):
            self.calls = []

        def resolution_summary(self, condition_id_hex, outcomes, outcome_count_hint):
            self.calls.append((condition_id_hex, outcomes, outcome_count_hint))
            return {
                "source": "conditional_tokens",
                "conditionId": condition_id_hex,
                "resolved": True,
                "outcomes": outcomes,
                "payouts": [0, 1],
                "winners": [{"index": 1, "label": "No", "payout": 1}],
                "checkedAt": datetime.now(timezone.utc).isoformat(),
            }

    fake_client = FakeClient()

    def fake_get_settings():
        base = api_main.settings
        base.polygon_rpc_url = "https://unit.test"
        base.conditional_tokens_address = "0x2222222222222222222222222222222222222222"
        return base

    monkeypatch.setattr(api_main, "_resolution_client", fake_client, raising=False)
    monkeypatch.setattr(api_main, "get_settings", fake_get_settings, raising=False)

    response = client.get(f"/resolution/{market.condition_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["resolved"] is True
    assert payload["winners"] == [{"index": 1, "label": "No", "payout": 1}]
    assert payload["marketId"] == market.id
    assert payload["eventId"] == market.event_id
    assert payload["title"] == market.title
    assert fake_client.calls == [
        (
            market.condition_id,
            ["Yes", "No"],
            2,
        )
    ]

    # second call should be served from cache
    cached = client.get(f"/resolution/{market.condition_id}")
    assert cached.status_code == 200
    assert len(fake_client.calls) == 1
