from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from shared.indexers import goldsky as goldsky_module
from shared.indexers.goldsky import AsyncGoldskyClient, GoldskyError


def _build_transport(expected_body: dict, *, status_code: int = 200, request_assertion=None):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request_assertion:
            request_assertion(request)
        return httpx.Response(status_code=status_code, json=expected_body)

    return httpx.MockTransport(handler)


def _build_sequence_transport(expected_bodies: list[dict], *, status_code: int = 200, request_assertion=None):
    responses = list(expected_bodies)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request_assertion:
            request_assertion(request)
        if not responses:
            raise AssertionError("unexpected extra request")
        body = responses.pop(0)
        return httpx.Response(status_code=status_code, json=body)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_resolution_summary_parses_payload(monkeypatch):
    timestamp = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp())
    payload = {
        "data": {
            "conditionResolutions": [
                {
                    "conditionId": "0xabc",
                    "oracle": "0xoracle",
                    "questionId": "0x1234",
                    "payoutNumerators": ["0", "1"],
                    "transactionHash": "0xdead",
                    "blockNumber": "12345",
                    "blockTimestamp": str(timestamp),
                }
            ]
        }
    }

    def assert_headers(request: httpx.Request):
        assert request.headers.get("x-api-key") == "test-key"

    transport = _build_transport(payload, request_assertion=assert_headers)
    client = AsyncGoldskyClient("https://example.com/subgraph", api_key="test-key", transport=transport)

    summary = await client.resolution_summary("0xabc", ["YES", "NO"])
    assert summary is not None
    assert summary["source"] == "goldsky_subgraph"
    assert summary["payouts"] == [0, 1]
    assert summary["winners"] == [{"index": 1, "label": "NO", "payout": 1}]
    assert summary["blockNumber"] == 12345
    assert summary["transactionHash"] == "0xdead"
    assert summary["questionId"] == "0x1234"
    assert isinstance(summary["checkedAt"], datetime)
    assert summary["blockTimestamp"] == datetime.fromtimestamp(timestamp, tz=UTC)
    await client.aclose()


@pytest.mark.asyncio
async def test_resolution_summary_returns_none_when_not_found():
    payload = {"data": {"conditionResolutions": []}}
    transport = _build_transport(payload)
    client = AsyncGoldskyClient("https://example.com/subgraph", transport=transport)

    assert await client.resolution_summary("0xmissing") is None
    await client.aclose()


@pytest.mark.asyncio
async def test_resolution_summary_raises_on_graph_errors():
    payload = {"errors": [{"message": "boom"}]}
    transport = _build_transport(payload)
    client = AsyncGoldskyClient("https://example.com/subgraph", transport=transport)

    with pytest.raises(GoldskyError):
        await client.resolution_summary("0xabc")
    await client.aclose()


@pytest.mark.asyncio
async def test_resolution_summary_falls_back_when_resolution_field_missing():
    payloads = [
        {"errors": [{"message": "Type `Query` has no field `conditionResolutions`"}]},
        {"data": {"condition": {"id": "0xabc", "payoutNumerators": ["1", "0"], "payoutDenominator": "1"}}},
    ]
    transport = _build_sequence_transport(payloads)
    client = AsyncGoldskyClient("https://example.com/subgraph", transport=transport)

    summary = await client.resolution_summary("0xabc", ["YES", "NO"])
    assert summary is not None
    assert summary["resolved"] is True
    assert summary["payouts"] == [1, 0]
    assert summary["winners"] == [{"index": 0, "label": "YES", "payout": 1}]
    await client.aclose()


@pytest.mark.asyncio
async def test_resolution_summary_batch_falls_back_when_resolution_field_missing():
    payloads = [
        {"errors": [{"message": "Type `Query` has no field `conditionResolutions`"}]},
        {
            "data": {
                "c0Cond": {"id": "0xabc", "payoutNumerators": ["0", "1"], "payoutDenominator": "1"},
                "c1Cond": {"id": "0xdef", "payoutNumerators": [], "payoutDenominator": None},
            }
        },
    ]
    transport = _build_sequence_transport(payloads)
    client = AsyncGoldskyClient("https://example.com/subgraph", transport=transport)

    batch = await client.resolution_summary_batch(
        [
            ("0xabc", 2, ["YES", "NO"]),
            ("0xdef", 2, ["YES", "NO"]),
        ]
    )
    assert batch["0xabc"] is not None
    assert batch["0xabc"]["resolved"] is True
    assert batch["0xabc"]["payouts"] == [0, 1]

    # Hint-based payout padding still applies on the fallback path.
    assert batch["0xdef"] is not None
    assert batch["0xdef"]["payouts"] == [0, 0]
    await client.aclose()


@pytest.mark.asyncio
async def test_resolution_summary_failure_logs_are_rate_limited(monkeypatch):
    payload = {"errors": [{"message": "boom"}]}
    transport = _build_transport(payload)
    client = AsyncGoldskyClient("https://example.com/subgraph", transport=transport, max_attempts=1)
    client._failure_log_cooldown_seconds = 3600.0

    recorded_events: list[str] = []

    def _capture_log_event(*args, **kwargs):
        _ = args
        recorded_events.append(kwargs.get("event", ""))

    monkeypatch.setattr(goldsky_module, "log_event", _capture_log_event)

    with pytest.raises(GoldskyError):
        await client.resolution_summary("0xabc")
    with pytest.raises(GoldskyError):
        await client.resolution_summary("0xabc")

    assert recorded_events.count("goldsky.resolution.failed") == 1
    assert recorded_events.count("goldsky.request.failed") == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_resolution_summary_recovery_clears_degraded(monkeypatch):
    payloads = [
        {"errors": [{"message": "boom"}]},
        {"errors": [{"message": "boom"}]},
        {
            "data": {
                "conditionResolutions": [
                    {
                        "conditionId": "0xabc",
                        "oracle": "0xoracle",
                        "questionId": "0x1234",
                        "payoutNumerators": ["1", "0"],
                        "transactionHash": "0xdead",
                        "blockNumber": "12345",
                        "blockTimestamp": "1704067200",
                    }
                ]
            }
        },
    ]
    transport = _build_sequence_transport(payloads)

    gauge_values: list[float] = []

    class _GaugeRecorder:
        def set(self, value: float) -> None:
            gauge_values.append(value)

    monkeypatch.setattr(goldsky_module, "GOLDSKY_DEGRADED_GAUGE", _GaugeRecorder())
    client = AsyncGoldskyClient("https://example.com/subgraph", transport=transport, max_attempts=1)

    with pytest.raises(GoldskyError):
        await client.resolution_summary("0xabc")

    assert client._degraded is True

    summary = await client.resolution_summary("0xabc", ["YES", "NO"])
    assert summary is not None
    assert client._degraded is False
    assert gauge_values[-1] == 0
    assert 1 in gauge_values
    await client.aclose()
