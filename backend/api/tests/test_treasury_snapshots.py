from __future__ import annotations


def test_treasury_snapshots_empty(client):
    response = client.get("/treasury/snapshots")
    assert response.status_code == 200
    assert response.json() == []
