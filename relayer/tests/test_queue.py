import asyncio
import json
import time

import pytest
from relayer.queue import TxQueue
from relayer.service import IngestDeliveryError, TxSendError


class DummyService:
    def __init__(self):
        self.commit_calls = 0
        self.claim_calls = 0
        self.last_kwargs = None

    async def commit(self, payload, **kwargs):
        self.commit_calls += 1
        self.last_kwargs = kwargs
        return {"txHash": "0xcommit", "status": 1, "nonce": kwargs.get("nonce_override") or 1}

    async def claim(self, payload, **kwargs):
        self.claim_calls += 1
        return {"txHash": "0xclaim", "status": 1, "nonce": kwargs.get("nonce_override") or 1}


class FlakyService:
    def __init__(self):
        self.commit_calls = 0
        self.bump_factors = []

    async def commit(self, payload, **kwargs):
        self.commit_calls += 1
        self.bump_factors.append(kwargs.get("bump_factor"))
        if self.commit_calls == 1:
            raise TxSendError("first attempt failed", nonce=7)
        return {"txHash": "0xcommit", "status": 1, "nonce": kwargs.get("nonce_override") or 7}

    async def claim(self, payload, **kwargs):
        return {"txHash": "0xclaim", "status": 1, "nonce": kwargs.get("nonce_override") or 1}


class PermanentFailService:
    async def commit(self, payload, **kwargs):
        raise TxSendError("tx_reverted", nonce=1, permanent=True, kind="reverted")

    async def claim(self, payload, **kwargs):
        raise TxSendError("tx_reverted", nonce=1, permanent=True, kind="reverted")


class ExplodingService:
    def __init__(self):
        self.called = asyncio.Event()
        self.tx_timeout_seconds = 1

    async def commit(self, payload, **kwargs):
        self.called.set()
        raise TypeError("boom")


class IngestFailService:
    def __init__(self):
        self.commit_calls = 0

    async def commit(self, payload, **kwargs):
        self.commit_calls += 1
        return {"txHash": "0xcommit", "status": 1, "nonce": kwargs.get("nonce_override") or 1}

    async def push_commit_ingest(self, payload, *, tx_hash=None):
        raise IngestDeliveryError("commit_ingest_http_500")


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
    assert svc.bump_factors == [1.0, pytest.approx(1.15)]


@pytest.mark.asyncio
async def test_queue_uses_nonce_override_on_retry(tmp_path):
    db_path = tmp_path / "queue.db"
    svc = DummyService()
    queue = TxQueue(str(db_path), svc, start_worker=False)

    job_id = await queue.enqueue("commit", {"payload": "x"})
    result = await queue.process_job(job_id)
    assert result["status"] == "succeeded"

    with queue._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE jobs SET status = 'pending', attempts = 1, nonce = 42 WHERE id = ?",
            (job_id,),
        )

    result = await queue.process_job(job_id)
    assert result["status"] == "succeeded"
    assert svc.last_kwargs["nonce_override"] == 42


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


@pytest.mark.asyncio
async def test_queue_deadletters_permanent_error(tmp_path):
    db_path = tmp_path / "queue.db"
    svc = PermanentFailService()
    queue = TxQueue(str(db_path), svc, max_attempts=3, start_worker=False)

    job_id = await queue.enqueue("commit", {"payload": "x"})
    result = await queue.process_job(job_id)
    assert result["status"] == "deadletter"


@pytest.mark.asyncio
async def test_queue_deadletters_when_ingest_fails_after_tx(tmp_path):
    db_path = tmp_path / "queue.db"
    svc = IngestFailService()
    queue = TxQueue(str(db_path), svc, max_attempts=3, start_worker=False)

    job_id = await queue.enqueue("commit", {"payload": "x"})
    result = await queue.process_job(job_id)
    assert result["status"] == "deadletter"
    assert result["txHash"] == "0xcommit"
    with queue._connect() as conn:  # noqa: SLF001
        row = conn.execute("SELECT status, tx_hash FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row is not None
    assert row["status"] == "deadletter"
    assert row["tx_hash"] == "0xcommit"


@pytest.mark.asyncio
async def test_queue_commit_expired_deadletters(tmp_path):
    db_path = tmp_path / "queue.db"
    svc = DummyService()
    queue = TxQueue(str(db_path), svc, start_worker=False)

    job_id = await queue.enqueue("commit", {"expiry": int(time.time()) - 10})
    result = await queue.process_job(job_id)
    assert result["status"] == "deadletter"
    assert result["error"] == "commit_expired"
    assert svc.commit_calls == 0


def test_queue_skips_running_jobs_in_sqlite(tmp_path):
    db_path = tmp_path / "queue.db"
    svc = DummyService()
    queue = TxQueue(str(db_path), svc, start_worker=False)

    job_id = queue._enqueue_sync("commit", {"foo": "bar"})  # noqa: SLF001
    with queue._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE jobs SET status = 'running', updated_at = ? WHERE id = ?",
            (int(time.time()), job_id),
        )

    row = queue._reserve_job_sync()  # noqa: SLF001
    assert row is None


def test_queue_init_preserves_running_jobs(tmp_path):
    db_path = tmp_path / "queue.db"
    svc = DummyService()
    queue = TxQueue(str(db_path), svc, start_worker=False)
    job_id = queue._enqueue_sync("commit", {"foo": "bar"})  # noqa: SLF001
    with queue._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE jobs SET status = 'running', updated_at = ? WHERE id = ?",
            (int(time.time()) - 3600, job_id),
        )
    queue_restarted = TxQueue(str(db_path), svc, start_worker=False)
    with queue_restarted._connect() as conn:  # noqa: SLF001
        row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row is not None
    assert row["status"] == "running"


@pytest.mark.asyncio
async def test_worker_survives_unexpected_error(tmp_path):
    db_path = tmp_path / "queue.db"
    svc = ExplodingService()
    queue = TxQueue(str(db_path), svc, poll_seconds=0.01)

    await queue.start()
    await queue.enqueue("commit", {"payload": "x"})
    await asyncio.wait_for(svc.called.wait(), timeout=1)
    assert queue._worker is not None  # noqa: SLF001
    assert not queue._worker.done()  # noqa: SLF001
    await queue.stop()


@pytest.mark.asyncio
async def test_queue_stats_reports_backlog_and_deadletter(tmp_path):
    db_path = tmp_path / "queue.db"
    svc = DummyService()
    queue = TxQueue(str(db_path), svc, start_worker=False)

    stats = await queue.get_stats()
    assert stats["depth"] == 0
    assert stats["deadletter"] == 0
    assert stats["oldestBacklogAgeSeconds"] is None

    job_id = await queue.enqueue("commit", {"foo": "bar"})
    stats = await queue.get_stats()
    assert stats["depth"] == 1
    assert stats["oldestBacklogAgeSeconds"] is not None

    with queue._connect() as conn:  # noqa: SLF001
        conn.execute("UPDATE jobs SET status = 'deadletter' WHERE id = ?", (job_id,))

    stats = await queue.get_stats()
    assert stats["depth"] == 0
    assert stats["deadletter"] == 1
