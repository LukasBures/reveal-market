from __future__ import annotations

import secrets

import pytest
from pydantic import ValidationError
from relayer.config import RelayerConfig, get_settings, load_config

REQUIRED = {
    "RM_RPC_URL": "http://localhost:8545",
    "RM_CHAIN_ID": "1",
    "RM_RELAYER_PRIVATE_KEY": "0x" + "1" * 64,
    "RM_RELAYER_ESCROW_ADDRESS": "0x" + "2" * 40,
    "RM_RELAYER_BEARER_TOKEN": "test-token",
}


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _seed_env(monkeypatch, **overrides: str):
    for key, value in {**REQUIRED, **overrides}.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize("missing_key", REQUIRED.keys())
def test_load_config_requires_env(monkeypatch, missing_key):
    _seed_env(monkeypatch)
    monkeypatch.delenv(missing_key, raising=False)
    with pytest.raises((ValidationError, ValueError)):
        load_config()


def test_load_config_uses_defaults(monkeypatch):
    _seed_env(monkeypatch)
    monkeypatch.delenv("RM_RELAYER_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("RM_RELAYER_MAX_BLOCK_AGE_SECONDS", raising=False)
    monkeypatch.delenv("RM_RELAYER_MIN_BALANCE_WEI", raising=False)
    monkeypatch.delenv("RM_RELAYER_MAX_RETRIES", raising=False)
    monkeypatch.delenv("RM_RELAYER_RETRY_BACKOFF_SECONDS", raising=False)
    monkeypatch.delenv("RM_RELAYER_TX_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("RM_RELAYER_QUEUE_DB_PATH", raising=False)
    monkeypatch.delenv("RM_DATABASE_URL", raising=False)
    monkeypatch.delenv("RM_RELAYER_QUEUE_POLL_SECONDS", raising=False)
    monkeypatch.delenv("RM_RELAYER_QUEUE_MAX_ATTEMPTS", raising=False)
    monkeypatch.delenv("RM_RELAYER_QUEUE_MAX_PAYLOAD_BYTES", raising=False)
    monkeypatch.delenv("RM_RELAYER_QUEUE_RUNNING_TTL_SECONDS", raising=False)
    monkeypatch.delenv("RM_RELAYER_FEE_BUMP_PERCENT", raising=False)
    monkeypatch.delenv("RM_RELAYER_MIN_ESCROW_TOKEN_BALANCE_WEI", raising=False)
    monkeypatch.delenv("RM_RELAYER_MIN_RELAYER_TOKEN_ALLOWANCE_WEI", raising=False)
    monkeypatch.delenv("RM_RELAYER_HTTP_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("RM_RELAYER_PREFLIGHT_MODE", raising=False)
    monkeypatch.delenv("RM_RELAYER_RATE_LIMIT_REQUESTS", raising=False)
    monkeypatch.delenv("RM_RELAYER_RATE_LIMIT_WINDOW_SECONDS", raising=False)
    monkeypatch.delenv("RM_RELAYER_IP_ALLOWLIST", raising=False)
    monkeypatch.delenv("RM_RELAYER_TRUST_X_FORWARDED_FOR", raising=False)
    monkeypatch.delenv("RM_RELAYER_TRUSTED_PROXY_CIDRS", raising=False)
    monkeypatch.setenv("RM_RELAYER_ALLOW_INSECURE_AUTH", "true")

    cfg = load_config()
    assert isinstance(cfg, RelayerConfig)
    assert cfg.relayer_bearer_token is None
    assert cfg.relayer_allow_insecure_auth is True
    assert cfg.relayer_max_block_age_seconds == 60
    assert cfg.relayer_min_balance_wei == 0
    assert cfg.relayer_max_retries == 3
    assert cfg.relayer_retry_backoff_seconds == 0.5
    assert cfg.relayer_tx_timeout_seconds == 120
    assert cfg.relayer_queue_db_path == "relayer_queue.db"
    assert cfg.queue_dsn is None
    assert cfg.relayer_queue_poll_seconds == 1.0
    assert cfg.relayer_queue_max_attempts == 5
    assert cfg.relayer_queue_max_payload_bytes == 131072
    assert cfg.relayer_queue_running_ttl_seconds == 150
    assert cfg.relayer_fee_bump_percent == 0.15
    assert cfg.relayer_min_escrow_token_balance_wei == 0
    assert cfg.relayer_min_relayer_token_allowance_wei == 0
    assert cfg.relayer_http_timeout_seconds == 10
    assert cfg.relayer_preflight_mode == "none"
    assert cfg.relayer_rate_limit_requests == 30
    assert cfg.relayer_rate_limit_window_seconds == 60
    assert cfg.relayer_ip_allowlist == []
    assert cfg.relayer_trust_x_forwarded_for is False
    assert cfg.relayer_trusted_proxy_cidrs == []


def test_load_config_applies_overrides(monkeypatch):
    token_value = secrets.token_hex(8)
    _seed_env(
        monkeypatch,
        RM_RELAYER_MAX_BLOCK_AGE_SECONDS="10",
        RM_RELAYER_MIN_BALANCE_WEI="5",
        RM_RELAYER_MAX_RETRIES="9",
        RM_RELAYER_RETRY_BACKOFF_SECONDS="1.2",
        RM_RELAYER_TX_TIMEOUT_SECONDS="30",
        RM_RELAYER_BEARER_TOKEN=<REDACTED>
        RM_RELAYER_QUEUE_DB_PATH="custom.db",
        RM_DATABASE_URL="postgresql+psycopg2://user:<REDACTED>@localhost:5432/relayer",
        RM_RELAYER_QUEUE_POLL_SECONDS="2.5",
        RM_RELAYER_QUEUE_MAX_ATTEMPTS="7",
        RM_RELAYER_QUEUE_MAX_PAYLOAD_BYTES="2048",
        RM_RELAYER_QUEUE_RUNNING_TTL_SECONDS="45",
        RM_RELAYER_FEE_BUMP_PERCENT="0.25",
        RM_RELAYER_MIN_ESCROW_TOKEN_BALANCE_WEI="10",
        RM_RELAYER_MIN_RELAYER_TOKEN_ALLOWANCE_WEI="20",
        RM_RELAYER_HTTP_TIMEOUT_SECONDS="15",
        RM_RELAYER_PREFLIGHT_MODE="both",
        RM_RELAYER_RATE_LIMIT_REQUESTS="5",
        RM_RELAYER_RATE_LIMIT_WINDOW_SECONDS="12",
        RM_RELAYER_IP_ALLOWLIST="127.0.0.1,10.0.0.0/24",
        RM_RELAYER_TRUST_X_FORWARDED_FOR="true",
        RM_RELAYER_TRUSTED_PROXY_CIDRS="127.0.0.1/32,10.0.0.0/24",
    )

    cfg = load_config()
    assert cfg.relayer_max_block_age_seconds == 10
    assert cfg.relayer_min_balance_wei == 5
    assert cfg.relayer_max_retries == 9
    assert cfg.relayer_retry_backoff_seconds == 1.2
    assert cfg.relayer_tx_timeout_seconds == 30
    assert cfg.relayer_bearer_token == token_value
    assert cfg.relayer_queue_db_path == "custom.db"
    assert cfg.queue_dsn == "postgresql://user:<REDACTED>@localhost:5432/relayer"
    assert cfg.relayer_queue_poll_seconds == 2.5
    assert cfg.relayer_queue_max_attempts == 7
    assert cfg.relayer_queue_max_payload_bytes == 2048
    assert cfg.relayer_queue_running_ttl_seconds == 45
    assert cfg.relayer_fee_bump_percent == 0.25
    assert cfg.relayer_min_escrow_token_balance_wei == 10
    assert cfg.relayer_min_relayer_token_allowance_wei == 20
    assert cfg.relayer_http_timeout_seconds == 15
    assert cfg.relayer_preflight_mode == "both"
    assert cfg.relayer_rate_limit_requests == 5
    assert cfg.relayer_rate_limit_window_seconds == 12
    assert len(cfg.relayer_ip_allowlist) == 2
    assert cfg.relayer_trust_x_forwarded_for is True
    assert len(cfg.relayer_trusted_proxy_cidrs) == 2


def test_load_config_requires_bearer_token_by_default(monkeypatch):
    _seed_env(monkeypatch)
    monkeypatch.delenv("RM_RELAYER_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("RM_RELAYER_ALLOW_INSECURE_AUTH", raising=False)

    with pytest.raises((ValidationError, ValueError)):
        load_config()


def test_load_config_allows_insecure_auth_override(monkeypatch):
    _seed_env(monkeypatch)
    monkeypatch.delenv("RM_RELAYER_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("RM_RELAYER_ALLOW_INSECURE_AUTH", "true")

    cfg = load_config()
    assert cfg.relayer_bearer_token is None
    assert cfg.relayer_allow_insecure_auth is True
