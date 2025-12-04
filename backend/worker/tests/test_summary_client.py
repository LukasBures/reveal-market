from __future__ import annotations

from app.summary_client import SummaryClient
from app.summary_jobs import SummaryJob


def test_summary_client_fallback(monkeypatch):
    client = SummaryClient()
    monkeypatch.setattr(client, "_api_key", None, raising=False)
    monkeypatch.setattr(client.settings, "summary_min_words", 80, raising=False)
    monkeypatch.setattr(client.settings, "summary_max_words", 120, raising=False)
    job = SummaryJob(
        job_id="job-1",
        event_id="evt-1",
        title="Will ZEN break 10k before 2026?",
        description="ZEN faces catalysts like ETF approvals and scaling upgrades.",
        category="crypto",
        tags=["zen", "markets"],
        oracle="polymarket",
    )
    result = client.generate(job)
    assert len(result.text.split()) >= client.settings.summary_min_words
    assert result.model == "fallback-generator"
    assert result.metadata["mode"] == "fallback"
