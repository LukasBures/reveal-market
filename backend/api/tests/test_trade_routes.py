from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import app.runtime as runtime
from app import models
from app.schemas import FxQuoteResponse
from eth_account import Account
from eth_account.messages import encode_defunct
from pydantic import SecretStr
from web3 import Web3


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


def _seed_market(db_session, event_id: str = "mkt-test", address: str = "0x1111111111111111111111111111111111111111"):
    market = models.Market(event_id=event_id, title="Test Market", oracle="0x1234", market_address=address)
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

    async def _fx_quote(*_args, **_kwargs):
        return FxQuoteResponse(zen_usd=Decimal("2"), stale=False, received_at=None)

    monkeypatch.setattr("app.routes.pricing.fetch_fx_quote", _fx_quote)

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
    assert quote["market_address"] is None
    assert quote["quote_id"]
    assert quote["signature"] is None


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
    monkeypatch.setattr(
        settings, "authorization_signer_private_key", SecretStr(auth_signer._private_key.hex()), raising=False
    )
    monkeypatch.setattr(settings, "authorization_signer", auth_signer.address, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)

    async def _fx_quote(*_args, **_kwargs):
        return FxQuoteResponse(zen_usd=Decimal("1.25"), stale=False, received_at=None)

    monkeypatch.setattr("app.routes.pricing.fetch_fx_quote", _fx_quote)

    async def _ensure_market(_session, _market_id, _expected):
        return market.id, market.market_address, 1

    monkeypatch.setattr("app.routes.trade._ensure_market", _ensure_market)
    monkeypatch.setattr("app.routes.trade._ensure_market_or_create", _ensure_market)

    async def _next_ticket_id(*_args, **_kwargs):
        return 0

    monkeypatch.setattr("app.routes.trade._next_ticket_id_onchain", _next_ticket_id)

    async def _escrow_balance(_wallet: str):
        return 4242

    monkeypatch.setattr("app.routes.trade._fetch_escrow_balance", _escrow_balance)
    monkeypatch.setattr(
        "app.routes.trade.httpx.AsyncClient", lambda *args, **kwargs: _AsyncClientStub({"txHash": "0xabc"})
    )

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

    commit_resp = client.post("/trade/commit", json={"quote_id": quote["quote_id"]})
    assert commit_resp.status_code == 200
    commit_body = commit_resp.json()
    assert commit_body["tx_hash"] == "0xabc"
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
    assert pos["tx_hash"] == "0xabc"


def test_trade_claim_rebuilds_merkle_path(client, db_session, monkeypatch):
    user = Account.create()
    market = _seed_market(db_session, event_id="claim-mkt", address="0x4444444444444444444444444444444444444444")
    commitment_hex = "0x" + "11" * 32
    leaf_bytes = bytes.fromhex(commitment_hex[2:])
    # Single-leaf tree hashes leaf with itself.
    merkle_root = Web3.keccak(leaf_bytes + leaf_bytes).hex()

    db_session.add(
        models.Commitment(
            market_id=market.id,
            user_address=user.address.lower(),
            outcome_id=0,
            amount_wei=100,
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
            proof_status=models.SettlementProofStatus.NONE.value,
            created_at=datetime.now(tz=UTC),
        )
    )
    db_session.commit()

    settings = runtime.settings
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(
        "app.routes.trade.httpx.AsyncClient", lambda *args, **kwargs: _AsyncClientStub({"txHash": "0xclaim"})
    )

    resp = client.post(
        "/trade/claim",
        json={
            "market_id": market.event_id,
            "wallet_address": user.address,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tx_hash"] == "0xclaim"
    assert body["ticket_id"] == 0
    assert body["status"] == "claimed"


def test_claim_bundles_return_winning_ticket(client, db_session):
    user = Account.create()
    market = _seed_market(db_session, event_id="bundle-mkt", address="0x6666666666666666666666666666666666666666")
    commitment_hex = "0x" + "33" * 32
    leaf_bytes = bytes.fromhex(commitment_hex[2:])
    merkle_root = Web3.keccak(leaf_bytes + leaf_bytes).hex()

    db_session.add(
        models.Commitment(
            market_id=market.id,
            user_address=user.address.lower(),
            outcome_id=1,
            amount_wei=200,
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
            proof_status=models.SettlementProofStatus.NONE.value,
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
    bundle = body["bundles"][0]
    assert bundle["marketId"] == market.event_id
    assert bundle["ticketId"] == 0
    assert bundle["amountWei"] == 200
    assert bundle["merkleProof"] == []
    assert bundle["commitmentsRoot"].lower() == merkle_root.lower()
    assert bundle["user"].lower() == user.address.lower()


def test_sync_commitments_endpoint(client, db_session):
    market = _seed_market(db_session, event_id="sync-mkt", address="0x5555555555555555555555555555555555555555")
    payload = {
        "event_id": market.event_id,
        "tickets": [
            {
                "ticketHash": "0x" + "22" * 32,
                "leaf": "0x" + "22" * 32,
                "user_address": "0xabc",
                "outcomeId": 1,
                "amount": 100,
                "salt": "0x0",
                "merkleIndex": 0,
                "merklePath": [],
            }
        ],
    }
    resp = client.post("/commitments/sync", json=payload)
    assert resp.status_code == 200
    assert resp.json()["recorded"] == 1


def test_ingest_settlement_endpoint(client, db_session):
    market = _seed_market(db_session, event_id="settle-mkt", address="0x6666666666666666666666666666666666666666")
    payload = {
        "event_id": market.event_id,
        "merkleRoot": "0x" + "33" * 32,
        "commitmentsCount": 1,
        "winningOutcomeId": 0,
        "rakeBps": 200,
        "totalEscrow": 100,
        "totalLiability": 100,
    }
    resp = client.post("/settlements/ingest", json=payload)
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

    # missing secret
    resp = client.post("/relayer/commitments", json={"event_id": market.event_id, "tickets": []})
    assert resp.status_code == 401

    resp_ok = client.post(
        "/relayer/commitments",
        headers={"X-Relayer-Secret": "secret"},
        json={"event_id": market.event_id, "tickets": []},
    )
    assert resp_ok.status_code == 200
