from __future__ import annotations

import pytest
from app import resolution
from app.polymarket import MarketPayload
from app.runtime import settings


@pytest.mark.asyncio
async def test_fetch_resolution_snapshot_falls_back_to_conditional(monkeypatch):
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
            return None

    class DummyConditional:
        def __init__(self):
            self.calls = 0

        def resolution_summary(self, *_args, **_kwargs):
            self.calls += 1
            return {"conditionId": "0xabc", "resolved": True}

    goldsky = DummyGoldsky()
    conditional = DummyConditional()

    monkeypatch.setattr(resolution, "goldsky_client", goldsky, raising=False)
    monkeypatch.setattr(resolution, "conditional_tokens_client", conditional, raising=False)
    monkeypatch.setattr(settings, "resolution_fetch_max_attempts", 1, raising=False)

    summary = await resolution._fetch_resolution_snapshot("0xabc", market, None)
    assert summary is not None
    assert summary["conditionId"] == "0xabc"
    assert conditional.calls == 1
