import pytest
from fastapi.testclient import TestClient
from relayer.app import create_app
from relayer.schemas import ClaimRequest, CommitRequest


class FakeService:
    def __init__(self):
        self.commits = []
        self.claims = []
        self.account = type("acct", (), {"address": "0xrelayer"})
        self.escrow = type("escrow", (), {"address": "0xescrow"})

    def commit(self, payload):
        self.commits.append(payload)
        return {"txHash": "0xcommit", "status": 1}

    def claim(self, payload):
        self.claims.append(payload)
        return {"txHash": "0xclaim", "status": 1}


@pytest.fixture
def client():
    service = FakeService()
    app = create_app(service, 1, "http://localhost")
    return TestClient(app)


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["relayer"] == "0xrelayer"


def test_commit_route(client):
    payload = CommitRequest(
        user="0x0000000000000000000000000000000000000001",
        market="0x0000000000000000000000000000000000000002",
        commitment="0x" + "0" * 64,
        nonce=1,
        expiry=123,
        signature="0x" + "1" * 130,
    ).model_dump()
    resp = client.post("/commit", json=payload)
    assert resp.status_code == 200
    assert resp.json()["txHash"] == "0xcommit"


def test_claim_route(client):
    payload = ClaimRequest(
        market="0x0000000000000000000000000000000000000002",
        user="0x0000000000000000000000000000000000000001",
        ticket_id=0,
        outcome_id=1,
        amount=10,
        salt="0x" + "1" * 64,
        merkle_proof=[],
    ).model_dump()
    resp = client.post("/claim", json=payload)
    assert resp.status_code == 200
    assert resp.json()["txHash"] == "0xclaim"


def test_commit_invalid_address(client):
    payload = CommitRequest(
        user="invalid",
        market="0x0000000000000000000000000000000000000002",
        commitment="0x" + "0" * 64,
        nonce=1,
        expiry=123,
        signature="0x" + "1" * 130,
    ).model_dump()
    resp = client.post("/commit", json=payload)
    assert resp.status_code == 400


def test_claim_invalid_address(client):
    payload = ClaimRequest(
        market="invalid",
        user="0x0000000000000000000000000000000000000001",
        ticket_id=0,
        outcome_id=1,
        amount=10,
        salt="0x" + "1" * 64,
        merkle_proof=[],
    ).model_dump()
    resp = client.post("/claim", json=payload)
    assert resp.status_code == 400
