from __future__ import annotations

from typing import Any

import pytest
from app import backfill
from app.backfill import backfill_market_params
from shared.onchain.abi import MARKET_FACTORY_ABI, RELAYER_ESCROW_ABI, REVEAL_MARKET_ABI


class DummySession:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flushes = 0

    def add(self, market: Any) -> None:
        self.added.append(market)

    async def flush(self) -> None:
        self.flushes += 1


class DummyMarket:
    def __init__(self, *, event_id: str, market_address: str | None, onchain_market_id: int | None) -> None:
        self.event_id = event_id
        self.market_address = market_address
        self.onchain_market_id = onchain_market_id
        self.factory: str | None = None
        self.rake_bps: int | None = None


class DummyCall:
    def __init__(self, result: Any = None, exc: Exception | None = None) -> None:
        self._result = result
        self._exc = exc

    async def call(self) -> Any:
        if self._exc is not None:
            raise self._exc
        return self._result


class DummyMarketFunctions:
    """Test double that mirrors the Web3 ABI method names."""

    def __init__(self, market_id: int | None = None, exc: Exception | None = None) -> None:
        self._market_id = market_id
        self._exc = exc

    def marketId(self) -> DummyCall:  # noqa: N802
        return DummyCall(result=self._market_id, exc=self._exc)


class DummyFactoryFunctions:
    """Test double that mirrors the Web3 ABI method names."""

    def __init__(self, params: tuple[Any, ...] | None = None, exc: Exception | None = None) -> None:
        self._params = params
        self._exc = exc

    def getMarketParams(self, _market_id: int) -> DummyCall:  # noqa: N802
        return DummyCall(result=self._params, exc=self._exc)


class DummyContract:
    def __init__(self, functions: Any) -> None:
        self.functions = functions


class DummyEth:
    def __init__(self, factory: DummyContract, market: DummyContract) -> None:
        self._factory = factory
        self._market = market

    def contract(self, *, address: str | None = None, abi: Any | None = None) -> DummyContract:
        if abi is MARKET_FACTORY_ABI:
            return self._factory
        if abi is REVEAL_MARKET_ABI:
            return self._market
        raise AssertionError("unexpected abi")


class DummyWeb3:
    def __init__(self, factory: DummyContract, market: DummyContract) -> None:
        self.eth = DummyEth(factory, market)


def test_reveal_market_abi_exposes_protocol_liability_cap_getter() -> None:
    reveal_market_names = {entry["name"] for entry in REVEAL_MARKET_ABI if entry.get("type") == "function"}
    relayer_escrow_names = {entry["name"] for entry in RELAYER_ESCROW_ABI if entry.get("type") == "function"}

    assert "protocolLiabilityCap" in reveal_market_names
    assert "protocolLiabilityCap" not in relayer_escrow_names


@pytest.mark.asyncio
async def test_backfill_market_params_updates_missing_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    session = DummySession()
    market = DummyMarket(event_id="evt-1", market_address="0xabc", onchain_market_id=None)

    async def get_markets_for_sync(_session, limit=None):
        return [market]

    params = [None] * 10
    params[0] = "0xabc"
    params[9] = 25
    factory = DummyContract(DummyFactoryFunctions(params=tuple(params)))
    contract = DummyContract(DummyMarketFunctions(market_id=7))

    monkeypatch.setattr(backfill, "get_async_web3", lambda _rpc: DummyWeb3(factory, contract))
    monkeypatch.setattr(backfill, "to_checksum", lambda value: value)

    count = await backfill_market_params(
        session,
        rpc_url="http://rpc",
        factory_address="0xfactory",
        get_markets_for_sync=get_markets_for_sync,
        limit=None,
    )

    assert count == 1
    assert market.onchain_market_id == 7
    assert market.market_address == "0xabc"
    assert market.factory == "0xfactory"
    assert market.rake_bps == 25
    assert session.added == [market]
    assert session.flushes == 1


@pytest.mark.asyncio
async def test_backfill_market_params_handles_factory_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    session = DummySession()
    market = DummyMarket(event_id="evt-2", market_address="0xdef", onchain_market_id=5)

    async def get_markets_for_sync(_session, limit=None):
        return [market]

    factory = DummyContract(DummyFactoryFunctions(exc=RuntimeError("boom")))
    contract = DummyContract(DummyMarketFunctions(market_id=5))

    monkeypatch.setattr(backfill, "get_async_web3", lambda _rpc: DummyWeb3(factory, contract))
    monkeypatch.setattr(backfill, "to_checksum", lambda value: value)

    count = await backfill_market_params(
        session,
        rpc_url="http://rpc",
        factory_address="0xfactory",
        get_markets_for_sync=get_markets_for_sync,
        limit=None,
    )

    assert count == 0
    assert market.onchain_market_id == 5
    assert market.factory is None
    assert market.rake_bps is None
    assert session.added == []
    assert session.flushes == 0
