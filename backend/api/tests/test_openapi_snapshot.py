from __future__ import annotations

import json
from pathlib import Path

from app.server import app
from fastapi.testclient import TestClient

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "openapi.json"


def test_openapi_schema_matches_snapshot():
    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    current = response.json()
    assert SNAPSHOT_PATH.exists(), "OpenAPI snapshot missing; regenerate via TestClient(openapi.json)"
    snapshot = json.loads(SNAPSHOT_PATH.read_text())
    assert current == snapshot
