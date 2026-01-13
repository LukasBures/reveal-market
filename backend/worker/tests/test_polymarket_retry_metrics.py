from __future__ import annotations

import httpx
import pytest
from app.polymarket import AsyncPolymarketClient


class DummyCounter:
    def __init__(self):
        self.records: list[dict[str, str]] = []

    def labels(self, outcome: str):
        record = {"outcome": outcome}
        self.records.append(record)

        class _Recorder:
            def __init__(self, target):
                self.target = target

            def inc(self, _amount: float = 1.0):
                return None

        return _Recorder(record)


@pytest.mark.asyncio
async def test_polymarket_retries_record_retry_metrics():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(status_code=500, json={"error": "boom"})
        return httpx.Response(status_code=200, json=[{"id": "1", "question": "ok"}])

    transport = httpx.MockTransport(handler)
    retry_counter = DummyCounter()
    client = AsyncPolymarketClient(
        "https://example.com",
        timeout=1.0,
        transport=transport,
        request_max_attempts=2,
        retry_counter=retry_counter,
    )

    markets = await client.fetch_markets(page_size=1, max_pages=1)
    assert markets
    outcomes = [record["outcome"] for record in retry_counter.records]
    assert "retry" in outcomes
    assert "success" in outcomes
