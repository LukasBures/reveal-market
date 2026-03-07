"""Tests for the trade_commit endpoint — all validation branches, state mutations, and relayer integration."""

from __future__ import annotations

# ruff: noqa: S101
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal

import app.runtime as runtime
from app import models
from eth_account import Account
from eth_account.messages import encode_defunct
from pydantic import SecretStr

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_commit_market(
    db_session, event_id: str = "mkt-commit", address: str = "0x1111111111111111111111111111111111111111"
):
    """Seed a market open for commits (no resolution_status, no resolved_at)."""
    market = models.Market(
        event_id=event_id,
        title="Commit Test Market",
        oracle="0x1234",
        market_address=address,
        status=models.MarketStatusEnum.COMMIT.value,
    )
    db_session.add(market)
    db_session.commit()
    return market


def _seed_quote(
    db_session,
    quote_id: str = "q-commit-1",
    user_address: str = "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    market_id: str = "mkt-commit",
    market_address: str = "0x1111111111111111111111111111111111111111",
    chain_id: int = 2651420,
    expired: bool = False,
    stake_wei: int = 1_000_000_000_000_000_000,
):
    """Create a Quote row directly in the DB (bypass /pricing/quote endpoint)."""
    now = datetime.now(tz=UTC)
    expires = now - timedelta(seconds=10) if expired else now + timedelta(hours=1)
    payload = {
        "quote_id": quote_id,
        "market_id": market_id,
        "wallet_address": user_address,
        "market_address": market_address,
        "outcome_id": 0,
        "stake_wei": stake_wei,
        "stake_zen": 1.0,
        "payout_zen": 1.8,
        "zen_usd": 1.0,
        "zen_usd_scaled": 10000,
        "chain_id": chain_id,
        "expires_at": expires.isoformat(),
        "expiry_ts": int(expires.timestamp()),
        "displayed_odds_multiplier": 1.8,
        "rake_zen": 0.01,
        "refund_zen": 0.0,
        "hedge_usdc": 0.0,
        "haircut_percent": 0.12,
        "worsen_percent": 0.05,
        "rake_percent": 0.01,
        "total_monetization": 0.0,
    }
    quote = models.Quote(
        quote_id=quote_id,
        status="issued",
        payload=payload,
        stake_zen=Decimal("1.0"),
        stake_wei=Decimal(stake_wei),
        fx_scaled=10000,
        zen_usd=Decimal("1.0"),
        market_id=market_id,
        market_address=market_address,
        wallet_address=user_address.lower(),
        outcome_id=0,
        chain_id=chain_id,
        expires_at=expires,
    )
    db_session.add(quote)
    db_session.commit()
    return quote


def _build_commit_message(quote_payload: dict, wallet: str) -> str:
    """Reconstruct the human-readable commit signature message."""

    def _fmt(value, places: int = 4) -> str:
        if value is None:
            return "n/a"
        quant = Decimal("1").scaleb(-places)
        quantized = Decimal(str(value)).quantize(quant, rounding=ROUND_DOWN)
        result = format(quantized, "f")
        if "." not in result:
            result += "." + "0" * places
        else:
            int_part, frac_part = result.split(".", 1)
            result = f"{int_part}.{frac_part.ljust(places, '0')}"
        return result

    return "\n".join(
        [
            "RevealMarket Buy Confirmation",
            "",
            f"Market ID: {quote_payload.get('market_id') or 'n/a'}",
            f"Outcome ID: {int(quote_payload['outcome_id'])}",
            f"You pay: {_fmt(quote_payload.get('stake_zen'))} ZEN",
            f"You can win: {_fmt(quote_payload.get('payout_zen'))} ZEN",
            f"Quote ID: {quote_payload.get('quote_id') or ''}",
            f"Wallet: {wallet.lower()}",
            "",
            "By signing, you authorize RevealMarket to submit this buy.",
        ]
    )


def _setup_commit_mocks(
    monkeypatch,
    settings,
    market_id: int,
    market_address: str,
    market_onchain_id: int = 1,
):
    """Patch all RPC-dependent functions so commit can reach the relayer call."""
    auth_signer = Account.create()
    monkeypatch.setattr(
        settings,
        "authorization_signer_private_key",
        SecretStr(auth_signer._private_key.hex()),
        raising=False,
    )
    monkeypatch.setattr(settings, "authorization_signer", auth_signer.address, raising=False)

    async def _ensure_market(_session, _mid, _addr, *, allow_create=False):
        return market_id, market_address, market_onchain_id

    async def _sync_factory(*_a, **_kw):
        return 0

    async def _next_ticket(*_a, **_kw):
        return 0

    async def _reserve_ticket(_addr, tentative):
        return tentative

    async def _escrow(*_a, **_kw):
        return None

    async def _assert_pool(*_a, **_kw):
        return None

    def _assert_commits(*_a, **_kw):
        pass  # synchronous, always allow

    async def _pricing_submit(*_a, **_kw):
        return None

    def _sign_quote(q):
        # Bypass the hex quote_id requirement in EIP-712 signing; tests don't test this layer.
        q.signature = "0x" + "ab" * 65
        return q

    monkeypatch.setattr("app.routes.trade._ensure_market_or_create", _ensure_market)
    monkeypatch.setattr("app.routes.trade._sync_market_factory_params", _sync_factory)
    monkeypatch.setattr("app.routes.trade._next_ticket_id_onchain", _next_ticket)
    monkeypatch.setattr("app.routes.trade._reserve_ticket_id", _reserve_ticket)
    monkeypatch.setattr("app.routes.trade._fetch_escrow_balance", _escrow)
    monkeypatch.setattr("app.routes.trade._assert_protocol_pool_headroom", _assert_pool)
    monkeypatch.setattr("app.routes.trade._sign_quote_for_commit", _sign_quote)
    monkeypatch.setattr("app.routes.pricing._assert_commits_allowed", _assert_commits)
    monkeypatch.setattr("app.routes.pricing.pricing_submit", _pricing_submit)

    return auth_signer


class _AsyncClientStub:
    """Minimal httpx.AsyncClient stub for relayer HTTP mocking."""

    def __init__(self, payload: dict, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code
        self.text = "ok"

    async def post(self, *_args, **_kwargs):
        return self

    def json(self):
        return self.payload


# ---------------------------------------------------------------------------
# Group A: Input Validation — fail before _ensure_market_or_create
# ---------------------------------------------------------------------------


def test_commit_rejects_missing_wallet_signature(client, db_session):
    """No X-Wallet-Signature header → 401 wallet_signature_required."""
    _seed_commit_market(db_session)
    _seed_quote(db_session, quote_id="q-no-sig")

    # Empty string is falsy → treated as missing
    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-no-sig"},
        headers={"X-Wallet-Signature": ""},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "wallet_signature_required"


def test_commit_rejects_relayer_unconfigured(client, db_session, monkeypatch):
    """No relayer_base_url → 503 relayer_unconfigured."""
    auth_signer = Account.create()
    settings = runtime.settings
    monkeypatch.setattr(
        settings,
        "authorization_signer_private_key",
        SecretStr(auth_signer._private_key.hex()),
        raising=False,
    )
    monkeypatch.setattr(settings, "relayer_base_url", "", raising=False)
    _seed_commit_market(db_session, event_id="mkt-no-relay")
    _seed_quote(db_session, quote_id="q-no-relayer", market_id="mkt-no-relay")

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-no-relayer"},
        headers={"X-Wallet-Signature": "0xdeadbeef"},
    )
    assert resp.status_code == 503
    assert resp.json()["detail"] == "relayer_unconfigured"


def test_commit_rejects_expired_quote(client, db_session, monkeypatch):
    """Expired quote → 400 quote_expired."""
    auth_signer = Account.create()
    settings = runtime.settings
    monkeypatch.setattr(
        settings,
        "authorization_signer_private_key",
        SecretStr(auth_signer._private_key.hex()),
        raising=False,
    )
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    _seed_commit_market(db_session, event_id="mkt-expired")
    _seed_quote(db_session, quote_id="q-expired", market_id="mkt-expired", expired=True)

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-expired"},
        headers={"X-Wallet-Signature": "0xdeadbeef"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "quote_expired"


def test_commit_rejects_wrong_chain_id(client, db_session, monkeypatch):
    """Quote chain_id != settings.pricing_chain_id → 400 quote_chain_mismatch."""
    auth_signer = Account.create()
    settings = runtime.settings
    monkeypatch.setattr(
        settings,
        "authorization_signer_private_key",
        SecretStr(auth_signer._private_key.hex()),
        raising=False,
    )
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    _seed_commit_market(db_session, event_id="mkt-chain")
    _seed_quote(db_session, quote_id="q-wrong-chain", market_id="mkt-chain", chain_id=1)

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-wrong-chain"},
        headers={"X-Wallet-Signature": "0xdeadbeef"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "quote_chain_mismatch"


def test_commit_rejects_stake_mismatch(client, db_session, monkeypatch):
    """Quote stake_wei != settings.ticket_size_wei → 400 stake_mismatch."""
    auth_signer = Account.create()
    settings = runtime.settings
    monkeypatch.setattr(
        settings,
        "authorization_signer_private_key",
        SecretStr(auth_signer._private_key.hex()),
        raising=False,
    )
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 5_000_000_000_000_000_000, raising=False)
    _seed_commit_market(db_session, event_id="mkt-stake")
    _seed_quote(db_session, quote_id="q-stake-mismatch", market_id="mkt-stake", stake_wei=1_000_000_000_000_000_000)

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-stake-mismatch"},
        headers={"X-Wallet-Signature": "0xdeadbeef"},
    )
    assert resp.status_code == 400
    assert "stake_mismatch_expected_" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Group B: Quote Lock (TOCTOU)
# ---------------------------------------------------------------------------


def test_commit_quote_lock_prevents_double_consumption(client, db_session):
    """Pre-set quote lock key in cache → 409 quote_already_consumed."""
    _seed_commit_market(db_session)
    _seed_quote(db_session, quote_id="q-double-lock")

    # Pre-set the lock that trade_commit checks via NX
    cache = runtime.cache_client
    cache.store["quote:lock:q-double-lock"] = "1"

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-double-lock"},
        headers={"X-Wallet-Signature": "0xdeadbeef"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "quote_already_consumed"


# ---------------------------------------------------------------------------
# Group C: Escrow
# ---------------------------------------------------------------------------


def test_commit_rejects_escrow_insufficient(client, db_session, monkeypatch):
    """Escrow balance < stake → 400 insufficient_escrow_balance."""
    user = Account.create()
    market = _seed_commit_market(db_session, event_id="mkt-escrow")
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(
        settings,
        "relayer_escrow_address",
        "0xEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE",
        raising=False,
    )
    _setup_commit_mocks(monkeypatch, settings, market.id, market.market_address)

    async def _low_escrow(_wallet):
        return 100  # way below stake_wei

    monkeypatch.setattr("app.routes.trade._fetch_escrow_balance", _low_escrow)

    quote = _seed_quote(
        db_session,
        quote_id="q-escrow-low",
        user_address=user.address,
        market_id="mkt-escrow",
        market_address=market.market_address,
    )
    sig = Account.sign_message(
        encode_defunct(text=_build_commit_message(quote.payload, user.address)),
        user._private_key,
    ).signature.hex()

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-escrow-low"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "insufficient_escrow_balance"


# ---------------------------------------------------------------------------
# Group D: Relayer Integration
# ---------------------------------------------------------------------------


def test_commit_returns_tx_hash_from_relayer(client, db_session, monkeypatch):
    """Relayer returns txHash → response contains correct tx_hash."""
    user = Account.create()
    tx_hash = "0x" + "a" * 64
    market = _seed_commit_market(db_session, event_id="mkt-tx-hash")
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "relayer_escrow_address", None, raising=False)
    _setup_commit_mocks(monkeypatch, settings, market.id, market.market_address)

    async def _http(*_a, **_kw):
        return _AsyncClientStub({"txHash": tx_hash})

    monkeypatch.setattr("app.routes.trade.get_http_client", _http)

    quote = _seed_quote(
        db_session,
        quote_id="q-tx-hash",
        user_address=user.address,
        market_id="mkt-tx-hash",
        market_address=market.market_address,
    )
    sig = Account.sign_message(
        encode_defunct(text=_build_commit_message(quote.payload, user.address)),
        user._private_key,
    ).signature.hex()

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-tx-hash"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp.status_code == 200
    assert resp.json()["tx_hash"] == tx_hash


def test_commit_returns_job_id_when_relayer_queues(client, db_session, monkeypatch):
    """Relayer returns job_id with 202 → job_id used as tx_hash fallback."""
    user = Account.create()
    market = _seed_commit_market(db_session, event_id="mkt-job")
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "relayer_escrow_address", None, raising=False)
    _setup_commit_mocks(monkeypatch, settings, market.id, market.market_address)

    async def _http(*_a, **_kw):
        return _AsyncClientStub({"job_id": "my-job-123"}, status_code=202)

    monkeypatch.setattr("app.routes.trade.get_http_client", _http)

    quote = _seed_quote(
        db_session,
        quote_id="q-job",
        user_address=user.address,
        market_id="mkt-job",
        market_address=market.market_address,
    )
    sig = Account.sign_message(
        encode_defunct(text=_build_commit_message(quote.payload, user.address)),
        user._private_key,
    ).signature.hex()

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-job"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tx_hash"] == "my-job-123"
    assert body["relayer_job_id"] == "my-job-123"


def test_commit_enqueues_when_relayer_fails_and_queue_enabled(client, db_session, monkeypatch):
    """Relayer failure + queue_enabled → _enqueue_relayer_job called, response has queued status."""
    user = Account.create()
    market = _seed_commit_market(db_session, event_id="mkt-enqueue")
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "relayer_escrow_address", None, raising=False)
    monkeypatch.setattr(settings, "relayer_queue_enabled", True, raising=False)
    _setup_commit_mocks(monkeypatch, settings, market.id, market.market_address)

    async def _http(*_a, **_kw):
        return _AsyncClientStub({}, status_code=502)

    monkeypatch.setattr("app.routes.trade.get_http_client", _http)

    enqueued_jobs = []

    async def _mock_enqueue(kind, endpoint, payload):
        enqueued_jobs.append({"kind": kind, "endpoint": endpoint})
        return "job-queued-abc"

    monkeypatch.setattr("app.routes.trade._enqueue_relayer_job", _mock_enqueue)

    quote = _seed_quote(
        db_session,
        quote_id="q-enqueue",
        user_address=user.address,
        market_id="mkt-enqueue",
        market_address=market.market_address,
    )
    sig = Account.sign_message(
        encode_defunct(text=_build_commit_message(quote.payload, user.address)),
        user._private_key,
    ).signature.hex()

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-enqueue"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["relayer_status"] == "queued"
    assert len(enqueued_jobs) == 1
    assert enqueued_jobs[0]["kind"] == "commit"


def test_commit_raises_502_when_relayer_fails_and_queue_disabled(client, db_session, monkeypatch):
    """Relayer failure + queue_disabled → 502 propagated."""
    user = Account.create()
    market = _seed_commit_market(db_session, event_id="mkt-502")
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "relayer_escrow_address", None, raising=False)
    monkeypatch.setattr(settings, "relayer_queue_enabled", False, raising=False)
    _setup_commit_mocks(monkeypatch, settings, market.id, market.market_address)

    async def _http(*_a, **_kw):
        return _AsyncClientStub({"detail": "down"}, status_code=500)

    monkeypatch.setattr("app.routes.trade.get_http_client", _http)

    quote = _seed_quote(
        db_session,
        quote_id="q-502",
        user_address=user.address,
        market_id="mkt-502",
        market_address=market.market_address,
    )
    sig = Account.sign_message(
        encode_defunct(text=_build_commit_message(quote.payload, user.address)),
        user._private_key,
    ).signature.hex()

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-502"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp.status_code == 502


# ---------------------------------------------------------------------------
# Group E: State Mutations
# ---------------------------------------------------------------------------


def test_commit_persists_commitment_to_db(client, db_session, monkeypatch):
    """After successful commit, Commitment row written with correct fields."""
    from sqlalchemy import select

    user = Account.create()
    tx_hash = "0x" + "c" * 64
    market = _seed_commit_market(db_session, event_id="mkt-persist")
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "relayer_escrow_address", None, raising=False)
    _setup_commit_mocks(monkeypatch, settings, market.id, market.market_address)

    async def _http(*_a, **_kw):
        return _AsyncClientStub({"txHash": tx_hash})

    monkeypatch.setattr("app.routes.trade.get_http_client", _http)

    quote = _seed_quote(
        db_session,
        quote_id="q-persist",
        user_address=user.address,
        market_id="mkt-persist",
        market_address=market.market_address,
    )
    sig = Account.sign_message(
        encode_defunct(text=_build_commit_message(quote.payload, user.address)),
        user._private_key,
    ).signature.hex()

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-persist"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp.status_code == 200

    commitments = (
        db_session.execute(select(models.Commitment).where(models.Commitment.market_id == market.id)).scalars().all()
    )
    assert len(commitments) == 1
    c = commitments[0]
    assert c.user_address.lower() == user.address.lower()
    assert c.outcome_id == 0
    assert c.leaf_index == 0
    assert c.tx_hash is not None


def test_commit_persists_salt_within_field_modulus(client, db_session, monkeypatch):
    """Salt stored in commitment is a valid BN254 field element."""
    from shared.poseidon import FIELD_MODULUS

    user = Account.create()
    market = _seed_commit_market(db_session, event_id="mkt-salt")
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "relayer_escrow_address", None, raising=False)
    _setup_commit_mocks(monkeypatch, settings, market.id, market.market_address)

    async def _http(*_a, **_kw):
        return _AsyncClientStub({"txHash": "0x" + "d" * 64})

    monkeypatch.setattr("app.routes.trade.get_http_client", _http)

    quote = _seed_quote(
        db_session,
        quote_id="q-salt",
        user_address=user.address,
        market_id="mkt-salt",
        market_address=market.market_address,
    )
    sig = Account.sign_message(
        encode_defunct(text=_build_commit_message(quote.payload, user.address)),
        user._private_key,
    ).signature.hex()

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-salt"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp.status_code == 200
    salt_int = int(resp.json()["salt"], 16)
    assert salt_int < FIELD_MODULUS


def test_commit_response_includes_required_fields(client, db_session, monkeypatch):
    """Response contains tx_hash, quote_id, ticket_id, salt, status=committed."""
    user = Account.create()
    market = _seed_commit_market(db_session, event_id="mkt-fields")
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "relayer_escrow_address", None, raising=False)
    _setup_commit_mocks(monkeypatch, settings, market.id, market.market_address)

    async def _http(*_a, **_kw):
        return _AsyncClientStub({"txHash": "0x" + "e" * 64})

    monkeypatch.setattr("app.routes.trade.get_http_client", _http)

    quote = _seed_quote(
        db_session,
        quote_id="q-fields",
        user_address=user.address,
        market_id="mkt-fields",
        market_address=market.market_address,
    )
    sig = Account.sign_message(
        encode_defunct(text=_build_commit_message(quote.payload, user.address)),
        user._private_key,
    ).signature.hex()

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-fields"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "tx_hash" in body
    assert body["quote_id"] == "q-fields"
    assert "ticket_id" in body
    assert body["salt"].startswith("0x")
    assert body["status"] == "committed"


# ---------------------------------------------------------------------------
# Group F: Market State Validation
# ---------------------------------------------------------------------------


def test_commit_rejects_market_settled(client, db_session, monkeypatch):
    """Market with resolved_at set → 400 market_settled."""
    user = Account.create()
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "relayer_escrow_address", None, raising=False)

    market = models.Market(
        event_id="mkt-settled-chk",
        title="Settled Market",
        oracle="0x1234",
        market_address="0x2222222222222222222222222222222222222222",
        status=models.MarketStatusEnum.SETTLED.value,
        resolved_at=datetime.now(tz=UTC),  # resolved → should block commits
    )
    db_session.add(market)
    db_session.commit()

    _setup_commit_mocks(monkeypatch, settings, market.id, market.market_address)

    quote = _seed_quote(
        db_session,
        quote_id="q-settled-chk",
        user_address=user.address,
        market_id="mkt-settled-chk",
        market_address=market.market_address,
    )
    sig = Account.sign_message(
        encode_defunct(text=_build_commit_message(quote.payload, user.address)),
        user._private_key,
    ).signature.hex()

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-settled-chk"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "market_settled"


def test_commit_rejects_invalid_wallet_signature(client, db_session, monkeypatch):
    """Signature from wrong key → 401 wallet_signature_mismatch."""
    user = Account.create()
    wrong_key = Account.create()
    market = _seed_commit_market(db_session, event_id="mkt-bad-sig")
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "relayer_escrow_address", None, raising=False)
    _setup_commit_mocks(monkeypatch, settings, market.id, market.market_address)

    quote = _seed_quote(
        db_session,
        quote_id="q-bad-sig",
        user_address=user.address,
        market_id="mkt-bad-sig",
        market_address=market.market_address,
    )
    # Sign the correct message but with the WRONG key
    sig = Account.sign_message(
        encode_defunct(text=_build_commit_message(quote.payload, user.address)),
        wrong_key._private_key,
    ).signature.hex()

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-bad-sig"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp.status_code == 401


def test_commit_rejects_market_cancelled(client, db_session, monkeypatch):
    """Market.status = 'cancelled' → 400 market_settled (same error as settled)."""
    user = Account.create()
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "relayer_escrow_address", None, raising=False)

    market = models.Market(
        event_id="mkt-cancelled",
        title="Cancelled Market",
        oracle="0x1234",
        market_address="0x3333333333333333333333333333333333333333",
        status=models.MarketStatusEnum.CANCELLED.value,
    )
    db_session.add(market)
    db_session.commit()

    _setup_commit_mocks(monkeypatch, settings, market.id, market.market_address)

    quote = _seed_quote(
        db_session,
        quote_id="q-cancelled",
        user_address=user.address,
        market_id="mkt-cancelled",
        market_address=market.market_address,
    )
    sig = Account.sign_message(
        encode_defunct(text=_build_commit_message(quote.payload, user.address)),
        user._private_key,
    ).signature.hex()

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-cancelled"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "market_settled"


def test_commit_rejects_market_onchain_id_none(client, db_session, monkeypatch):
    """_ensure_market_or_create returns onchain_id=None → 503 market_onchain_id_unavailable."""
    user = Account.create()
    market = _seed_commit_market(db_session, event_id="mkt-no-onchain")
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "relayer_escrow_address", None, raising=False)

    _setup_commit_mocks(monkeypatch, settings, market.id, market.market_address, market_onchain_id=None)

    quote = _seed_quote(
        db_session,
        quote_id="q-no-onchain",
        user_address=user.address,
        market_id="mkt-no-onchain",
        market_address=market.market_address,
    )
    sig = Account.sign_message(
        encode_defunct(text=_build_commit_message(quote.payload, user.address)),
        user._private_key,
    ).signature.hex()

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-no-onchain"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp.status_code == 503
    assert resp.json()["detail"] == "market_onchain_id_unavailable"


# ---------------------------------------------------------------------------
# Group B (Escrow) continued
# ---------------------------------------------------------------------------


def test_commit_rejects_escrow_check_unavailable(client, db_session, monkeypatch):
    """relayer_escrow_address set but escrow fetch returns None → 503 escrow_balance_unavailable."""
    user = Account.create()
    market = _seed_commit_market(db_session, event_id="mkt-escrow-unav")
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    # Escrow address is configured → check will run
    monkeypatch.setattr(
        settings,
        "relayer_escrow_address",
        "0xEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE",
        raising=False,
    )
    # _setup_commit_mocks patches _fetch_escrow_balance to return None by default
    _setup_commit_mocks(monkeypatch, settings, market.id, market.market_address)

    quote = _seed_quote(
        db_session,
        quote_id="q-escrow-unav",
        user_address=user.address,
        market_id="mkt-escrow-unav",
        market_address=market.market_address,
    )
    sig = Account.sign_message(
        encode_defunct(text=_build_commit_message(quote.payload, user.address)),
        user._private_key,
    ).signature.hex()

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-escrow-unav"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp.status_code == 503
    assert resp.json()["detail"] == "escrow_balance_unavailable"


def test_commit_skips_escrow_when_check_disabled(client, db_session, monkeypatch):
    """relayer_escrow_address=None means escrow check is skipped; commit proceeds."""
    user = Account.create()
    market = _seed_commit_market(db_session, event_id="mkt-escrow-skip")
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "relayer_escrow_address", None, raising=False)  # check disabled
    _setup_commit_mocks(monkeypatch, settings, market.id, market.market_address)

    async def _http(*_a, **_kw):
        return _AsyncClientStub({"txHash": "0x" + "a" * 64})

    monkeypatch.setattr("app.routes.trade.get_http_client", _http)

    quote = _seed_quote(
        db_session,
        quote_id="q-escrow-skip",
        user_address=user.address,
        market_id="mkt-escrow-skip",
        market_address=market.market_address,
    )
    sig = Account.sign_message(
        encode_defunct(text=_build_commit_message(quote.payload, user.address)),
        user._private_key,
    ).signature.hex()

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-escrow-skip"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Group C (Quote Lock) continued
# ---------------------------------------------------------------------------


def test_commit_quote_lock_persists_after_failure(client, db_session, monkeypatch):
    """After relayer failure (502), quote lock remains set; immediate retry gets 409."""
    user = Account.create()
    market = _seed_commit_market(db_session, event_id="mkt-lock-fail")
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "relayer_escrow_address", None, raising=False)
    monkeypatch.setattr(settings, "relayer_queue_enabled", False, raising=False)
    _setup_commit_mocks(monkeypatch, settings, market.id, market.market_address)

    async def _http(*_a, **_kw):
        return _AsyncClientStub({}, status_code=500)

    monkeypatch.setattr("app.routes.trade.get_http_client", _http)

    quote = _seed_quote(
        db_session,
        quote_id="q-lock-fail",
        user_address=user.address,
        market_id="mkt-lock-fail",
        market_address=market.market_address,
    )
    sig = Account.sign_message(
        encode_defunct(text=_build_commit_message(quote.payload, user.address)),
        user._private_key,
    ).signature.hex()

    resp1 = client.post(
        "/trade/commit",
        json={"quote_id": "q-lock-fail"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp1.status_code == 502

    # Lock was set on first call and not released; second attempt hits it
    resp2 = client.post(
        "/trade/commit",
        json={"quote_id": "q-lock-fail"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp2.status_code == 409
    assert resp2.json()["detail"] == "quote_already_consumed"


# ---------------------------------------------------------------------------
# Group D (Relayer) continued
# ---------------------------------------------------------------------------


def test_commit_relayer_retries_on_503(client, db_session, monkeypatch):
    """First relayer call returns 503; second attempt returns 200 → commit succeeds."""
    user = Account.create()
    tx_hash = "0x" + "b" * 64
    market = _seed_commit_market(db_session, event_id="mkt-retry")
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "relayer_escrow_address", None, raising=False)
    monkeypatch.setattr(settings, "relayer_retry_attempts", 1, raising=False)  # total = 2
    monkeypatch.setattr(settings, "relayer_retry_backoff_seconds", 0.0, raising=False)
    _setup_commit_mocks(monkeypatch, settings, market.id, market.market_address)

    call_count = [0]

    class _RetryStub:
        def __init__(self, call_num: int):
            self._call_num = call_num

        async def post(self, *_a, **_kw):
            return self

        @property
        def status_code(self):
            return 503 if self._call_num == 0 else 200

        def json(self):
            return {} if self._call_num == 0 else {"txHash": tx_hash}

        @property
        def text(self):
            return "error" if self._call_num == 0 else "ok"

    async def _http(*_a, **_kw):
        stub = _RetryStub(call_count[0])
        call_count[0] += 1
        return stub

    monkeypatch.setattr("app.routes.trade.get_http_client", _http)

    quote = _seed_quote(
        db_session,
        quote_id="q-retry-503",
        user_address=user.address,
        market_id="mkt-retry",
        market_address=market.market_address,
    )
    sig = Account.sign_message(
        encode_defunct(text=_build_commit_message(quote.payload, user.address)),
        user._private_key,
    ).signature.hex()

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-retry-503"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp.status_code == 200
    assert resp.json()["tx_hash"] == tx_hash
    assert call_count[0] == 2  # one 503, one 200


# ---------------------------------------------------------------------------
# Group E (State Mutations) continued
# ---------------------------------------------------------------------------


def test_commit_ticket_id_monotonically_increases(client, db_session, monkeypatch):
    """Two successive commits return ticket_ids 0 and 1 respectively."""
    user = Account.create()
    market = _seed_commit_market(db_session, event_id="mkt-tickets")
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "relayer_escrow_address", None, raising=False)
    _setup_commit_mocks(monkeypatch, settings, market.id, market.market_address)

    counter = [0]

    async def _counting_ticket(*_a, **_kw):
        val = counter[0]
        counter[0] += 1
        return val

    monkeypatch.setattr("app.routes.trade._next_ticket_id_onchain", _counting_ticket)

    async def _http(*_a, **_kw):
        return _AsyncClientStub({"txHash": "0x" + "f" * 64})

    monkeypatch.setattr("app.routes.trade.get_http_client", _http)

    results = []
    for i in range(2):
        quote = _seed_quote(
            db_session,
            quote_id=f"q-tickets-{i}",
            user_address=user.address,
            market_id="mkt-tickets",
            market_address=market.market_address,
        )
        sig = Account.sign_message(
            encode_defunct(text=_build_commit_message(quote.payload, user.address)),
            user._private_key,
        ).signature.hex()
        resp = client.post(
            "/trade/commit",
            json={"quote_id": f"q-tickets-{i}"},
            headers={"X-Wallet-Signature": sig},
        )
        assert resp.status_code == 200
        results.append(resp.json()["ticket_id"])

    assert results == [0, 1]


def test_commit_updates_quote_market_address_when_differs(client, db_session, monkeypatch):
    """When resolved market_address differs from quote.market_address, the DB quote is updated."""
    from sqlalchemy import select

    user = Account.create()
    old_address = "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    new_address = "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
    market = _seed_commit_market(db_session, event_id="mkt-addr-update", address=old_address)
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "relayer_escrow_address", None, raising=False)

    # _ensure_market_or_create returns a different address than what's in the quote
    _setup_commit_mocks(monkeypatch, settings, market.id, new_address)

    async def _http(*_a, **_kw):
        return _AsyncClientStub({"txHash": "0x" + "e" * 64})

    monkeypatch.setattr("app.routes.trade.get_http_client", _http)

    quote = _seed_quote(
        db_session,
        quote_id="q-addr-update",
        user_address=user.address,
        market_id="mkt-addr-update",
        market_address=old_address,
    )
    sig = Account.sign_message(
        encode_defunct(text=_build_commit_message(quote.payload, user.address)),
        user._private_key,
    ).signature.hex()

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-addr-update"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp.status_code == 200

    db_session.expire_all()
    updated = db_session.execute(select(models.Quote).where(models.Quote.quote_id == "q-addr-update")).scalar_one()
    assert updated.market_address.lower() == new_address.lower()


def test_commit_nonce_recorded_for_idempotency(client, db_session, monkeypatch):
    """After a successful commit, retrying the same quote_id gets 409 (lock persists)."""
    user = Account.create()
    market = _seed_commit_market(db_session, event_id="mkt-nonce")
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "relayer_escrow_address", None, raising=False)
    _setup_commit_mocks(monkeypatch, settings, market.id, market.market_address)

    async def _http(*_a, **_kw):
        return _AsyncClientStub({"txHash": "0x" + "c" * 64})

    monkeypatch.setattr("app.routes.trade.get_http_client", _http)

    quote = _seed_quote(
        db_session,
        quote_id="q-nonce",
        user_address=user.address,
        market_id="mkt-nonce",
        market_address=market.market_address,
    )
    sig = Account.sign_message(
        encode_defunct(text=_build_commit_message(quote.payload, user.address)),
        user._private_key,
    ).signature.hex()

    # First call succeeds
    resp1 = client.post(
        "/trade/commit",
        json={"quote_id": "q-nonce"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp1.status_code == 200

    # Second call with same quote_id → lock prevents reuse
    resp2 = client.post(
        "/trade/commit",
        json={"quote_id": "q-nonce"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp2.status_code == 409
    assert resp2.json()["detail"] == "quote_already_consumed"


# ---------------------------------------------------------------------------
# Group F (Auth Signature) continued
# ---------------------------------------------------------------------------


def test_commit_auth_digest_uses_market_onchain_id(client, db_session, monkeypatch):
    """Auth digest is built with market_onchain_id=42; signature recovers the expected signer."""
    from web3 import Web3

    user = Account.create()
    market = _seed_commit_market(db_session, event_id="mkt-onchain-id")
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "relayer_escrow_address", None, raising=False)

    ONCHAIN_ID = 42
    auth_signer = _setup_commit_mocks(
        monkeypatch, settings, market.id, market.market_address, market_onchain_id=ONCHAIN_ID
    )

    captured: list[dict] = []

    async def _mock_call_relayer(endpoint: str, payload: dict):
        captured.append(payload)
        return {"txHash": "0x" + "f" * 64}

    monkeypatch.setattr("app.routes.trade.call_relayer", _mock_call_relayer)

    quote = _seed_quote(
        db_session,
        quote_id="q-onchain-id",
        user_address=user.address,
        market_id="mkt-onchain-id",
        market_address=market.market_address,
    )
    sig = Account.sign_message(
        encode_defunct(text=_build_commit_message(quote.payload, user.address)),
        user._private_key,
    ).signature.hex()

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-onchain-id"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp.status_code == 200
    assert len(captured) == 1

    # Reconstruct auth_digest and verify the signer used ONCHAIN_ID=42
    payload = captured[0]
    ticket_size_wei = 1_000_000_000_000_000_000
    auth_digest = Web3.solidity_keccak(
        ["address", "uint256", "uint256", "bytes32", "address", "uint256", "uint256", "uint256", "uint256"],
        [
            Web3.to_checksum_address(payload["market"]),
            ONCHAIN_ID,
            payload["ticket_id"],
            bytes.fromhex(payload["commitment"][2:]),
            Web3.to_checksum_address(payload["user"]),
            payload["nonce"],
            payload["expiry"],
            ticket_size_wei,
            2651420,
        ],
    )
    recovered = Account.recover_message(
        encode_defunct(hexstr=auth_digest.hex()),
        signature=bytes.fromhex(payload["signature"][2:]),
    )
    assert recovered.lower() == auth_signer.address.lower()


def test_commit_verifies_wallet_recovers_correct_address(client, db_session, monkeypatch):
    """user_A signing a message that names user_B's wallet is rejected as 401."""
    user_a = Account.create()
    user_b = Account.create()
    market = _seed_commit_market(db_session, event_id="mkt-wrong-user")
    settings = runtime.settings
    monkeypatch.setattr(settings, "pricing_chain_id", 2651420, raising=False)
    monkeypatch.setattr(settings, "ticket_size_wei", 1_000_000_000_000_000_000, raising=False)
    monkeypatch.setattr(settings, "relayer_base_url", "http://relayer", raising=False)
    monkeypatch.setattr(settings, "relayer_escrow_address", None, raising=False)
    _setup_commit_mocks(monkeypatch, settings, market.id, market.market_address)

    # Quote belongs to user_B
    quote = _seed_quote(
        db_session,
        quote_id="q-wrong-user",
        user_address=user_b.address,
        market_id="mkt-wrong-user",
        market_address=market.market_address,
    )
    # user_A signs a message for user_A's wallet → recovered address = user_A ≠ user_B
    sig = Account.sign_message(
        encode_defunct(text=_build_commit_message(quote.payload, user_a.address)),
        user_a._private_key,
    ).signature.hex()

    resp = client.post(
        "/trade/commit",
        json={"quote_id": "q-wrong-user"},
        headers={"X-Wallet-Signature": sig},
    )
    assert resp.status_code == 401
