from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app import resolution
from app.polymarket import MarketPayload
from app.runtime import settings


@pytest.mark.asyncio
async def test_fetch_resolution_snapshot_uses_goldsky(monkeypatch):
    # set minimal market payload
    market = MarketPayload(
        event_id="evt-1",
        title="Test market",
        slug="test",
        oracle="polymarket",
        status="commit",
        outcomes=["Yes", "No"],
    )

    class DummyGoldsky:
        def __init__(self):
            self.calls = 0

        def resolution_summary(self, *_args, **_kwargs):
            self.calls += 1
            return {
                "conditionId": "0xabc",
                "resolved": True,
                "outcomes": ["Yes", "No"],
                "payouts": [0, 1],
                "winners": [{"index": 1, "label": "No", "payout": 1}],
                "checkedAt": datetime.now(UTC),
            }

    goldsky = DummyGoldsky()

    monkeypatch.setattr(resolution, "goldsky_client", goldsky, raising=False)
    monkeypatch.setattr(settings, "resolution_fetch_max_attempts", 1, raising=False)

    summary = await resolution._fetch_resolution_snapshot("0xabc", market, None)
    assert summary is not None
    assert goldsky.calls == 1
