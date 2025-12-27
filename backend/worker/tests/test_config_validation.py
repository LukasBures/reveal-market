from __future__ import annotations

import pytest
from app.config import MissingSettingsError, Settings, validate_required_settings


def test_validate_required_settings_requires_db_and_redis_in_prod(monkeypatch):
    monkeypatch.delenv("RM_DATABASE_URL", raising=False)
    monkeypatch.delenv("RM_REDIS_URL", raising=False)
    settings = Settings(environment="production")
    with pytest.raises(MissingSettingsError) as excinfo:
        validate_required_settings(settings)
    message = str(excinfo.value)
    assert "RM_DATABASE_URL" in message
    assert "RM_REDIS_URL" in message


def test_validate_required_settings_requires_summary_api_key_when_no_fallback(monkeypatch):
    monkeypatch.setenv("RM_DATABASE_URL", "postgresql://user:<REDACTED>@db/reveal")
    monkeypatch.setenv("RM_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("RM_POLYMARKET_API_BASE", "https://gamma-api.polymarket.com")
    monkeypatch.setenv("RM_PROVER_BASE_URL", "http://prover:8085")
    monkeypatch.setenv("RM_RPC_URL", "https://rpc.example")
    monkeypatch.setenv("RM_SETTLEMENT_SIGNER_PRIVATE_KEY", "0x" + "1" * 64)
    monkeypatch.delenv("RM_SUMMARY_API_KEY", raising=False)
    settings = Settings(
        environment="production",
        summary_enabled=True,
        summary_fallback_enabled=False,
    )
    with pytest.raises(MissingSettingsError) as excinfo:
        validate_required_settings(settings)
    assert "RM_SUMMARY_API_KEY" in str(excinfo.value)


def test_validate_required_settings_allows_prover_when_env_present(monkeypatch):
    monkeypatch.setenv("RM_DATABASE_URL", "postgresql://user:<REDACTED>@db/reveal")
    monkeypatch.setenv("RM_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("RM_PROVER_BASE_URL", "http://prover:8085")
    monkeypatch.setenv("RM_POLYMARKET_API_BASE", "https://gamma-api.polymarket.com")
    monkeypatch.setenv("RM_RPC_URL", "https://rpc.example")
    monkeypatch.setenv("RM_SETTLEMENT_SIGNER_PRIVATE_KEY", "0x" + "1" * 64)
    settings = Settings(environment="production")
    # should not raise because required envs are set
    validate_required_settings(settings)


def test_validate_required_settings_requires_lock_batches_signer(monkeypatch):
    monkeypatch.setenv("RM_DATABASE_URL", "postgresql://user:<REDACTED>@db/reveal")
    monkeypatch.setenv("RM_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("RM_RPC_URL", "https://rpc.example")
    monkeypatch.setenv("RM_PROVER_BASE_URL", "http://prover:8085")
    monkeypatch.setenv("RM_POLYMARKET_API_BASE", "https://gamma-api.polymarket.com")
    monkeypatch.delenv("RM_SETTLEMENT_SIGNER_PRIVATE_KEY", raising=False)
    settings = Settings(environment="production")
    with pytest.raises(MissingSettingsError) as excinfo:
        validate_required_settings(settings)
    assert "RM_SETTLEMENT_SIGNER_PRIVATE_KEY" in str(excinfo.value)


def test_validate_required_settings_requires_relayer_for_lock_batches(monkeypatch):
    monkeypatch.setenv("RM_DATABASE_URL", "postgresql://user:<REDACTED>@db/reveal")
    monkeypatch.setenv("RM_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("RM_RPC_URL", "https://rpc.example")
    monkeypatch.setenv("RM_PROVER_BASE_URL", "http://prover:8085")
    monkeypatch.setenv("RM_POLYMARKET_API_BASE", "https://gamma-api.polymarket.com")
    monkeypatch.setenv("RM_SETTLEMENT_SIGNER_PRIVATE_KEY", "0x" + "1" * 64)
    monkeypatch.delenv("RM_RELAYER_BASE_URL", raising=False)
    settings = Settings(
        environment="production",
        lock_batches_use_relayer=True,
    )
    with pytest.raises(MissingSettingsError) as excinfo:
        validate_required_settings(settings)
    assert "RM_RELAYER_BASE_URL" in str(excinfo.value)


def test_resolved_async_database_url_preserves_password():
    settings = Settings(database_url="postgresql+psycopg2://user:<REDACTED>@db:5432/reveal")

    assert settings.resolved_async_database_url == "postgresql+asyncpg://user:<REDACTED>@db:5432/reveal"


def test_resolved_async_database_url_prefers_override():
    settings = Settings(
        database_url="postgresql+psycopg2://user:<REDACTED>@db:5432/reveal",
        database_async_url="postgresql+asyncpg://user:<REDACTED>@async-db:5432/reveal_async",
    )

    assert settings.resolved_async_database_url == "postgresql+asyncpg://user:<REDACTED>@async-db:5432/reveal_async"
