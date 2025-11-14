from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import app.summary_worker as summary_worker
from app.summary_client import SummaryClientError
from app.summary_jobs import SummaryJob
from app.summary_worker import process_job
from shared import cache as shared_cache
from shared.models import Base, Market
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


def _setup_session(monkeypatch):
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(bind=engine)
    test_session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    monkeypatch.setattr(summary_worker, "engine", engine, raising=False)
    monkeypatch.setattr(summary_worker, "SessionLocal", test_session_factory, raising=False)
    return test_session_factory


class DummyRedis:
    def __init__(self):
        self.queues: dict[str, list[str]] = {}

    def rpush(self, key: str, value: str):
        self.queues.setdefault(key, []).append(value)

    def lpush(self, key: str, value: str):
        queue = self.queues.setdefault(key, [])
        queue.insert(0, value)


def test_process_job_persists_summary_and_invalidates_cache(monkeypatch):
    test_session_factory = _setup_session(monkeypatch)
    now = datetime.now(UTC)
    with test_session_factory() as session:
        session.add(
            Market(
                event_id="evt-ai",
                title="AI Summary Market",
                category="finance",
                oracle="0xabc",
                status="commit",
                created_at=now,
                updated_at=now,
                summary_requested_at=now,
            )
        )
        session.commit()

    invalidated = []

    def fake_invalidate(redis_client, tag):
        invalidated.append(tag)
        return []

    monkeypatch.setattr(shared_cache, "invalidate_tag", fake_invalidate, raising=False)

    class StubClient:
        def generate(self, job):
            return SimpleNamespace(
                text="AI generated overview.",
                source="ai_enrichment",
                model="gpt-5.1-mini",
                metadata={"mode": "test"},
                generated_at=now,
            )

    job = SummaryJob(
        job_id="job-1",
        event_id="evt-ai",
        title="AI Summary Market",
        description="Source description",
        category="finance",
        tags=["ai"],
        oracle="0xabc",
    )
    redis_client = DummyRedis()
    assert process_job(job, redis_client, StubClient()) is True

    with test_session_factory() as session:
        stored = session.execute(select(Market).where(Market.event_id == "evt-ai")).scalar_one()
        assert stored.summary == "AI generated overview."
        assert stored.summary_source == "ai_enrichment"
        assert stored.summary_model == "gpt-5.1-mini"
        assert stored.summary_metadata == {"mode": "test"}
        assert stored.summary_requested_at is None
    assert f"market:{job.event_id}" in invalidated
    assert "markets:list" in invalidated


def test_process_job_requeues_on_failure(monkeypatch):
    redis_client = DummyRedis()
    job = SummaryJob(
        job_id="job-2",
        event_id="evt-fail",
        title="Failure",
        description="desc",
        category="finance",
        tags=[],
        oracle=None,
    )

    class FailingClient:
        def generate(self, job):
            raise SummaryClientError("boom")

    monkeypatch.setattr(shared_cache, "invalidate_tag", lambda *args, **kwargs: [], raising=False)
    result = process_job(job, redis_client, FailingClient())
    assert result is False
    assert job.attempts == 1
    queue_entries = redis_client.queues.get(summary_worker.settings.summary_queue_key, [])
    assert len(queue_entries) == 1


def test_process_job_dead_letters_after_max_attempts(monkeypatch):
    redis_client = DummyRedis()
    attempts = summary_worker.settings.summary_retry_max_attempts - 1
    job = SummaryJob(
        job_id="job-dlq",
        event_id="evt-dlq",
        title="Dead Letter",
        description="desc",
        category="finance",
        tags=[],
        oracle=None,
        attempts=attempts,
    )

    class FailingClient:
        def generate(self, job):
            raise SummaryClientError("boom")

    monkeypatch.setattr(shared_cache, "invalidate_tag", lambda *args, **kwargs: [], raising=False)
    result = process_job(job, redis_client, FailingClient())
    assert result is False
    dlq_entries = redis_client.queues.get(summary_worker.settings.summary_dead_letter_key, [])
    assert len(dlq_entries) == 1
