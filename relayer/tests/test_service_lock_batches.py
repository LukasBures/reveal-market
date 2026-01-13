from __future__ import annotations

from types import SimpleNamespace

import pytest
from relayer.service import RelayerService, TxSendError
from web3 import Web3


class DummyWeb3:
    def __init__(self):
        self.eth = SimpleNamespace()

    def to_checksum_address(self, address: str) -> str:
        return Web3.to_checksum_address(address)


def _service() -> RelayerService:
    return RelayerService(
        web3=DummyWeb3(),
        escrow=SimpleNamespace(address="0xescrow"),
        account=SimpleNamespace(address="0xrelayer"),
        chain_id=1,
        rpc_url="http://localhost",
    )


def _ticket(ticket_id: int, *, leaf: str | None = None) -> dict:
    payload = {
        "ticket_id": ticket_id,
        "outcome_id": 0,
        "amount": 10,
        "payout": 10,
        "user": "0x0000000000000000000000000000000000000001",
        "salt": "0x" + "1" * 64,
    }
    if leaf is not None:
        payload["leaf"] = leaf
    return payload


def test_build_batch_roots_rejects_gap_between_batches():
    service = _service()
    tickets = [_ticket(0), _ticket(512)]
    with pytest.raises(TxSendError) as exc:
        service._build_batch_roots(tickets)
    assert exc.value.kind == "invalid"


def test_build_batch_roots_rejects_gap_within_batch():
    service = _service()
    tickets = [_ticket(0), _ticket(2)]
    with pytest.raises(TxSendError) as exc:
        service._build_batch_roots(tickets)
    assert exc.value.kind == "invalid"


def test_build_batch_roots_rejects_duplicate_ticket_index():
    service = _service()
    tickets = [_ticket(0), _ticket(0)]
    with pytest.raises(TxSendError) as exc:
        service._build_batch_roots(tickets)
    assert exc.value.kind == "invalid"
