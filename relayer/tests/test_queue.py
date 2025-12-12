import json

import pytest
from relayer.queue import TxQueue
from relayer.service import TxSendError


class DummyService:
    def __init__(self):
        self.commit_calls = 0
        self.claim_calls = 0

    async def commit(self, payload, **kwargs):
        self.commit_calls += 1
        return {"txHash": "0xcommit", "status": 1, "nonce": kwargs.get("nonce_override") or 1}

    async def claim(self, payload, **kwargs):
        self.claim_calls += 1
        return {"txHash": "0xclaim", "status": 1, "nonce": kwargs.get("nonce_override") or 1}


class FlakyService:
    def __init__(self):
        self.commit_calls = 0

    async def commit(self, payload, **kwargs):
        self.commit_calls += 1
        if self.commit_calls == 1:
            raise TxSendError("first attempt failed", nonce=7)
        return {"txHash": "0xcommit", "status": 1, "nonce": kwargs.get("nonce_override") or 7}

    async def claim(self, payload, **kwargs):
        return {"txHash": "0xclaim", "status": 1, "nonce": kwargs.get("nonce_override") or 1}


@pytest.mark.asyncio
async def test_queue_process_commit(tmp_path):
    db_path = tmp_path / "queue.db"
    svc = DummyService()
    queue = TxQueue(str(db_path), svc, start_worker=False)

    result = await queue.enqueue_and_process("commit", {"foo": "bar"})
    assert result["status"] == "succeeded"
    assert result["txHash"] == "0xcommit"
    assert svc.commit_calls == 1


@pytest.mark.asyncio
async def test_queue_retry_then_succeed(tmp_path):
    db_path = tmp_path / "queue.db"
    svc = FlakyService()
    queue = TxQueue(str(db_path), svc, max_attempts=2, start_worker=False)

    job_id = await queue.enqueue("commit", {"payload": "x"})
    first = await queue.process_job(job_id)
    assert first["status"] == "pending"
    assert svc.commit_calls == 1

    second = await queue.process_job(job_id)
    assert second["status"] == "succeeded"
    assert second["txHash"] == "0xcommit"
    assert svc.commit_calls == 2


@pytest.mark.asyncio
async def test_queue_persists_payload(tmp_path):
    db_path = tmp_path / "queue.db"
    svc = DummyService()
    queue = TxQueue(str(db_path), svc, start_worker=False)

    job_id = await queue.enqueue("claim", {"foo": "bar"})
    with queue._connect() as conn:  # noqa: SLF001
        row = conn.execute("SELECT payload FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row is not None
    assert json.loads(row["payload"]) == {"foo": "bar"}
