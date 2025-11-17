from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from shared.indexers.goldsky import GoldskyClient, GoldskyError


def _build_transport(expected_body: dict, *, status_code: int = 200, request_assertion=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request_assertion:
            request_assertion(request)
        return httpx.Response(status_code=status_code, json=expected_body)

    return httpx.MockTransport(handler)


def test_resolution_summary_parses_payload(monkeypatch):
    timestamp = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
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
    client = GoldskyClient("https://example.com/subgraph", api_key="test-key", transport=transport)

    summary = client.resolution_summary("0xabc", ["YES", "NO"])
    assert summary is not None
    assert summary["source"] == "goldsky_subgraph"
    assert summary["payouts"] == [0, 1]
    assert summary["winners"] == [{"index": 1, "label": "NO", "payout": 1}]
    assert summary["blockNumber"] == 12345
    assert summary["transactionHash"] == "0xdead"
    assert summary["questionId"] == "0x1234"
    assert isinstance(summary["checkedAt"], datetime)
    assert summary["blockTimestamp"] == datetime.fromtimestamp(timestamp, tz=timezone.utc)


def test_resolution_summary_returns_none_when_not_found():
    payload = {"data": {"conditionResolutions": []}}
    transport = _build_transport(payload)
    client = GoldskyClient("https://example.com/subgraph", transport=transport)

    assert client.resolution_summary("0xmissing") is None


def test_resolution_summary_raises_on_graph_errors():
    payload = {"errors": [{"message": "boom"}]}
    transport = _build_transport(payload)
    client = GoldskyClient("https://example.com/subgraph", transport=transport)

    with pytest.raises(GoldskyError):
        client.resolution_summary("0xabc")
