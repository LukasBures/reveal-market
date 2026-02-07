from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from decimal import Decimal

import app.runtime as runtime
import pytest
from app import models
from app.routes import trade as trade_routes
from app.schemas import FxQuoteResponse
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import HTTPException
from pydantic import SecretStr
from shared.merkle import build_merkle_root_and_paths


class _AsyncClientStub:
    def __init__(self, payload: dict, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code
        self.text = "ok"

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False

    async def post(self, *_args, **_kwargs):
        return self

    def json(self):
        return self.payload


async def _streamer_price(*_args, **_kwargs):
    return Decimal("0.5")


def _seed_market(db_session, event_id: str = "mkt-test", address: str = "0x1111111111111111111111111111111111111111"):
    market = models.Market(
        event_id=event_id,
        title="Test Market",
        oracle="0x1234",
        market_address=address,
        resolution_status=models.ResolutionStatusEnum.FINAL.value,
    )
    db_session.add(market)
    db_session.commit()
    return market


def test_claim_rejected_when_resolution_pending(client, db_session, monkeypatch):
    signer = Account.create()
    user = Account.create()
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "pricing_signer_private_key", SecretStr(signer._private_key.hex()), raising=False)
    market = models.Market(
        event_id="claim-pending",
        title="Pending Market",
        oracle="0x1234",
        market_address="0x5555555555555555555555555555555555555555",
        resolution_status=models.ResolutionStatusEnum.PENDING.value,
    )
    db_session.add(market)
    db_session.flush()
    settlement = models.Settlement(
        id=market.id,
        market_id=market.id,
        merkle_root="0xabc",
        commitments_count=1,
        winning_outcome_id=0,
    )
    db_session.add(settlement)
    db_session.commit()

    payload = {
        "event_id": market.event_id,
        "wallet_address": user.address,
        "ticket_id": 0,
    }
    resp = client.post("/trade/claim", json=payload)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "market_not_final"


def test_pricing_quote_allows_missing_address(client, db_session, monkeypatch):
    signer = Account.create()
    user = Account.create()
    market = _seed_market(db_session, event_id="auto-mkt", address=None)
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "pricing_signer_private_key", SecretStr(signer._private_key.hex()), raising=False)
    monkeypatch.setattr(settings, "max_stake_zen", 1, raising=False)
    monkeypatch.setattr(settings, "max_user_stake_per_market_zen", 10, raising=False)
    monkeypatch.setattr(settings, "max_market_stake_zen", 100, raising=False)
    monkeypatch.setattr(settings, "haircut_percent", 0.12, raising=False)
    monkeypatch.setattr(settings, "pricing_edge_percent", 0.05, raising=False)

    async def _fx_quote(*_args, **_kwargs):
        return FxQuoteResponse(zen_usd=Decimal("2"), stale=False, received_at=None)

    monkeypatch.setattr("app.routes.pricing.fetch_fx_quote", _fx_quote)
    monkeypatch.setattr("app.routes.pricing._fetch_streamer_price", _streamer_price)
    deployed_address = "0x2222222222222222222222222222222222222222"

    async def _ensure_market(_session, _market_id, _expected):
        return market.id, deployed_address, 1

    monkeypatch.setattr("app.routes.trade._ensure_market_or_create", _ensure_market)

    payload = {
        "stake_zen": 0.1,
        "wallet_address": user.address,
        "market_address": None,
        "outcome_id": 0,
        "market_id": market.event_id,
        "user_id": user.address,
    }
    resp = client.post("/pricing/quote", json=payload)
    assert resp.status_code == 200
    quote = resp.json()
    assert quote["market_address"] == deployed_address
    assert quote["quote_id"]
    assert quote["signature"]


def test_trade_commit_and_positions_roundtrip(client, db_session, monkeypatch):
    signer = Account.create()
    auth_signer = Account.create()
    user = Account.create()
    market = _seed_market(db_session, event_id="commit-mkt", address="0x3333333333333333333333333333333333333333")
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "pricing_signer_private_key", SecretStr(signer._private_key.hex()), raising=False)
    monkeypatch.setattr(settings, "max_stake_zen", 1, raising=False)
    monkeypatch.setattr(settings, "max_user_stake_per_market_zen", 10, raising=False)
    monkeypatch.setattr(settings, "max_market_stake_zen", 100, raising=False)
    monkeypatch.setattr(settings, "haircut_percent", 0.12, raising=False)
    monkeypatch.setattr(settings, "pricing_edge_percent", 0.05, raising=False)
    monkeypatch.setattr(
        settings, "authorization_signer_private_key", SecretStr(auth_signer._private_key.hex()), raising=False
    )
    monkeypatch.setattr(settings, "authorization_signer", auth_signer.address, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)

    async def _fx_quote(*_args, **_kwargs):
        return FxQuoteResponse(zen_usd=Decimal("1.25"), stale=False, received_at=None)

    monkeypatch.setattr("app.routes.pricing.fetch_fx_quote", _fx_quote)
    monkeypatch.setattr("app.routes.pricing._fetch_streamer_price", _streamer_price)

    async def _ensure_market(_session, _market_id, _expected):
        return market.id, market.market_address, 1

    monkeypatch.setattr("app.routes.trade._ensure_market", _ensure_market)
    monkeypatch.setattr("app.routes.trade._ensure_market_or_create", _ensure_market)

    async def _sync_factory(*_args, **_kwargs):
        return 0

    monkeypatch.setattr("app.routes.trade._sync_market_factory_params", _sync_factory)

    async def _next_ticket_id(*_args, **_kwargs):
        return 0

    monkeypatch.setattr("app.routes.trade._next_ticket_id_onchain", _next_ticket_id)

    async def _escrow_balance(_wallet: str):
        return 4242

    monkeypatch.setattr("app.routes.trade._fetch_escrow_balance", _escrow_balance)
    tx_hash = "0x" + "a" * 64

    async def _http_client_stub(*_args, **_kwargs):
        return _AsyncClientStub({"txHash": tx_hash})

    monkeypatch.setattr("app.routes.trade.get_http_client", _http_client_stub)

    quote_payload = {
        "stake_zen": 0.1,
        "wallet_address": user.address,
        "market_address": market.market_address,
        "outcome_id": 1,
        "market_id": market.event_id,
        "user_id": user.address,
    }
    quote_resp = client.post("/pricing/quote", json=quote_payload)
    assert quote_resp.status_code == 200
    quote = quote_resp.json()

    commit_signature = Account.sign_message(
        encode_defunct(text=f"commit:{quote['quote_id']}:{user.address.lower()}"),
        user._private_key,
    ).signature.hex()
    commit_resp = client.post(
        "/trade/commit",
        json={"quote_id": quote["quote_id"]},
        headers={"X-Wallet-Signature": commit_signature},
    )
    assert commit_resp.status_code == 200
    commit_body = commit_resp.json()
    assert commit_body["tx_hash"] == tx_hash
    assert commit_body["escrow_balance_wei"] == 4242

    positions_resp = client.get(f"/positions?wallet={user.address}")
    assert positions_resp.status_code == 200
    data = positions_resp.json()
    assert isinstance(data, dict)
    assert data["escrow_balance_wei"] == 4242
    assert len(data["positions"]) == 1
    pos = data["positions"][0]
    assert pos["market_id"] == market.event_id
    assert pos["ticket_id"] == 0
    assert pos["status"] == "committed"
    assert pos["claimable"] is False
    assert pos["tx_hash"] == tx_hash


def test_trade_claim_rebuilds_merkle_path(client, db_session, monkeypatch):
    user = Account.create()
    market = _seed_market(db_session, event_id="claim-mkt", address="0x4444444444444444444444444444444444444444")
    commitment_hex = "0x" + "11" * 32
    leaf_bytes = bytes.fromhex(commitment_hex[2:])
    root_bytes, _ = build_merkle_root_and_paths([leaf_bytes])
    merkle_root = "0x" + root_bytes.hex()

    db_session.add(
        models.Commitment(
            market_id=market.id,
            user_address=user.address.lower(),
            outcome_id=0,
            amount_wei=100,
            payout_wei=150,
            salt="0x0",
            ticket_hash=commitment_hex.lower(),
            leaf=commitment_hex.lower(),
            leaf_index=0,
        )
    )
    db_session.add(
        models.Settlement(
            id=1,
            market_id=market.id,
            merkle_root=merkle_root,
            commitments_count=1,
            winning_outcome_id=0,
            proof_status=models.SettlementProofStatus.GENERATED.value,
            created_at=datetime.now(tz=UTC),
        )
    )
    db_session.commit()

    settings = runtime.settings
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    tx_hash = "0x" + "c" * 64

    async def _http_client_stub(*_args, **_kwargs):
        return _AsyncClientStub({"txHash": tx_hash})

    monkeypatch.setattr("app.routes.trade.get_http_client", _http_client_stub)

    resp = client.post(
        "/trade/claim",
        json={
            "market_id": market.event_id,
            "wallet_address": user.address,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tx_hash"] == tx_hash
    assert body["ticket_id"] == 0
    assert body["payout_wei"] == 150
    assert body["status"] == "claimed"


def test_claim_bundles_return_winning_ticket(client, db_session):
    user = Account.create()
    market = _seed_market(db_session, event_id="bundle-mkt", address="0x6666666666666666666666666666666666666666")
    commitment_hex = "0x" + "33" * 32
    leaf_bytes = bytes.fromhex(commitment_hex[2:])
    root_bytes, paths = build_merkle_root_and_paths([leaf_bytes])
    merkle_root = "0x" + root_bytes.hex()
    expected_proof = ["0x" + sibling.hex() for sibling in paths[0]]

    db_session.add(
        models.Commitment(
            market_id=market.id,
            user_address=user.address.lower(),
            outcome_id=1,
            amount_wei=200,
            payout_wei=250,
            salt="0xbeef",
            ticket_hash=commitment_hex.lower(),
            leaf=commitment_hex.lower(),
            leaf_index=0,
        )
    )
    db_session.add(
        models.Settlement(
            id=2,
            market_id=market.id,
            merkle_root=merkle_root,
            commitments_count=1,
            winning_outcome_id=1,
            proof_status=models.SettlementProofStatus.GENERATED.value,
            created_at=datetime.now(tz=UTC),
        )
    )
    db_session.commit()

    signature = Account.sign_message(
        encode_defunct(text=f"claim-bundles:{user.address.lower()}"),
        private_key=user._private_key,
    ).signature.hex()
    resp = client.get(f"/claim/bundles?wallet={user.address}", headers={"X-Wallet-Signature": signature})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["bundles"]) == 1
    assert body.get("status") is None
    bundle = body["bundles"][0]
    assert bundle["marketId"] == market.event_id
    assert bundle["ticketId"] == 0
    assert bundle["amountWei"] == 200
    assert bundle["payoutWei"] == 250
    assert bundle["merkleProof"] == expected_proof
    assert bundle["commitmentsRoot"].lower() == merkle_root.lower()
    assert bundle["user"].lower() == user.address.lower()


def test_claim_bundles_skip_claimed_commitment(client, db_session):
    user = Account.create()
    market = _seed_market(db_session, event_id="bundle-claimed", address="0x7777777777777777777777777777777777777777")
    commitment_hex = "0x" + "44" * 32
    leaf_bytes = bytes.fromhex(commitment_hex[2:])
    root_bytes, _ = build_merkle_root_and_paths([leaf_bytes])
    merkle_root = "0x" + root_bytes.hex()

    db_session.add(
        models.Commitment(
            market_id=market.id,
            user_address=user.address.lower(),
            outcome_id=1,
            amount_wei=200,
            payout_wei=250,
            salt="0xbeef",
            ticket_hash=commitment_hex.lower(),
            leaf=commitment_hex.lower(),
            leaf_index=0,
            claimed_at=datetime.now(tz=UTC),
        )
    )
    db_session.add(
        models.Settlement(
            id=3,
            market_id=market.id,
            merkle_root=merkle_root,
            commitments_count=1,
            winning_outcome_id=1,
            proof_status=models.SettlementProofStatus.GENERATED.value,
            created_at=datetime.now(tz=UTC),
        )
    )
    db_session.commit()

    signature = Account.sign_message(
        encode_defunct(text=f"claim-bundles:{user.address.lower()}"),
        private_key=user._private_key,
    ).signature.hex()
    resp = client.get(f"/claim/bundles?wallet={user.address}", headers={"X-Wallet-Signature": signature})
    assert resp.status_code == 200
    body = resp.json()
    assert body["bundles"] == []
    assert body.get("status") is None


def test_claim_status_pending(client, db_session):
    user = Account.create()
    market = _seed_market(db_session, event_id="bundle-pending", address="0x9999999999999999999999999999999999999999")
    market.resolution_status = models.ResolutionStatusEnum.FINAL.value
    market.resolved_at = datetime.now(tz=UTC)
    db_session.add(market)
    db_session.add(
        models.Commitment(
            market_id=market.id,
            user_address=user.address.lower(),
            outcome_id=1,
            amount_wei=200,
            payout_wei=250,
            salt="0xbeef",
            ticket_hash="0x" + "99" * 32,
            leaf="0x" + "99" * 32,
            leaf_index=0,
        )
    )
    db_session.add(
        models.Settlement(
            id=10,
            market_id=market.id,
            merkle_root=None,
            commitments_count=1,
            winning_outcome_id=1,
            proof_status=models.SettlementProofStatus.PENDING.value,
            created_at=datetime.now(tz=UTC),
        )
    )
    db_session.commit()

    signature = Account.sign_message(
        encode_defunct(text=f"claim-bundles:{user.address.lower()}"),
        private_key=user._private_key,
    ).signature.hex()
    resp = client.get(f"/claim/status?wallet={user.address}", headers={"X-Wallet-Signature": signature})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert market.event_id in body.get("pendingMarkets", [])


def test_positions_marks_claimed(client, db_session):
    user = Account.create()
    market = _seed_market(db_session, event_id="pos-claimed", address="0x8888888888888888888888888888888888888888")
    commitment_hex = "0x" + "55" * 32
    db_session.add(
        models.Commitment(
            market_id=market.id,
            user_address=user.address.lower(),
            outcome_id=1,
            amount_wei=200,
            payout_wei=250,
            salt="0xbeef",
            ticket_hash=commitment_hex.lower(),
            leaf=commitment_hex.lower(),
            leaf_index=0,
            claimed_at=datetime.now(tz=UTC),
        )
    )
    db_session.add(
        models.Settlement(
            id=4,
            market_id=market.id,
            merkle_root="0x" + "11" * 32,
            commitments_count=1,
            winning_outcome_id=1,
            proof_status=models.SettlementProofStatus.GENERATED.value,
            created_at=datetime.now(tz=UTC),
        )
    )
    db_session.commit()

    resp = client.get(f"/positions?wallet={user.address}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["positions"]) == 1
    pos = body["positions"][0]
    assert pos["status"] == "claimed"
    assert pos["claimable"] is False


def test_positions_zeroes_payout_for_losing_outcome(client, db_session):
    user = Account.create()
    market = _seed_market(db_session, event_id="pos-loser", address="0x7777777777777777777777777777777777777777")
    commitment_hex = "0x" + "77" * 32
    db_session.add(
        models.Commitment(
            market_id=market.id,
            user_address=user.address.lower(),
            outcome_id=0,
            amount_wei=200,
            payout_wei=250,
            salt="0xbeef",
            ticket_hash=commitment_hex.lower(),
            leaf=commitment_hex.lower(),
            leaf_index=0,
        )
    )
    db_session.add(
        models.Settlement(
            id=5,
            market_id=market.id,
            merkle_root="0x" + "99" * 32,
            commitments_count=1,
            winning_outcome_id=1,
            proof_status=models.SettlementProofStatus.GENERATED.value,
            created_at=datetime.now(tz=UTC),
        )
    )
    db_session.commit()

    resp = client.get(f"/positions?wallet={user.address}")
    assert resp.status_code == 200
    pos = resp.json()["positions"][0]
    assert pos["status"] == "settled"
    assert pos["claimable"] is False
    assert pos["payout_wei"] == 0
    assert pos["payout_zen"] == 0


def test_sync_commitments_endpoint(client, db_session, monkeypatch):
    market = _seed_market(db_session, event_id="sync-mkt", address="0x5555555555555555555555555555555555555555")
    monkeypatch.setattr("app.routes.trade.settings.internal_api_secret", SecretStr("secret"), raising=False)
    payload = {
        "event_id": market.event_id,
        "tickets": [
            {
                "ticketHash": "0x" + "22" * 32,
                "leaf": "0x" + "22" * 32,
                "user_address": "0xabc",
                "outcomeId": 1,
                "amount": 100,
                "payout": 110,
                "salt": "0x0",
                "merkleIndex": 0,
                "merklePath": [],
            }
        ],
    }
    resp = client.post("/internal/commitments/sync", json=payload, headers={"X-Internal-Secret": "secret"})
    assert resp.status_code == 200
    assert resp.json()["recorded"] == 1


def test_ingest_settlement_endpoint(client, db_session, monkeypatch):
    market = _seed_market(db_session, event_id="settle-mkt", address="0x6666666666666666666666666666666666666666")
    monkeypatch.setattr("app.routes.trade.settings.internal_api_secret", SecretStr("secret"), raising=False)
    payload = {
        "event_id": market.event_id,
        "merkleRoot": "0x" + "33" * 32,
        "commitmentsCount": 1,
        "winningOutcomeId": 0,
        "rakeBps": 200,
        "totalEscrow": 100,
        "totalLiability": 100,
    }
    resp = client.post("/internal/settlements/ingest", json=payload, headers={"X-Internal-Secret": "secret"})
    assert resp.status_code == 200
    assert resp.json()["updated"] is True
    refreshed = db_session.get(models.Settlement, 1)
    assert refreshed is not None
    assert refreshed.winning_outcome_id == 0


def test_trade_status_reads_queue_result(client, monkeypatch):
    class FakeCache:
        def __init__(self):
            self.store = {}

        async def get(self, key):
            return self.store.get(key)

        async def lpush(self, key, value):
            self.store[key] = value

    cache = FakeCache()

    async def _get_cache():
        return cache

    monkeypatch.setattr("app.routes.trade.get_cache_client", _get_cache)
    monkeypatch.setattr("app.runtime.settings.relayer_queue_key", "queue-key", raising=False)
    cache.store["queue-key:result:job1"] = json.dumps({"status": "pending"})

    resp = client.get("/trade/status", params={"job_id": "job1"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


def test_relayer_hooks_require_secret(client, db_session, monkeypatch):
    market = _seed_market(db_session, event_id="hook-mkt", address="0x7777777777777777777777777777777777777777")
    monkeypatch.setattr("app.runtime.settings.relayer_webhook_secret", "secret", raising=False)
    monkeypatch.setattr("app.routes.trade.settings.internal_api_secret", SecretStr("internal"), raising=False)

    # missing secret
    resp = client.post("/internal/relayer/commitments", json={"event_id": market.event_id, "tickets": []})
    assert resp.status_code == 401

    resp_ok = client.post(
        "/internal/relayer/commitments",
        headers={"X-Relayer-Secret": "secret", "X-Internal-Secret": "internal"},
        json={"event_id": market.event_id, "tickets": []},
    )
    assert resp_ok.status_code == 200

    settlement_payload = {
        "event_id": market.event_id,
        "merkleRoot": "0x" + "11" * 32,
        "commitmentsCount": 1,
        "winningOutcomeId": 0,
        "rakeBps": 200,
        "totalEscrow": 100,
        "totalLiability": 100,
    }
    resp_settlements = client.post(
        "/internal/relayer/settlements",
        headers={"X-Relayer-Secret": "secret", "X-Internal-Secret": "internal"},
        json=settlement_payload,
    )
    assert resp_settlements.status_code == 200


class _DummyAsyncCall:
    def __init__(self, value):
        self._value = value

    async def call(self):
        return self._value


class _DummyFactoryContract:
    def __init__(self, params):
        self._params = params
        self.functions = self

    def getMarketParams(self, _market_id):  # noqa: N802 - mirrors on-chain method
        return _DummyAsyncCall(self._params)


class _DummyMarketContract:
    def __init__(self, market_id):
        self._market_id = market_id
        self.functions = self

    def marketId(self):  # noqa: N802 - mirrors on-chain method
        return _DummyAsyncCall(self._market_id)


class _DummyEth:
    def __init__(self, factory_contract, market_contract):
        self._factory_contract = factory_contract
        self._market_contract = market_contract

    def contract(self, address=None, abi=None):
        if abi == trade_routes.MARKET_FACTORY_ABI:
            return self._factory_contract
        return self._market_contract


class _DummyWeb3:
    def __init__(self, factory_contract, market_contract):
        self.eth = _DummyEth(factory_contract, market_contract)


def _build_factory_params(
    *,
    market_address: str,
    ticket_size: int,
    auth_signer: str,
    rake_bps: int,
    market_id: int,
    circuit_hash: str,
):
    return (
        market_address,
        "0x" + "11" * 20,
        "0x" + "22" * 20,
        circuit_hash,
        int(time.time()) + 1000,
        ticket_size,
        1000,
        auth_signer,
        0,
        rake_bps,
        "0x" + "44" * 20,
        "0x" + "55" * 20,
        market_id,
    )


@pytest.mark.asyncio
async def test_sync_market_factory_params_updates_market(test_database, monkeypatch):
    _, async_session, _ = test_database
    auth_signer = Account.create()
    market_address = "0x" + "ab" * 20
    params = _build_factory_params(
        market_address=market_address,
        ticket_size=100,
        auth_signer=auth_signer.address,
        rake_bps=200,
        market_id=42,
        circuit_hash=trade_routes.settings.circuit_hash,
    )
    dummy_web3 = _DummyWeb3(_DummyFactoryContract(params), _DummyMarketContract(42))
    monkeypatch.setattr(trade_routes, "get_async_web3", lambda *_args, **_kwargs: dummy_web3)
    monkeypatch.setattr(trade_routes.settings, "factory_address", "0x" + "99" * 20, raising=False)
    monkeypatch.setattr(trade_routes.settings, "rpc_url", "http://localhost", raising=False)
    monkeypatch.setattr(trade_routes.settings, "ticket_size_wei", 100, raising=False)
    monkeypatch.setattr(trade_routes.settings, "rake_percent", 0.02, raising=False)
    monkeypatch.setattr(trade_routes.settings, "authorization_signer", auth_signer.address, raising=False)
    monkeypatch.setattr(trade_routes.settings, "circuit_hash", trade_routes.settings.circuit_hash, raising=False)

    async with async_session() as session:
        market = models.Market(event_id="evt-sync", title="Sync", oracle="0x1", market_address=market_address)
        session.add(market)
        await session.flush()
        rake = await trade_routes._sync_market_factory_params(
            session,
            market_record=market,
            market_address=market_address,
            market_onchain_id=None,
            auth_signer_key=auth_signer._private_key.hex(),
        )
        await session.refresh(market)

    assert rake == 200
    assert market.onchain_market_id == 42
    assert market.factory == trade_routes.settings.factory_address
    assert market.rake_bps == 200


@pytest.mark.asyncio
async def test_sync_market_factory_params_rejects_ticket_size(monkeypatch, test_database):
    _, async_session, _ = test_database
    auth_signer = Account.create()
    market_address = "0x" + "cd" * 20
    params = _build_factory_params(
        market_address=market_address,
        ticket_size=101,
        auth_signer=auth_signer.address,
        rake_bps=200,
        market_id=1,
        circuit_hash=trade_routes.settings.circuit_hash,
    )
    dummy_web3 = _DummyWeb3(_DummyFactoryContract(params), _DummyMarketContract(1))
    monkeypatch.setattr(trade_routes, "get_async_web3", lambda *_args, **_kwargs: dummy_web3)
    monkeypatch.setattr(trade_routes.settings, "factory_address", "0x" + "99" * 20, raising=False)
    monkeypatch.setattr(trade_routes.settings, "rpc_url", "http://localhost", raising=False)
    monkeypatch.setattr(trade_routes.settings, "ticket_size_wei", 100, raising=False)
    monkeypatch.setattr(trade_routes.settings, "rake_percent", 0.02, raising=False)
    monkeypatch.setattr(trade_routes.settings, "authorization_signer", auth_signer.address, raising=False)
    monkeypatch.setattr(trade_routes.settings, "circuit_hash", trade_routes.settings.circuit_hash, raising=False)

    async with async_session() as session:
        market = models.Market(event_id="evt-mismatch", title="Mismatch", oracle="0x1", market_address=market_address)
        session.add(market)
        await session.flush()
        with pytest.raises(HTTPException) as exc:
            await trade_routes._sync_market_factory_params(
                session,
                market_record=market,
                market_address=market_address,
                market_onchain_id=None,
                auth_signer_key=auth_signer._private_key.hex(),
            )

    assert exc.value.status_code == 409
    assert exc.value.detail == "ticket_size_mismatch"


@pytest.mark.asyncio
async def test_sync_market_factory_params_rejects_signer_mismatch(monkeypatch, test_database):
    _, async_session, _ = test_database
    auth_signer = Account.create()
    other_signer = Account.create()
    market_address = "0x" + "ef" * 20
    params = _build_factory_params(
        market_address=market_address,
        ticket_size=100,
        auth_signer=other_signer.address,
        rake_bps=200,
        market_id=2,
        circuit_hash=trade_routes.settings.circuit_hash,
    )
    dummy_web3 = _DummyWeb3(_DummyFactoryContract(params), _DummyMarketContract(2))
    monkeypatch.setattr(trade_routes, "get_async_web3", lambda *_args, **_kwargs: dummy_web3)
    monkeypatch.setattr(trade_routes.settings, "factory_address", "0x" + "99" * 20, raising=False)
    monkeypatch.setattr(trade_routes.settings, "rpc_url", "http://localhost", raising=False)
    monkeypatch.setattr(trade_routes.settings, "ticket_size_wei", 100, raising=False)
    monkeypatch.setattr(trade_routes.settings, "rake_percent", 0.02, raising=False)
    monkeypatch.setattr(trade_routes.settings, "authorization_signer", auth_signer.address, raising=False)
    monkeypatch.setattr(trade_routes.settings, "circuit_hash", trade_routes.settings.circuit_hash, raising=False)

    async with async_session() as session:
        market = models.Market(event_id="evt-signer", title="Signer", oracle="0x1", market_address=market_address)
        session.add(market)
        await session.flush()
        with pytest.raises(HTTPException) as exc:
            await trade_routes._sync_market_factory_params(
                session,
                market_record=market,
                market_address=market_address,
                market_onchain_id=None,
                auth_signer_key=auth_signer._private_key.hex(),
            )

    assert exc.value.status_code == 409
    assert exc.value.detail == "authorization_signer_mismatch"


@pytest.mark.asyncio
async def test_sync_market_factory_params_rejects_circuit_hash(monkeypatch, test_database):
    _, async_session, _ = test_database
    auth_signer = Account.create()
    market_address = "0x" + "aa" * 20
    params = _build_factory_params(
        market_address=market_address,
        ticket_size=100,
        auth_signer=auth_signer.address,
        rake_bps=200,
        market_id=3,
        circuit_hash="0x" + "11" * 32,
    )
    dummy_web3 = _DummyWeb3(_DummyFactoryContract(params), _DummyMarketContract(3))
    monkeypatch.setattr(trade_routes, "get_async_web3", lambda *_args, **_kwargs: dummy_web3)
    monkeypatch.setattr(trade_routes.settings, "factory_address", "0x" + "99" * 20, raising=False)
    monkeypatch.setattr(trade_routes.settings, "rpc_url", "http://localhost", raising=False)
    monkeypatch.setattr(trade_routes.settings, "ticket_size_wei", 100, raising=False)
    monkeypatch.setattr(trade_routes.settings, "rake_percent", 0.02, raising=False)
    monkeypatch.setattr(trade_routes.settings, "authorization_signer", auth_signer.address, raising=False)
    monkeypatch.setattr(trade_routes.settings, "circuit_hash", "0x" + "22" * 32, raising=False)

    async with async_session() as session:
        market = models.Market(event_id="evt-circuit", title="Circuit", oracle="0x1", market_address=market_address)
        session.add(market)
        await session.flush()
        with pytest.raises(HTTPException) as exc:
            await trade_routes._sync_market_factory_params(
                session,
                market_record=market,
                market_address=market_address,
                market_onchain_id=None,
                auth_signer_key=auth_signer._private_key.hex(),
            )

    assert exc.value.status_code == 409
    assert exc.value.detail == "circuit_hash_mismatch"
