from __future__ import annotations

import secrets

import pytest
from relayer.config import RelayerConfig, load_config

REQUIRED = {
    "RPC_URL": "http://localhost:8545",
    "CHAIN_ID": "1",
    "RELAYER_PRIVATE_KEY": "0x" + "1" * 64,
    "RELAYER_ESCROW_ADDRESS": "0x" + "2" * 40,
    "RELAYER_HOST": "127.0.0.1",
    "RELAYER_PORT": "8000",
}


def _seed_env(monkeypatch, **overrides: str):
    for key, value in {**REQUIRED, **overrides}.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize("missing_key", REQUIRED.keys())
def test_load_config_requires_env(monkeypatch, missing_key):
    _seed_env(monkeypatch)
    monkeypatch.delenv(missing_key, raising=False)
    with pytest.raises(RuntimeError) as exc:
        load_config()
    assert missing_key in str(exc.value)


def test_load_config_uses_defaults(monkeypatch):
    _seed_env(monkeypatch)
    monkeypatch.delenv("RELAYER_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("RELAYER_MAX_BLOCK_AGE_SECONDS", raising=False)
    monkeypatch.delenv("RELAYER_MIN_BALANCE_WEI", raising=False)
    monkeypatch.delenv("RELAYER_MAX_RETRIES", raising=False)
    monkeypatch.delenv("RELAYER_RETRY_BACKOFF_SECONDS", raising=False)
    monkeypatch.delenv("RELAYER_TX_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("RELAYER_QUEUE_DB_PATH", raising=False)
    monkeypatch.delenv("RM_DATABASE_URL", raising=False)
    monkeypatch.delenv("RELAYER_QUEUE_POLL_SECONDS", raising=False)
    monkeypatch.delenv("RELAYER_QUEUE_MAX_ATTEMPTS", raising=False)
    monkeypatch.delenv("RELAYER_FEE_BUMP_PERCENT", raising=False)
    monkeypatch.delenv("RELAYER_MIN_ESCROW_TOKEN_BALANCE_WEI", raising=False)
    monkeypatch.delenv("RELAYER_MIN_RELAYER_TOKEN_ALLOWANCE_WEI", raising=False)
    monkeypatch.delenv("RELAYER_HTTP_TIMEOUT_SECONDS", raising=False)

    cfg = load_config()
    assert isinstance(cfg, RelayerConfig)
    assert cfg.bearer_token is None
    assert cfg.max_block_age_seconds == 60
    assert cfg.min_relayer_balance_wei == 0
    assert cfg.max_retries == 3
    assert cfg.retry_backoff_seconds == 0.5
    assert cfg.tx_timeout_seconds == 120
    assert cfg.queue_db_path == "relayer_queue.db"
    assert cfg.queue_dsn is None
    assert cfg.queue_poll_seconds == 1.0
    assert cfg.queue_max_attempts == 5
    assert cfg.fee_bump_percent == 0.15
    assert cfg.min_escrow_token_balance_wei == 0
    assert cfg.min_relayer_token_allowance_wei == 0
    assert cfg.http_timeout_seconds == 10


def test_load_config_applies_overrides(monkeypatch):
    token_value = secrets.token_hex(8)
    _seed_env(
        monkeypatch,
        RELAYER_MAX_BLOCK_AGE_SECONDS="10",
        RELAYER_MIN_BALANCE_WEI="5",
        RELAYER_MAX_RETRIES="9",
        RELAYER_RETRY_BACKOFF_SECONDS="1.2",
        RELAYER_TX_TIMEOUT_SECONDS="30",
        RELAYER_BEARER_TOKEN=<REDACTED>
        RELAYER_QUEUE_DB_PATH="custom.db",
        RM_DATABASE_URL="postgresql+psycopg2://user:<REDACTED>@localhost:5432/relayer",
        RELAYER_QUEUE_POLL_SECONDS="2.5",
        RELAYER_QUEUE_MAX_ATTEMPTS="7",
        RELAYER_FEE_BUMP_PERCENT="0.25",
        RELAYER_MIN_ESCROW_TOKEN_BALANCE_WEI="10",  # noqa: S106 - test fixture value
        RELAYER_MIN_RELAYER_TOKEN_ALLOWANCE_WEI="20",  # noqa: S106 - test fixture value
        RELAYER_HTTP_TIMEOUT_SECONDS="15",
    )

    cfg = load_config()
    assert cfg.max_block_age_seconds == 10
    assert cfg.min_relayer_balance_wei == 5
    assert cfg.max_retries == 9
    assert cfg.retry_backoff_seconds == 1.2
    assert cfg.tx_timeout_seconds == 30
    assert cfg.bearer_token == token_value
    assert cfg.queue_db_path == "custom.db"
    assert cfg.queue_dsn == "postgresql://user:<REDACTED>@localhost:5432/relayer"
    assert cfg.queue_poll_seconds == 2.5
    assert cfg.queue_max_attempts == 7
    assert cfg.fee_bump_percent == 0.25
    assert cfg.min_escrow_token_balance_wei == 10
    assert cfg.min_relayer_token_allowance_wei == 20
    assert cfg.http_timeout_seconds == 15
