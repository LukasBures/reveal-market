import asyncio
import json
import time
from types import SimpleNamespace

import pytest
from relayer.queue import TxQueue
from relayer.service import IngestDeliveryError, TxSendError


def _stub_web3_account():
    """Return minimal web3/account stubs for queue nonce validation."""
    eth = SimpleNamespace(get_transaction_count=lambda _addr, _block="latest": 0)
    web3 = SimpleNamespace(eth=eth)
    account = SimpleNamespace(address="0x" + "0" * 40)
    return web3, account


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
        self.web3, self.account = _stub_web3_account()

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

    # Enqueue with a valid future expiry, then patch the payload in the DB to
    # simulate a commit that expired between enqueue and processing (the enqueue
    # guard now rejects already-expired commits upfront).
    job_id = await queue.enqueue("commit", {"expiry": int(time.time()) + 600})
    expired_payload = json.dumps({"expiry": int(time.time()) - 10})
    with queue._connect() as conn:  # noqa: SLF001
        conn.execute("UPDATE jobs SET payload = ? WHERE id = ?", (expired_payload, job_id))

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


def test_get_last_stored_nonce_reads_succeeded_jobs(tmp_path):
    db_path = tmp_path / "queue.db"
    svc = DummyService()
    queue = TxQueue(str(db_path), svc, start_worker=False)

    job_id = queue._enqueue_sync("commit", {"foo": "bar"})  # noqa: SLF001
    with queue._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE jobs SET status = 'succeeded', nonce = 7 WHERE id = ?",
            (job_id,),
        )

    assert queue._get_last_stored_nonce() == 7  # noqa: SLF001


@pytest.mark.asyncio
async def test_validate_nonce_on_startup_uses_next_expected_nonce(tmp_path, monkeypatch):
    db_path = tmp_path / "queue.db"
    svc = DummyService()
    svc.web3, svc.account = _stub_web3_account()
    svc.web3.eth.get_transaction_count = lambda _addr, _block="latest": 8
    queue = TxQueue(str(db_path), svc, start_worker=False)

    job_id = queue._enqueue_sync("commit", {"foo": "bar"})  # noqa: SLF001
    with queue._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE jobs SET status = 'succeeded', nonce = 7 WHERE id = ?",
            (job_id,),
        )

    info_calls: list[tuple[str, dict]] = []
    warning_calls: list[tuple[str, dict]] = []

    class StubLogger:
        def info(self, event, **kwargs):
            info_calls.append((event, kwargs))

        def warning(self, event, **kwargs):
            warning_calls.append((event, kwargs))

    monkeypatch.setattr("relayer.queue.logger", StubLogger(), raising=False)

    await queue._validate_nonce_on_startup()  # noqa: SLF001

    assert warning_calls == []
    assert info_calls == [
        (
            "relayer.queue.nonce_validated",
            {
                "on_chain_nonce": 8,
                "stored_nonce": 7,
                "expected_next_nonce": 8,
            },
        )
    ]


def test_queue_reclaims_stale_running_jobs(tmp_path):
    db_path = tmp_path / "queue.db"
    svc = DummyService()
    queue = TxQueue(str(db_path), svc, start_worker=False, running_ttl_seconds=1)
    job_id = queue._enqueue_sync("commit", {"foo": "bar"})  # noqa: SLF001
    stale_time = int(time.time()) - 10
    with queue._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE jobs SET status = 'running', updated_at = ? WHERE id = ?",
            (stale_time, job_id),
        )

    row = queue._reserve_job_sync()  # noqa: SLF001
    assert row is not None
    assert row["id"] == job_id
    with queue._connect() as conn:  # noqa: SLF001
        status_row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert status_row is not None
    assert status_row["status"] == "running"


def test_queue_deadletters_stale_running_with_tx_hash(tmp_path):
    db_path = tmp_path / "queue.db"
    svc = DummyService()
    queue = TxQueue(str(db_path), svc, start_worker=False, running_ttl_seconds=1)
    job_id = queue._enqueue_sync("commit", {"foo": "bar"})  # noqa: SLF001
    stale_time = int(time.time()) - 10
    with queue._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE jobs SET status = 'running', updated_at = ?, tx_hash = ? WHERE id = ?",
            (stale_time, "0xabc", job_id),
        )

    row = queue._reserve_job_sync()  # noqa: SLF001
    assert row is None
    with queue._connect() as conn:  # noqa: SLF001
        status_row = conn.execute("SELECT status, last_error FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert status_row is not None
    assert status_row["status"] == "deadletter"
    assert status_row["last_error"] == "stale_running_with_tx_hash"


def test_queue_prunes_stale_deadletter_jobs(tmp_path):
    db_path = tmp_path / "queue.db"
    svc = DummyService()
    queue = TxQueue(str(db_path), svc, start_worker=False, deadletter_retention_seconds=60)
    old_job_id = queue._enqueue_sync("claim", {"foo": "old"})  # noqa: SLF001
    fresh_job_id = queue._enqueue_sync("claim", {"foo": "fresh"})  # noqa: SLF001
    stale_time = int(time.time()) - 120
    recent_time = int(time.time()) - 10
    with queue._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE jobs SET status = 'deadletter', updated_at = ? WHERE id = ?",
            (stale_time, old_job_id),
        )
        conn.execute(
            "UPDATE jobs SET status = 'deadletter', updated_at = ? WHERE id = ?",
            (recent_time, fresh_job_id),
        )

    restarted = TxQueue(str(db_path), svc, start_worker=False, deadletter_retention_seconds=60)

    with restarted._connect() as conn:  # noqa: SLF001
        rows = conn.execute("SELECT id, status FROM jobs ORDER BY id").fetchall()

    assert [(row["id"], row["status"]) for row in rows] == [(fresh_job_id, "deadletter")]


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
