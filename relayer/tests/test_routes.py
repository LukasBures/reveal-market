import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from relayer.app import create_app
from relayer.queue import TxQueue
from relayer.schemas import ClaimRequest, CommitRequest, LockBatchesRequest
from relayer.security import RateLimiter


class FakeService:
    def __init__(self):
        self.commits = []
        self.claims = []
        self.lock_batches_calls = []
        self.account = type("acct", (), {"address": "0xrelayer"})
        self.escrow = type("escrow", (), {"address": "0xescrow"})
        self.health_called = False

    async def commit(self, payload):
        self.commits.append(payload)
        return {"txHash": "0xcommit", "status": 1}

    async def claim(self, payload):
        self.claims.append(payload)
        return {"txHash": "0xclaim", "status": 1}

    async def lock_batches(self, payload):
        self.lock_batches_calls.append(payload)
        return {"txHash": "0xlock", "status": 1}

    async def health(self):
        self.health_called = True
        return {
            "status": "ok",
            "relayer": self.account.address,
            "escrow": self.escrow.address,
            "chainId": 1,
            "rpc": "http://localhost",
            "latestBlock": 1,
            "blockAgeSeconds": 0,
            "relayerBalanceWei": 1,
            "issues": [],
            "connected": True,
            "escrowOwner": self.account.address,
        }

    def validate_commit_payload(self, _payload):
        return None

    def validate_claim_payload(self, _payload):
        return None

    def validate_lock_payload(self, _payload):
        return None


class IngestService(FakeService):
    def __init__(self):
        super().__init__()
        self.commit_ingests: list[dict[str, Any]] = []
        self.settlement_ingests: list[dict[str, Any]] = []

    async def push_commit_ingest(self, payload, *, tx_hash=None):
        self.commit_ingests.append({"payload": payload, "tx_hash": tx_hash})

    async def push_settlement_ingest(self, payload, *, tx_hash=None):
        self.settlement_ingests.append({"payload": payload, "tx_hash": tx_hash})


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
    assert body["escrow"] == "0xescrow"


def test_healthz_includes_queue_stats(tmp_path):
    service = FakeService()
    queue = TxQueue(str(tmp_path / "queue.db"), service, start_worker=False)
    app = create_app(service, 1, "http://localhost", tx_queue=queue)
    client = TestClient(app)

    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["queue"]["enabled"] is True
    assert body["queue"]["depth"] == 0
    assert body["queue"]["deadletter"] == 0
    assert body["queue"]["oldestBacklogAgeSeconds"] is None


def test_metrics(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert b"relayer_request_latency_seconds" in resp.content


def test_commit_route_with_queue(tmp_path):
    service = FakeService()
    queue = TxQueue(str(tmp_path / "queue.db"), service, start_worker=False)
    app = create_app(service, 1, "http://localhost", tx_queue=queue)
    client = TestClient(app)

    payload = CommitRequest(
        user="0x0000000000000000000000000000000000000001",
        market="0x0000000000000000000000000000000000000002",
        commitment="0x" + "0" * 64,
        nonce=1,
        expiry=123,
        chain_id=1,
        ticket_value_wei=1,
        signature="0x" + "1" * 130,
    ).model_dump()
    resp = client.post("/commit", json=payload)
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert "jobId" in body
    assert service.commits == []


def test_claim_route_with_queue(tmp_path):
    service = FakeService()
    queue = TxQueue(str(tmp_path / "queue.db"), service, start_worker=False)
    app = create_app(service, 1, "http://localhost", tx_queue=queue)
    client = TestClient(app)

    payload = ClaimRequest(
        market="0x0000000000000000000000000000000000000002",
        user="0x0000000000000000000000000000000000000001",
        ticket_id=0,
        outcome_id=1,
        amount=10,
        payout=15,
        salt="0x" + "1" * 64,
        merkle_proof=[],
    ).model_dump()
    resp = client.post("/claim", json=payload)
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert "jobId" in body
    assert service.claims == []


def test_admin_deadletter_endpoints(tmp_path):
    service = FakeService()
    queue = TxQueue(str(tmp_path / "queue.db"), service, start_worker=False)
    app = create_app(service, 1, "http://localhost", bearer_token="secret", tx_queue=queue)  # noqa: S106 - test token
    client = TestClient(app)

    job_id = asyncio.run(queue.enqueue("commit", {"foo": "bar"}))
    # mark as deadletter manually
    with queue._connect() as conn:  # noqa: SLF001
        conn.execute("UPDATE jobs SET status = 'deadletter', attempts = 3, last_error = 'boom' WHERE id = ?", (job_id,))

    resp = client.get("/admin/queue/deadletter", headers={"Authorization": "Bearer secret"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["deadletter"][0]["jobId"] == job_id

    resp = client.post(f"/admin/queue/deadletter/{job_id}/replay", headers={"Authorization": "Bearer secret"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"

    resp = client.delete(f"/admin/queue/deadletter/{job_id}", headers={"Authorization": "Bearer secret"})
    assert resp.status_code == 400  # not deadletter anymore


def test_commit_route(client):
    payload = CommitRequest(
        user="0x0000000000000000000000000000000000000001",
        market="0x0000000000000000000000000000000000000002",
        commitment="0x" + "0" * 64,
        nonce=1,
        expiry=123,
        chain_id=1,
        ticket_value_wei=1,
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
        payout=15,
        salt="0x" + "1" * 64,
        merkle_proof=[],
    ).model_dump()
    resp = client.post("/claim", json=payload)
    assert resp.status_code == 200
    assert resp.json()["txHash"] == "0xclaim"


def test_lock_batches_route(client):
    payload = LockBatchesRequest(
        market="0x0000000000000000000000000000000000000002",
        event_id="evt-lock",
        tickets=[
            {
                "ticket_id": 0,
                "outcome_id": 0,
                "amount": 10,
                "payout": 15,
                "user": "0x0000000000000000000000000000000000000001",
                "salt": "0x" + "1" * 64,
            }
        ],
    ).model_dump()
    resp = client.post("/lock-batches", json=payload)
    assert resp.status_code == 200
    assert resp.json()["txHash"] == "0xlock"


def test_lock_batches_route_with_queue(tmp_path):
    service = FakeService()
    queue = TxQueue(str(tmp_path / "queue.db"), service, start_worker=False)
    app = create_app(service, 1, "http://localhost", tx_queue=queue)
    client = TestClient(app)

    payload = LockBatchesRequest(
        market="0x0000000000000000000000000000000000000002",
        event_id="evt-lock",
        tickets=[
            {
                "ticket_id": 0,
                "outcome_id": 0,
                "amount": 10,
                "payout": 15,
                "user": "0x0000000000000000000000000000000000000001",
                "salt": "0x" + "1" * 64,
            }
        ],
    ).model_dump()
    resp = client.post("/lock-batches", json=payload)
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert "jobId" in body
    assert service.lock_batches_calls == []


def test_commit_route_triggers_ingest():
    service = IngestService()
    app = create_app(service, 1, "http://localhost")
    client = TestClient(app)

    payload = CommitRequest(
        user="0x0000000000000000000000000000000000000001",
        market="0x0000000000000000000000000000000000000002",
        commitment="0x" + "0" * 64,
        nonce=1,
        expiry=123,
        chain_id=1,
        ticket_value_wei=1,
        signature="0x" + "1" * 130,
    ).model_dump()

    resp = client.post("/commit", json=payload)
    assert resp.status_code == 200
    assert service.commit_ingests
    assert service.commit_ingests[0]["tx_hash"] == "0xcommit"


def test_claim_route_triggers_ingest():
    service = IngestService()
    app = create_app(service, 1, "http://localhost")
    client = TestClient(app)

    payload = ClaimRequest(
        market="0x0000000000000000000000000000000000000002",
        user="0x0000000000000000000000000000000000000001",
        ticket_id=0,
        outcome_id=1,
        amount=10,
        payout=15,
        salt="0x" + "1" * 64,
        merkle_proof=[],
    ).model_dump()

    resp = client.post("/claim", json=payload)
    assert resp.status_code == 200
    assert service.settlement_ingests
    assert service.settlement_ingests[0]["tx_hash"] == "0xclaim"


def test_lock_batches_route_triggers_ingest():
    service = IngestService()
    app = create_app(service, 1, "http://localhost")
    client = TestClient(app)

    payload = LockBatchesRequest(
        market="0x0000000000000000000000000000000000000002",
        event_id="evt-lock",
        tickets=[
            {
                "ticket_id": 0,
                "outcome_id": 0,
                "amount": 10,
                "payout": 15,
                "user": "0x0000000000000000000000000000000000000001",
                "salt": "0x" + "1" * 64,
            }
        ],
    ).model_dump()
    resp = client.post("/lock-batches", json=payload)
    assert resp.status_code == 200
    assert service.settlement_ingests
    assert service.settlement_ingests[0]["tx_hash"] == "0xlock"


def test_lock_batches_requires_market_identifier(client):
    payload = {
        "market": "0x0000000000000000000000000000000000000002",
        "tickets": [
            {
                "ticket_id": 0,
                "outcome_id": 0,
                "amount": 10,
                "payout": 15,
                "user": "0x0000000000000000000000000000000000000001",
                "salt": "0x" + "1" * 64,
            }
        ],
    }
    resp = client.post("/lock-batches", json=payload)
    assert resp.status_code == 422


def test_commit_requires_auth_when_enabled():
    service = FakeService()
    bearer = "test-token"
    app = create_app(service, 1, "http://localhost", bearer_token=bearer)
    client = TestClient(app)

    payload = CommitRequest(
        user="0x0000000000000000000000000000000000000001",
        market="0x0000000000000000000000000000000000000002",
        commitment="0x" + "0" * 64,
        nonce=1,
        expiry=123,
        chain_id=1,
        ticket_value_wei=1,
        signature="0x" + "1" * 130,
    ).model_dump()

    resp = client.post("/commit", json=payload)
    assert resp.status_code == 401

    resp = client.post("/commit", json=payload, headers={"Authorization": f"Bearer {bearer}"})
    assert resp.status_code == 200
    assert resp.json()["txHash"] == "0xcommit"


def test_claim_requires_auth_when_enabled():
    service = FakeService()
    bearer = "test-token"
    app = create_app(service, 1, "http://localhost", bearer_token=bearer)
    client = TestClient(app)

    payload = ClaimRequest(
        market="0x0000000000000000000000000000000000000002",
        user="0x0000000000000000000000000000000000000001",
        ticket_id=0,
        outcome_id=1,
        amount=10,
        payout=15,
        salt="0x" + "1" * 64,
        merkle_proof=[],
    ).model_dump()

    resp = client.post("/claim", json=payload)
    assert resp.status_code == 401

    resp = client.post("/claim", json=payload, headers={"Authorization": f"Bearer {bearer}"})
    assert resp.status_code == 200
    assert resp.json()["txHash"] == "0xclaim"


def test_status_returns_tx_hash(tmp_path):
    service = FakeService()
    queue = TxQueue(str(tmp_path / "queue.db"), service, start_worker=False)
    app = create_app(service, 1, "http://localhost", tx_queue=queue)
    client = TestClient(app)

    job_id = asyncio.run(queue.enqueue("commit", {"foo": "bar"}))
    with queue._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE jobs SET status = 'succeeded', tx_hash = '0xabc', nonce = 1 WHERE id = ?",
            (job_id,),
        )

    resp = client.post("/status", json={"jobId": job_id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["txHash"] == "0xabc"


def test_status_rejects_invalid_job_id(tmp_path):
    service = FakeService()
    queue = TxQueue(str(tmp_path / "queue.db"), service, start_worker=False)
    app = create_app(service, 1, "http://localhost", tx_queue=queue)
    client = TestClient(app)

    resp = client.post("/status", json={"jobId": "nope"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_job_id"


def test_commit_invalid_address(client):
    payload = CommitRequest(
        user="invalid",
        market="0x0000000000000000000000000000000000000002",
        commitment="0x" + "0" * 64,
        nonce=1,
        expiry=123,
        chain_id=1,
        ticket_value_wei=1,
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
        payout=15,
        salt="0x" + "1" * 64,
        merkle_proof=[],
    ).model_dump()
    resp = client.post("/claim", json=payload)
    assert resp.status_code == 400


def test_metrics_use_route_template_for_params(tmp_path):
    service = FakeService()
    queue = TxQueue(str(tmp_path / "queue.db"), service, start_worker=False)
    app = create_app(service, 1, "http://localhost", bearer_token="secret", tx_queue=queue)  # noqa: S106 - test token
    client = TestClient(app)

    resp = client.post("/admin/queue/deadletter/1/replay", headers={"Authorization": "Bearer secret"})
    assert resp.status_code in (400, 404)

    metrics = client.get("/metrics")
    assert b'endpoint="/admin/queue/deadletter/{job_id}/replay"' in metrics.content


def test_rate_limit_blocks_commit_requests():
    service = FakeService()
    limiter = RateLimiter(1, 60)
    app = create_app(service, 1, "http://localhost", bearer_token="secret", rate_limiter=limiter)  # noqa: S106
    client = TestClient(app)

    payload = CommitRequest(
        user="0x0000000000000000000000000000000000000001",
        market="0x0000000000000000000000000000000000000002",
        commitment="0x" + "0" * 64,
        nonce=1,
        expiry=123,
        chain_id=1,
        ticket_value_wei=1,
        signature="0x" + "1" * 130,
    ).model_dump()
    headers = {"Authorization": "Bearer secret"}

    resp = client.post("/commit", json=payload, headers=headers)
    assert resp.status_code == 200

    resp = client.post("/commit", json=payload, headers=headers)
    assert resp.status_code == 429
