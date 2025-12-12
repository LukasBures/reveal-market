from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app import summary_jobs
from app.polymarket import MarketPayload
from app.summary_jobs import SummaryJob, maybe_enqueue_summary_job


class QueueRecorder:
    def __init__(self):
        self.items: list[tuple[str, str]] = []

    async def lpush(self, key: str, value: str):
        self.items.append((key, value))


def build_payload(description: str = "Example description"):
    return MarketPayload(
        event_id="evt-summary",
        title="Will BTC hit a new ATH before 2025?",
        slug="btc-ath",
        category="crypto",
        metadata_uri=None,
        oracle="polymarket",
        status="commit",
        gamma_metadata={"description": description},
    )


def build_market(summary=None, requested_at=None, checked_at=None):
    return SimpleNamespace(
        event_id="evt-summary",
        title="Will BTC hit a new ATH before 2025?",
        category="crypto",
        tags=["btc", "markets"],
        oracle="polymarket",
        summary=summary,
        summary_requested_at=requested_at,
        summary_checked_at=checked_at,
    )


@pytest.mark.asyncio
async def test_summary_job_enqueued_when_missing_summary(monkeypatch):
    redis = QueueRecorder()
    market_record = build_market()
    payload = build_payload()
    monkeypatch.setattr(summary_jobs.settings, "summary_enabled", True, raising=False)
    enqueued = await maybe_enqueue_summary_job(redis, market_record=market_record, market_payload=payload)
    assert enqueued is True
    assert len(redis.items) == 1
    key, payload_json = redis.items[0]
    assert key == summary_jobs.settings.summary_queue_key
    job = SummaryJob.from_json(payload_json)
    assert job.event_id == market_record.event_id
    assert job.description == payload.gamma_metadata["description"]
    assert market_record.summary_requested_at is not None


@pytest.mark.asyncio
async def test_summary_job_serializes_datetime_metadata(monkeypatch):
    redis = QueueRecorder()
    market_record = build_market()
    payload = build_payload()
    naive_dt = datetime(2024, 1, 2, 3, 4, 5)  # naive to ensure UTC coercion
    payload.gamma_metadata["start_date"] = naive_dt
    monkeypatch.setattr(summary_jobs.settings, "summary_enabled", True, raising=False)

    enqueued = await maybe_enqueue_summary_job(redis, market_record=market_record, market_payload=payload)

    assert enqueued is True
    _, payload_json = redis.items[0]
    job = SummaryJob.from_json(payload_json)
    start_date = job.metadata["gamma_metadata"]["start_date"]
    assert start_date == naive_dt.replace(tzinfo=UTC).isoformat()


@pytest.mark.asyncio
async def test_summary_job_skipped_when_recent_request(monkeypatch):
    redis = QueueRecorder()
    now = datetime.now(UTC)
    market_record = build_market(requested_at=now)
    payload = build_payload()
    monkeypatch.setattr(summary_jobs.settings, "summary_enabled", True, raising=False)
    enqueued = await maybe_enqueue_summary_job(redis, market_record=market_record, market_payload=payload)
    assert enqueued is False
    assert len(redis.items) == 0


@pytest.mark.asyncio
async def test_summary_job_refreshes_when_stale(monkeypatch):
    redis = QueueRecorder()
    old = datetime.now(UTC) - timedelta(days=10)
    market_record = build_market(summary="old summary", checked_at=old, requested_at=None)
    payload = build_payload()
    monkeypatch.setattr(summary_jobs.settings, "summary_enabled", True, raising=False)
    monkeypatch.setattr(summary_jobs.settings, "summary_refresh_interval_seconds", 24 * 3600, raising=False)
    enqueued = await maybe_enqueue_summary_job(redis, market_record=market_record, market_payload=payload)
    assert enqueued is True
    assert len(redis.items) == 1
