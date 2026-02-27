from __future__ import annotations

import asyncio

from relayer.service import RelayerService
from web3.exceptions import Web3Exception


class _TimeoutEth:
    def get_block(self, _block):
        raise Web3Exception("timeout")

    def get_balance(self, _address):
        raise Web3Exception("timeout")

    def get_transaction_count(self, _address, _block="latest"):
        raise Web3Exception("timeout")


class _TimeoutFunctions:
    def COLLATERAL_TOKEN(self):  # noqa: N802
        return self

    def owner(self):
        return self

    def call(self):
        raise Web3Exception("timeout")


class _TimeoutWeb3:
    def __init__(self):
        self.eth = _TimeoutEth()

    def is_connected(self):
        raise Web3Exception("timeout")


class _Escrow:
    def __init__(self):
        self.address = "0xescrow"
        self.functions = _TimeoutFunctions()


class _Account:
    def __init__(self, address: str):
        self.address = address


def test_health_logs_elapsed_for_web3_errors(capsys):
    service = RelayerService(
        web3=_TimeoutWeb3(),
        escrow=_Escrow(),
        account=_Account("0xrelayer"),
        chain_id=1,
        rpc_url="http://rpc",
    )

    asyncio.run(service.health())
    captured = capsys.readouterr()
    assert "duration_ms=" in captured.out
