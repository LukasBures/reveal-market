from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import pytest
import relayer.service as service_module
from relayer.poseidon import build_batch_root, compute_leaf, int_to_hex32
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


def _valid_commit_payload():
    return {
        "user": "0x0000000000000000000000000000000000000001",
        "market": "0x0000000000000000000000000000000000000002",
        "commitment": "0x" + "0" * 64,
        "nonce": 1,
        "expiry": int(time.time()) + 60,
        "chain_id": 1,
        "ticket_value_wei": 1,
        "signature": "0x" + "1" * 130,
    }


def _valid_claim_payload():
    return {
        "market": "0x0000000000000000000000000000000000000002",
        "user": "0x0000000000000000000000000000000000000001",
        "ticket_id": 0,
        "outcome_id": 1,
        "amount": 10,
        "salt": "0x" + "2" * 64,
        "merkle_proof": ["0x" + "3" * 64],
    }


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


def test_validate_commit_rejects_expired():
    service = RelayerService(
        web3=DummyWeb3(),
        escrow=SimpleNamespace(address="0xescrow"),
        account=SimpleNamespace(address="0xrelayer"),
        chain_id=1,
        rpc_url="http://localhost",
    )
    payload = _valid_commit_payload()
    payload["expiry"] = int(time.time()) - 1

    with pytest.raises(TxSendError) as exc:
        service.validate_commit_payload(payload)

    assert exc.value.kind == "invalid"
    assert exc.value.permanent is True


def test_validate_commit_rejects_bad_commitment():
    service = RelayerService(
        web3=DummyWeb3(),
        escrow=SimpleNamespace(address="0xescrow"),
        account=SimpleNamespace(address="0xrelayer"),
        chain_id=1,
        rpc_url="http://localhost",
    )
    payload = _valid_commit_payload()
    payload["commitment"] = "0x" + "0" * 62

    with pytest.raises(TxSendError) as exc:
        service.validate_commit_payload(payload)

    assert exc.value.kind == "invalid"


def test_validate_claim_rejects_bad_salt():
    service = RelayerService(
        web3=DummyWeb3(),
        escrow=SimpleNamespace(address="0xescrow"),
        account=SimpleNamespace(address="0xrelayer"),
        chain_id=1,
        rpc_url="http://localhost",
    )
    payload = _valid_claim_payload()
    payload["salt"] = "0x" + "4" * 62

    with pytest.raises(TxSendError) as exc:
        service.validate_claim_payload(payload)

    assert exc.value.kind == "invalid"


def test_validate_lock_requires_market_id():
    service = RelayerService(
        web3=DummyWeb3(),
        escrow=SimpleNamespace(address="0xescrow"),
        account=SimpleNamespace(address="0xrelayer"),
        chain_id=1,
        rpc_url="http://localhost",
    )
    payload = {
        "market": "0x0000000000000000000000000000000000000002",
        "tickets": [
            {
                "ticket_id": 0,
                "outcome_id": 0,
                "amount": 10,
                "user": "0x0000000000000000000000000000000000000001",
                "salt": "0x" + "1" * 64,
            }
        ],
    }

    with pytest.raises(TxSendError) as exc:
        service.validate_lock_payload(payload)

    assert exc.value.kind == "invalid"
    assert exc.value.permanent is True


def test_build_batch_roots_matches_poseidon():
    service = RelayerService(
        web3=DummyWeb3(),
        escrow=SimpleNamespace(address="0xescrow"),
        account=SimpleNamespace(address="0xrelayer"),
        chain_id=1,
        rpc_url="http://localhost",
    )
    tickets = [
        {
            "ticket_id": 0,
            "outcome_id": 0,
            "amount": 10,
            "user": "0x0000000000000000000000000000000000000001",
            "salt": "0x" + "1" * 64,
        },
        {
            "ticket_id": 1,
            "outcome_id": 1,
            "amount": 5,
            "user": "0x0000000000000000000000000000000000000002",
            "salt": "0x" + "2" * 64,
        },
    ]

    roots, counts, total = service._build_batch_roots(tickets)
    expected_leaves = [
        compute_leaf(
            tickets[0]["ticket_id"],
            tickets[0]["outcome_id"],
            tickets[0]["amount"],
            tickets[0]["user"],
            tickets[0]["salt"],
        ),
        compute_leaf(
            tickets[1]["ticket_id"],
            tickets[1]["outcome_id"],
            tickets[1]["amount"],
            tickets[1]["user"],
            tickets[1]["salt"],
        ),
    ]
    expected_root = build_batch_root(expected_leaves)
    assert roots == [int_to_hex32(expected_root)]
    assert counts == [2]
    assert total == 2


def test_build_batch_roots_rejects_leaf_mismatch():
    service = RelayerService(
        web3=DummyWeb3(),
        escrow=SimpleNamespace(address="0xescrow"),
        account=SimpleNamespace(address="0xrelayer"),
        chain_id=1,
        rpc_url="http://localhost",
    )
    tickets = [
        {
            "ticket_id": 0,
            "outcome_id": 0,
            "amount": 10,
            "user": "0x0000000000000000000000000000000000000001",
            "salt": "0x" + "1" * 64,
            "leaf": "0x" + "3" * 64,
        }
    ]

    with pytest.raises(TxSendError) as exc:
        service._build_batch_roots(tickets)

    assert exc.value.kind == "invalid"


@pytest.mark.asyncio
async def test_push_commit_ingest_uses_api_aliases(monkeypatch):
    captured: dict[str, Any] = {}

    class DummyResponse:
        status_code = 200

    class DummyAsyncClient:
        def __init__(self, *args, **kwargs):
            captured["client"] = self
            self.requests: list[dict[str, Any]] = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None, headers=None):
            self.requests.append({"url": url, "json": json, "headers": headers})
            return DummyResponse()

    monkeypatch.setattr(service_module.httpx, "AsyncClient", DummyAsyncClient)

    service = RelayerService(
        web3=DummyWeb3(),
        escrow=SimpleNamespace(address="0xescrow"),
        account=SimpleNamespace(address="0xrelayer"),
        chain_id=1,
        rpc_url="http://localhost",
        api_base_url="http://api",
        api_bearer_token="token",  # noqa: S106 - test-only token
    )
    payload = {
        "event_id": "evt-1",
        "market": "0x0000000000000000000000000000000000000002",
        "commitment": "0x" + "0" * 64,
        "user": "0x0000000000000000000000000000000000000001",
        "outcome_id": 1,
        "amount_wei": 99,
        "salt": "0x" + "1" * 64,
        "ticket_id": 7,
    }
    await service.push_commit_ingest(payload, tx_hash="0xabc")

    client = captured.get("client")
    assert client is not None
    assert client.requests
    request = client.requests[0]
    assert request["url"].endswith("/commitments/sync")
    ticket = request["json"]["tickets"][0]
    assert ticket["ticketHash"] == payload["commitment"]
    assert ticket["user_address"] == payload["user"]
    assert ticket["outcomeId"] == payload["outcome_id"]
    assert ticket["amount"] == payload["amount_wei"]
    assert ticket["merkleIndex"] == payload["ticket_id"]
    assert ticket["txHash"] == "0xabc"


@pytest.mark.asyncio
async def test_push_settlement_ingest_uses_api_aliases(monkeypatch):
    captured: dict[str, Any] = {}

    class DummyResponse:
        status_code = 200

    class DummyAsyncClient:
        def __init__(self, *args, **kwargs):
            captured["client"] = self
            self.requests: list[dict[str, Any]] = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None, headers=None):
            self.requests.append({"url": url, "json": json, "headers": headers})
            return DummyResponse()

    monkeypatch.setattr(service_module.httpx, "AsyncClient", DummyAsyncClient)

    service = RelayerService(
        web3=DummyWeb3(),
        escrow=SimpleNamespace(address="0xescrow"),
        account=SimpleNamespace(address="0xrelayer"),
        chain_id=1,
        rpc_url="http://localhost",
        api_base_url="http://api",
    )
    payload = {
        "event_id": "evt-2",
        "merkle_root": "0x" + "2" * 64,
        "commitments_count": 3,
        "batch_roots": ["0x" + "3" * 64],
        "batch_counts": [3],
        "pool_total_yes": 10,
        "pool_total_no": 20,
        "total_escrow": 30,
        "total_liability": 10,
        "rake_bps": 200,
        "proof_request_id": "req-1",
    }
    await service.push_settlement_ingest(payload, tx_hash="0xdef")

    client = captured.get("client")
    assert client is not None
    assert client.requests
    request = client.requests[0]
    assert request["url"].endswith("/settlements/ingest")
    body = request["json"]
    assert body["merkleRoot"] == payload["merkle_root"]
    assert body["commitmentsCount"] == payload["commitments_count"]
    assert body["batchRoots"] == payload["batch_roots"]
    assert body["batchCounts"] == payload["batch_counts"]
    assert body["poolTotalYes"] == payload["pool_total_yes"]
    assert body["poolTotalNo"] == payload["pool_total_no"]
    assert body["totalEscrow"] == payload["total_escrow"]
    assert body["totalLiability"] == payload["total_liability"]
    assert body["rakeBps"] == payload["rake_bps"]
    assert body["proofRequestId"] == payload["proof_request_id"]


@pytest.mark.asyncio
async def test_push_commit_ingest_skips_missing_event_id(monkeypatch):
    def fail_async_client(*_args, **_kwargs):
        raise AssertionError("AsyncClient should not be constructed")

    monkeypatch.setattr(service_module.httpx, "AsyncClient", fail_async_client)

    service = RelayerService(
        web3=DummyWeb3(),
        escrow=SimpleNamespace(address="0xescrow"),
        account=SimpleNamespace(address="0xrelayer"),
        chain_id=1,
        rpc_url="http://localhost",
        api_base_url="http://api",
    )
    payload = {
        "market": "0x0000000000000000000000000000000000000002",
        "commitment": "0x" + "0" * 64,
        "user": "0x0000000000000000000000000000000000000001",
        "outcome_id": 1,
        "amount_wei": 99,
        "salt": "0x" + "1" * 64,
        "ticket_id": 7,
    }
    await service.push_commit_ingest(payload, tx_hash="0xabc")


@pytest.mark.asyncio
async def test_push_settlement_ingest_skips_missing_market_id(monkeypatch):
    def fail_async_client(*_args, **_kwargs):
        raise AssertionError("AsyncClient should not be constructed")

    monkeypatch.setattr(service_module.httpx, "AsyncClient", fail_async_client)

    service = RelayerService(
        web3=DummyWeb3(),
        escrow=SimpleNamespace(address="0xescrow"),
        account=SimpleNamespace(address="0xrelayer"),
        chain_id=1,
        rpc_url="http://localhost",
        api_base_url="http://api",
    )
    payload = {
        "merkle_root": "0x" + "2" * 64,
        "commitments_count": 3,
    }
    await service.push_settlement_ingest(payload, tx_hash="0xdef")
