from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.onchain import fetch_factory_markets
from shared.onchain import OnChainConfigurationError


class _DummyCall:
    def __init__(self, addresses: list[str]):
        self._addresses = addresses

    async def call(self) -> list[str]:
        return self._addresses


class _DummyFunctions:
    def __init__(self, addresses: list[str]):
        self._addresses = addresses

    def getMarkets(self) -> _DummyCall:
        return _DummyCall(self._addresses)


class _DummyContract:
    def __init__(self, addresses: list[str]):
        self.functions = _DummyFunctions(addresses)


class _DummyEth:
    def __init__(self, addresses: list[str]):
        self._addresses = addresses
        self.contract_calls: list[str] = []

    def contract(self, address: str, abi):
        self.contract_calls.append(address)
        return _DummyContract(self._addresses)


class _DummyWeb3:
    def __init__(self, addresses: list[str]):
        self.eth = _DummyEth(addresses)


@pytest.mark.asyncio
async def test_fetch_factory_markets_returns_addresses(monkeypatch):
    addresses = [
        "0x1111111111111111111111111111111111111111",
        "0x2222222222222222222222222222222222222222",
    ]
    web3 = _DummyWeb3(addresses)
    request_urls: list[str] = []

    def fake_get_async_web3(url: str):
        request_urls.append(url)
        return web3

    checksum_inputs: list[str] = []

    def fake_checksum(value: str) -> str:
        checksum_inputs.append(value)
        return value.upper()

    monkeypatch.setattr("app.onchain.get_async_web3", fake_get_async_web3)
    monkeypatch.setattr("app.onchain.to_checksum", fake_checksum)
    monkeypatch.setattr("app.onchain.log_event", lambda *args, **kwargs: None)

    settings = SimpleNamespace(rpc_url="https://rpc.unit.test", factory_address="0xabcDEF1234")

    result = await fetch_factory_markets(settings)

    assert result == addresses
    assert request_urls == ["https://rpc.unit.test"]
    assert checksum_inputs == ["0xabcDEF1234"]
    assert web3.eth.contract_calls == ["0XABCDEF1234"]


@pytest.mark.asyncio
async def test_fetch_factory_markets_requires_configuration():
    settings = SimpleNamespace(rpc_url=None, factory_address=None)
    with pytest.raises(OnChainConfigurationError):
        await fetch_factory_markets(settings)
