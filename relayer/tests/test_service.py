from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest
from relayer.service import RelayerService, TxSendError
from web3 import Web3


class DummyEth:
    def __init__(self, receipt_status: int):
        self.receipt_status = receipt_status

    def get_transaction_receipt(self, _tx_hash):
        return {"status": self.receipt_status}


class DummyWeb3:
    def __init__(self, receipt_status: int = 1):
        self.eth = DummyEth(receipt_status)

    def to_checksum_address(self, address: str) -> str:
        return Web3.to_checksum_address(address)


class DummyEscrowCall:
    def build_transaction(self, base_tx):
        tx = dict(base_tx)
        tx["to"] = "0x0000000000000000000000000000000000000002"
        return tx


class DummyEscrow:
    def __init__(self):
        self.functions = self

    def commit_on_behalf(self, *_args, **_kwargs):
        return DummyEscrowCall()

    def __getattr__(self, name: str):
        if name == "commitOnBehalf":
            return self.commit_on_behalf
        raise AttributeError(name)


class LockingService(RelayerService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.active = 0
        self.max_active = 0

    async def _build_base_tx(self, value: int = 0, nonce_override: int | None = None, bump_factor: float = 1.0):
        return {
            "from": "0x0000000000000000000000000000000000000001",
            "nonce": 1 if nonce_override is None else nonce_override,
            "value": value,
            "chainId": self.chain_id,
        }

    async def _send_and_wait(self, tx, _action):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.02)
        self.active -= 1
        return {"txHash": "0xabc", "status": 1, "nonce": tx["nonce"]}


@pytest.mark.asyncio
async def test_poll_receipt_revert_marks_permanent():
    service = RelayerService(
        web3=DummyWeb3(receipt_status=0),
        escrow=SimpleNamespace(address="0xescrow"),
        account=SimpleNamespace(address="0xrelayer"),
        chain_id=1,
        rpc_url="http://localhost",
    )

    with pytest.raises(TxSendError) as exc:
        await service._poll_receipt(b"\x01", "commit", 1, time.perf_counter(), attempt=1)

    assert exc.value.permanent is True
    assert exc.value.kind == "reverted"


@pytest.mark.asyncio
async def test_commit_serializes_nonce_lock():
    service = LockingService(
        web3=DummyWeb3(),
        escrow=DummyEscrow(),
        account=SimpleNamespace(address="0x0000000000000000000000000000000000000001"),
        chain_id=1,
        rpc_url="http://localhost",
    )

    payload = {
        "user": "0x0000000000000000000000000000000000000001",
        "market": "0x0000000000000000000000000000000000000002",
        "commitment": "0x" + "0" * 64,
        "nonce": 1,
        "expiry": int(time.time()) + 60,
        "chain_id": 1,
        "ticket_value_wei": 1,
        "signature": "0x" + "1" * 130,
    }

    await asyncio.gather(service.commit(payload), service.commit(payload))
    assert service.max_active == 1
