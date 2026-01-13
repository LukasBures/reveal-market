from __future__ import annotations

import threading

import pytest
from relayer.queue import TxQueue


class DummyService:
    def __init__(self):
        self.tx_timeout_seconds = 5


class FakeCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class FakeConnection:
    def __init__(self, jobs):
        self.jobs = jobs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        if query.strip().startswith("SELECT status"):
            job_id = params[0]
            job = self.jobs.get(job_id)
            return FakeCursor({"status": job["status"]} if job else None)
        if query.strip().startswith("UPDATE jobs") and "SET status = 'pending'" in query:
            if params is None:
                return FakeCursor(None)
            job_id = params[1]
            job = self.jobs[job_id]
            job["status"] = "pending"
            job["attempts"] = 0
            job["last_error"] = None
            return FakeCursor({"id": job_id})
        return FakeCursor(None)


@pytest.mark.asyncio
async def test_replay_deadletter_postgres_backend(monkeypatch):
    jobs = {1: {"status": "deadletter", "attempts": 3, "last_error": "boom"}}

    def _connect_pg():
        return FakeConnection(jobs)

    monkeypatch.setattr(TxQueue, "_connect_pg", staticmethod(_connect_pg))
    monkeypatch.setattr(TxQueue, "_connect", staticmethod(_connect_pg))
    queue = TxQueue("unused", DummyService(), dsn="postgres://", start_worker=False)
    queue._lock = threading.Lock()

    result = await queue.replay_job(1)
    assert result["status"] == "pending"
    assert jobs[1]["status"] == "pending"
