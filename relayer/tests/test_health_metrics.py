import asyncio

from relayer.metrics import RPC_ERRORS
from relayer.service import RelayerService


class _FailingFunction:
    def call(self):
        raise ValueError("boom")


class _FailingFunctions:
    def COLLATERAL_TOKEN(self):  # noqa: N802
        return _FailingFunction()

    def owner(self):
        return _FailingFunction()


class _FailingEth:
    def get_block(self, _block):
        raise ValueError("boom")

    def get_balance(self, _address):
        raise ValueError("boom")


class _FailingWeb3:
    def __init__(self):
        self.eth = _FailingEth()

    def is_connected(self):
        raise ValueError("boom")


class _FailingEscrow:
    def __init__(self):
        self.address = "0xescrow"
        self.functions = _FailingFunctions()


class _Account:
    def __init__(self, address: str):
        self.address = address


def test_health_rpc_errors_increment():
    service = RelayerService(
        web3=_FailingWeb3(),
        escrow=_FailingEscrow(),
        account=_Account("0xrelayer"),
        chain_id=1,
        rpc_url="http://rpc",
    )

    before = RPC_ERRORS.labels(label="connection_failed", error_type="ValueError")._value.get()  # noqa: SLF001
    payload = asyncio.run(service.health())
    after = RPC_ERRORS.labels(label="connection_failed", error_type="ValueError")._value.get()  # noqa: SLF001

    assert payload["status"] == "degraded"
    assert after == before + 1
    assert "connection_failed" in payload["issues"]
    assert "block_fetch_failed" in payload["issues"]
    assert "balance_fetch_failed" in payload["issues"]
    assert "token_fetch_failed" in payload["issues"]
    assert "owner_fetch_failed" in payload["issues"]
