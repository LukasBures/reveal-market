from __future__ import annotations

import json

import httpx
import pytest
from app.config import Settings
from app.subgraph import SubgraphClient, SubgraphNotConfiguredError


@pytest.mark.asyncio
async def test_subgraph_client_executes_queries():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content.decode())
        assert payload["variables"]["marketId"] == "m1"
        return httpx.Response(200, json={"data": {"marketOpenInterests": [{"id": "oi1"}]}})

    transport = httpx.MockTransport(handler)
    settings = Settings(
        subgraph_default_url="https://example.com/subgraph",
        subgraph_open_interest_url="https://example.com/subgraph",
    )
    client = SubgraphClient(settings, transport=transport)

    records = await client.fetch_open_interest(market_id="m1", first=2, skip=1)
    assert records == [{"id": "oi1"}]
    assert requests, "request not sent"


@pytest.mark.asyncio
async def test_subgraph_requires_endpoint():
    settings = Settings(
        subgraph_default_url=None,
        subgraph_markets_url=None,
        subgraph_trades_url=None,
        subgraph_positions_url=None,
        subgraph_open_interest_url=None,
        subgraph_pnl_url=None,
    )
    client = SubgraphClient(settings)
    with pytest.raises(SubgraphNotConfiguredError):
        await client.fetch_markets()
