from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app import models
from app.server import settings

_FUTURE = datetime.now(tz=UTC) + timedelta(hours=12)


def test_create_market_requires_event_id(client):
    payload = {
        "title": "Missing Event",
        "category": "sports",
        "oracle": "0xabc",
        "status": "commit",
    }
    response = client.post("/events", json=payload)
    assert response.status_code == 422


def test_patch_missing_market_returns_404(client):
    response = client.patch("/events/does-not-exist", json={"title": "noop"})
    assert response.status_code == 404
    assert response.json()["detail"] == "market_not_found"


def test_search_requires_minimum_length(client):
    response = client.get("/events", params={"search": "a"})
    assert response.status_code == 422


def test_category_limit_validation(client):
    response = client.get("/categories/politics", params={"limit": 0})
    assert response.status_code == 422


def test_suggest_rejects_large_limit(client):
    response = client.get("/events/suggest", params={"q": "alpha", "limit": 100})
    assert response.status_code == 422


def test_default_page_size_respected(client, db_session):
    for idx in range(settings.default_page_size + 5):
        db_session.add(
            models.Market(
                event_id=f"evt-limit-{idx}",
                title=f"Market {idx}",
                category="sports",
                oracle="0xaaa",
                status="commit",
                closes_at=_FUTURE,
            ),
        )
    db_session.commit()

    response = client.get("/events")
    assert response.status_code == 200
    assert len(response.json()) == settings.default_page_size
