from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.admin import router as admin_router
from app.config import Settings
from app.main import create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _DummyRiskEngine:
    def check_limits(self, **_kwargs):
        return []

    def report(self, breaches):
        return {"breaches": breaches}


class _DummyService:
    def __init__(self, *, secret: str | None, read_only: bool = False):
        self.settings = SimpleNamespace(admin_internal_secret=secret, admin_read_only=read_only)
        self.risk_engine = _DummyRiskEngine()
        self.wallet = None

    async def exposures(self):
        return []

    async def ingest_commit(self, commit):
        return {"status": "ok", "market_id": commit.market_id}

    async def trigger_settlement(self, market_id: str, payload: dict):
        return {"status": "ok", "market_id": market_id, "payload": payload}

    async def request_bridge(self, direction: str, amount, destination: str, slippage_bps: int | None = None):
        return {
            "status": "ok",
            "direction": direction,
            "amount": str(amount),
            "destination": destination,
            "slippage_bps": slippage_bps,
        }


def _build_admin_app(*, secret: str | None) -> FastAPI:
    app = FastAPI()
    app.state.service = _DummyService(secret=secret)
    app.include_router(admin_router)
    return app


def test_state_changing_admin_routes_require_internal_secret():
    app = _build_admin_app(secret="top-secret")  # noqa: S106 - test fixture
    client = TestClient(app)

    settlement = client.post("/admin/settlements/mkt-1", json={"winningOutcomeId": "0"})
    assert settlement.status_code == 401
    assert settlement.json()["detail"] == "invalid_internal_secret"

    bridge = client.post("/admin/bridge?direction=usdc_to_zen&amount=1&destination=0xabc")
    assert bridge.status_code == 401
    assert bridge.json()["detail"] == "invalid_internal_secret"


def test_admin_read_routes_require_internal_secret():
    app = _build_admin_app(secret="top-secret")  # noqa: S106 - test fixture
    client = TestClient(app)

    exposures = client.get("/admin/exposures")
    assert exposures.status_code == 401
    assert exposures.json()["detail"] == "invalid_internal_secret"

    risk = client.get("/admin/risk")
    assert risk.status_code == 401
    assert risk.json()["detail"] == "invalid_internal_secret"

    positions = client.get("/admin/positions")
    assert positions.status_code == 401
    assert positions.json()["detail"] == "invalid_internal_secret"

    metrics = client.get("/admin/metrics")
    assert metrics.status_code == 401
    assert metrics.json()["detail"] == "invalid_internal_secret"

    headers = {"X-Internal-Secret": "top-secret"}
    assert client.get("/admin/exposures", headers=headers).status_code == 200
    assert client.get("/admin/risk", headers=headers).status_code == 200
    assert client.get("/admin/positions", headers=headers).status_code == 200
    assert client.get("/admin/metrics", headers=headers).status_code == 200


def test_admin_commits_fail_closed_when_secret_missing():
    app = _build_admin_app(secret=None)
    client = TestClient(app)

    response = client.post(
        "/admin/commits",
        json={"market_id": "mkt-1", "stake_zen": "1", "direction": "yes"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "internal_secret_not_configured"


def test_admin_mutations_accept_valid_internal_secret():
    app = _build_admin_app(secret="top-secret")  # noqa: S106 - test fixture
    client = TestClient(app)
    headers = {"X-Internal-Secret": "top-secret"}

    commit = client.post(
        "/admin/commits",
        json={"market_id": "mkt-1", "stake_zen": "1", "direction": "yes"},
        headers=headers,
    )
    assert commit.status_code == 200
    assert commit.json()["status"] == "ok"

    settlement = client.post(
        "/admin/settlements/mkt-1",
        json={"winningOutcomeId": "0"},
        headers=headers,
    )
    assert settlement.status_code == 200
    assert settlement.json()["status"] == "ok"

    bridge = client.post(
        "/admin/bridge?direction=usdc_to_zen&amount=1&destination=0xabc",
        headers=headers,
    )
    assert bridge.status_code == 200
    assert bridge.json()["status"] == "ok"


def test_create_app_requires_internal_secret_in_non_local_env(monkeypatch):
    settings = Settings(environment="prod", admin_internal_secret=None)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    with pytest.raises(RuntimeError, match="HEDGER_ADMIN_INTERNAL_SECRET"):
        create_app()
