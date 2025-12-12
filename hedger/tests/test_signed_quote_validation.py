from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.config import Settings
from app.service import HedgerService
from app.types import CommitEvent, OutcomeSide
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3


class _FxStub:
    def __init__(self, price: Decimal):
        self._quote = type("Q", (), {"zen_usd": price})

    async def get_quote(self):
        return self._quote


@pytest.mark.asyncio
async def test_validate_signed_quote_accepts_valid_signature(monkeypatch):
    signer = Account.create()
    user = Account.create()
    market_address = "0x" + "11" * 20
    quote_id = "0x" + "22" * 32
    stake_zen = Decimal("1.0")
    stake_wei = int(stake_zen * Decimal("1e18"))
    expiry_ts = int((datetime.now(tz=UTC) + timedelta(hours=1)).timestamp())
    chain_id = 1337
    outcome_id = 0
    fx_scaled = 100_000_000

    digest = Web3.solidity_keccak(
        [
            "string",
            "uint256",
            "address",
            "address",
            "uint256",
            "uint256",
            "uint256",
            "uint256",
            "bytes32",
        ],
        [
            "QUOTE_V1",
            chain_id,
            Web3.to_checksum_address(market_address),
            Web3.to_checksum_address(user.address),
            outcome_id,
            stake_wei,
            fx_scaled,
            expiry_ts,
            bytes.fromhex(quote_id.removeprefix("0x")),
        ],
    )
    signature = Account.sign_message(encode_defunct(hexstr=digest.hex()), signer.key).signature.hex()

    commit = CommitEvent(
        market_id="mkt-quote",
        stake_zen=stake_zen,
        direction=OutcomeSide.YES,
        market_address=market_address,
        wallet_address=user.address,
        outcome_id=outcome_id,
        quote={
            "quote_id": quote_id,
            "stake_wei": stake_wei,
            "zen_usd_scaled": fx_scaled,
            "expiry_ts": expiry_ts,
            "chain_id": chain_id,
            "market_address": market_address,
            "wallet_address": user.address,
            "outcome_id": outcome_id,
            "signature": signature,
        },
    )

    settings = Settings(
        vault_rpc_url="http://localhost:8545",
        vault_private_key="0x" + "01" * 32,
        vault_sender_address="0x" + "02" * 20,
        lp_vault_address="0x" + "03" * 20,
        pricing_signer_address=signer.address,
        database_url="sqlite+aiosqlite://",
    )
    service = HedgerService(settings)
    service.lock_manager = None
    monkeypatch.setattr(service, "fx_oracle", _FxStub(price=Decimal("1")))

    valid, reason = await service._validate_signed_quote(commit, commit.signed_quote)
    assert valid is True
    assert reason is None


@pytest.mark.asyncio
async def test_validate_signed_quote_rejects_stake_mismatch(monkeypatch):
    signer = Account.create()
    user = Account.create()
    market_address = "0x" + "aa" * 20
    quote_id = "0x" + "bb" * 32
    stake_zen = Decimal("1.5")
    stake_wei = int(Decimal("1.0") * Decimal("1e18"))  # quote is 1 ZEN but commit is 1.5
    expiry_ts = int((datetime.now(tz=UTC) + timedelta(hours=1)).timestamp())
    fx_scaled = 90_000_000
    chain_id = 1337
    outcome_id = 1

    digest = Web3.solidity_keccak(
        [
            "string",
            "uint256",
            "address",
            "address",
            "uint256",
            "uint256",
            "uint256",
            "uint256",
            "bytes32",
        ],
        [
            "QUOTE_V1",
            chain_id,
            Web3.to_checksum_address(market_address),
            Web3.to_checksum_address(user.address),
            outcome_id,
            stake_wei,
            fx_scaled,
            expiry_ts,
            bytes.fromhex(quote_id.removeprefix("0x")),
        ],
    )
    signature = Account.sign_message(encode_defunct(hexstr=digest.hex()), signer.key).signature.hex()

    commit = CommitEvent(
        market_id="mkt-quote",
        stake_zen=stake_zen,
        direction=OutcomeSide.NO,
        market_address=market_address,
        wallet_address=user.address,
        outcome_id=outcome_id,
        quote={
            "quote_id": quote_id,
            "stake_wei": stake_wei,
            "zen_usd_scaled": fx_scaled,
            "expiry_ts": expiry_ts,
            "chain_id": chain_id,
            "market_address": market_address,
            "wallet_address": user.address,
            "outcome_id": outcome_id,
            "signature": signature,
        },
    )
    settings = Settings(
        vault_rpc_url="http://localhost:8545",
        vault_private_key="0x" + "04" * 32,
        vault_sender_address="0x" + "05" * 20,
        lp_vault_address="0x" + "06" * 20,
        pricing_signer_address=signer.address,
        database_url="sqlite+aiosqlite://",
    )
    service = HedgerService(settings)
    service.lock_manager = None
    monkeypatch.setattr(service, "fx_oracle", _FxStub(price=Decimal("0.9")))

    valid, reason = await service._validate_signed_quote(commit, commit.signed_quote)
    assert valid is False
    assert reason == "quote_stake_mismatch"
