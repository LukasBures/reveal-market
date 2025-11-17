from __future__ import annotations

from datetime import UTC, datetime

from app.main import _fetch_resolution_snapshot
from app.polymarket import MarketPayload


def _build_market(condition_id: str = "0x" + "1" * 64) -> MarketPayload:
    return MarketPayload(
        event_id="evt-test",
        title="Test Market",
        slug="test-market",
        category="sports",
        metadata_uri=None,
        oracle="polymarket",
        status="commit",
        outcomes=["Yes", "No"],
        outcome_prices=[0.4, 0.6],
        extra_data={"gamma": {"id": "evt-test"}},
        condition_id=condition_id,
    )


def test_fetch_resolution_snapshot_prefers_goldsky(monkeypatch):
    class GoldskyStub:
        def __init__(self):
            self.called = False

        def resolution_summary(self, condition_id_hex, outcomes, outcome_count_hint):
            self.called = True
            return {
                "source": "goldsky_subgraph",
                "conditionId": condition_id_hex,
                "resolved": True,
                "outcomes": outcomes,
                "payouts": [1, 0],
                "winners": [{"index": 0, "label": outcomes[0], "payout": 1}],
                "checkedAt": datetime.now(UTC),
                "blockNumber": 1,
                "blockTimestamp": datetime.now(UTC),
            }

    class ConditionalTokensStub:
        def resolution_summary(self, *args, **kwargs):
            raise AssertionError("should not use conditional tokens when Goldsky succeeds")

    goldsky_stub = GoldskyStub()
    monkeypatch.setattr("app.main.goldsky_client", goldsky_stub, raising=False)
    monkeypatch.setattr("app.main.conditional_tokens_client", ConditionalTokensStub(), raising=False)

    market = _build_market()
    summary = _fetch_resolution_snapshot(market.condition_id, market, len(market.outcomes))

    assert summary is not None
    assert summary["source"] == "goldsky_subgraph"
    assert goldsky_stub.called is True


def test_fetch_resolution_snapshot_falls_back_to_conditional_tokens(monkeypatch):
    class GoldskyStub:
        def resolution_summary(self, *args, **kwargs):
            return None

    class ConditionalTokensStub:
        def __init__(self):
            self.called = False

        def resolution_summary(self, condition_id_hex, outcomes, outcome_count_hint):
            self.called = True
            return {
                "source": "conditional_tokens",
                "conditionId": condition_id_hex,
                "resolved": True,
                "outcomes": outcomes,
                "payouts": [0, 1],
                "winners": [{"index": 1, "label": outcomes[1], "payout": 1}],
                "checkedAt": datetime.now(UTC),
                "blockNumber": 10,
                "blockTimestamp": datetime.now(UTC),
            }

    conditional_stub = ConditionalTokensStub()
    monkeypatch.setattr("app.main.goldsky_client", GoldskyStub(), raising=False)
    monkeypatch.setattr("app.main.conditional_tokens_client", conditional_stub, raising=False)

    market = _build_market()
    summary = _fetch_resolution_snapshot(market.condition_id, market, len(market.outcomes))

    assert summary is not None
    assert summary["source"] == "conditional_tokens"
    assert conditional_stub.called is True
