"""Configuration primitives for the worker service."""

from __future__ import annotations

import csv
import logging
import os
from functools import lru_cache
from typing import Any, cast

from pydantic import AnyHttpUrl, AnyUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, DotEnvSettingsSource, EnvSettingsSource, SettingsConfigDict
from shared.env_presets import get_preset
from shared.logging import log_event
from sqlalchemy.engine.url import make_url

PRESET = get_preset()


def _split_csv(value: str) -> list[str]:
    reader = csv.reader([value], skipinitialspace=True)
    items = next(reader, [])
    if len(items) == 1:
        stripped = value.strip()
        if stripped and stripped[0] in {'"', "'"} and stripped[-1] == stripped[0]:
            inner = stripped[1:-1]
            if "," in inner:
                items = inner.split(",")
    return [item.strip() for item in items if item.strip()]


def _empty_to_none(value):
    """Convert empty strings to None so optional fields tolerate blank env entries."""

    if isinstance(value, str) and value.strip() == "":
        return None
    return value


class LenientEnvSettingsSource(EnvSettingsSource):
    """Env source that falls back to raw strings when JSON decoding fails."""

    def decode_complex_value(self, field_name, field, value):
        try:
            return super().decode_complex_value(field_name, field, value)
        except (ValueError, TypeError):
            return value


class LenientDotEnvSettingsSource(DotEnvSettingsSource):
    """Dotenv source that falls back to raw strings when JSON decoding fails."""

    def decode_complex_value(self, field_name, field, value):
        try:
            return super().decode_complex_value(field_name, field, value)
        except (ValueError, TypeError):
            return value


class Settings(BaseSettings):
    """Runtime options sourced from env vars/`.env` for the worker."""

    model_config = SettingsConfigDict(env_prefix="RM_")

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        env_source = LenientEnvSettingsSource(
            settings_cls,
            case_sensitive=env_settings.case_sensitive,
            env_prefix=env_settings.env_prefix,
            env_nested_delimiter=env_settings.env_nested_delimiter,
            env_nested_max_split=getattr(env_settings, "env_nested_max_split", None),
            env_ignore_empty=env_settings.env_ignore_empty,
            env_parse_none_str=env_settings.env_parse_none_str,
            env_parse_enums=env_settings.env_parse_enums,
        )
        dotenv_source = LenientDotEnvSettingsSource(
            settings_cls,
            env_file=getattr(dotenv_settings, "env_file", None),
            env_file_encoding=getattr(dotenv_settings, "env_file_encoding", None),
            case_sensitive=dotenv_settings.case_sensitive,
            env_prefix=dotenv_settings.env_prefix,
            env_nested_delimiter=dotenv_settings.env_nested_delimiter,
            env_nested_max_split=getattr(dotenv_settings, "env_nested_max_split", None),
            env_ignore_empty=dotenv_settings.env_ignore_empty,
            env_parse_none_str=dotenv_settings.env_parse_none_str,
            env_parse_enums=dotenv_settings.env_parse_enums,
        )
        return init_settings, env_source, dotenv_source, file_secret_settings

    app_name: str = Field(default="Reveal Market Worker")
    environment: str = Field(default="development")
    database_url: str = Field(default="postgresql+psycopg2://market_admin:<REDACTED>@postgres:5432/reveal_market")
    database_async_url: str | None = Field(
        default=None,
        description="Optional async driver URL; defaults to database_url converted to asyncpg",
    )
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    database_pool_timeout: float = Field(default=10.0, gt=0)
    redis_url: str = Field(default="redis://redis:6379/0")
    polymarket_api_base: AnyHttpUrl = Field(default=cast(AnyHttpUrl, "https://gamma-api.polymarket.com"))
    polymarket_timeout_seconds: float = Field(default=10.0, gt=0)
    polymarket_page_size: int = Field(default=100, ge=1, le=250)
    polymarket_max_pages: int | None = Field(default=None, ge=1)
    polymarket_order: str = Field(default="id")
    polymarket_sort_ascending: bool = Field(default=False)
    polymarket_closed_filter: bool | None = Field(default=None)
    polymarket_active_filter: bool | None = Field(default=None)
    polymarket_archived_filter: bool | None = Field(default=None)
    polymarket_max_retries: int = Field(default=3, ge=1)
    polymarket_retry_backoff_seconds: float = Field(default=0.2, ge=0)
    polymarket_retry_backoff_max_seconds: float = Field(default=2.0, ge=0)
    polymarket_sync_max_attempts: int = Field(default=3, ge=1)
    polymarket_sync_retry_backoff_seconds: float = Field(default=1.0, ge=0)
    polymarket_sync_retry_backoff_max_seconds: float = Field(default=15.0, ge=0)
    polymarket_rate_limit_requests: int | None = Field(default=100, ge=1)
    polymarket_rate_limit_window_seconds: float | None = Field(default=8.0, gt=0)
    polymarket_empty_page_tolerance: int = Field(default=2, ge=0)
    polymarket_stream_persist: bool = Field(default=False)
    polymarket_sync_lease_key: str = Field(default="reveal_market_worker:polymarket_sync_lease")
    polymarket_sync_lease_ttl_seconds: int = Field(default=120, ge=5)
    polymarket_sync_lease_jitter_seconds: float = Field(default=2.0, ge=0)
    poll_interval_seconds: int = Field(default=300, ge=1)
    poll_interval_jitter_seconds: float = Field(default=3.0, ge=0)
    api_base_url: str | None = Field(
        default_factory=lambda: str(PRESET.get("api_internal_base_url", "http://localhost:8000"))
    )
    prime_markets_cache_enabled: bool = Field(default=True)
    markets_cache_limit: int = Field(default=30, ge=1, le=250)
    markets_cache_offset: int = Field(default=0, ge=0)
    markets_cache_order_by: str | None = Field(default="volume")
    markets_cache_prime_pages: int = Field(default=5, ge=1, le=1000)
    markets_cache_ttl_seconds: int = Field(default=300, ge=1)
    cache_prime_timeout_seconds: float = Field(default=5.0, gt=0)
    category_cache_limit: int = Field(default=18, ge=1, le=250)
    suggest_cache_limit: int = Field(default=5, ge=1, le=25)
    heartbeat_key: str = Field(default="reveal_market_worker:heartbeat")
    heartbeat_ttl_seconds: int = Field(default=900, ge=10)
    heartbeat_max_retries: int = Field(default=2, ge=1)
    heartbeat_retry_backoff_seconds: float = Field(default=0.1, ge=0)
    heartbeat_retry_backoff_max_seconds: float = Field(default=1.0, ge=0)
    batch_stats_key: str = Field(default="reveal_market_worker:batch_stats")
    batch_stats_ttl_seconds: int = Field(default=900, ge=30)
    schema_version_key: str = Field(default="reveal_market:schema_version")
    factory_address: str | None = Field(default=None)
    rake_manager_address: str | None = Field(default=None)
    verifier_address: str | None = Field(default=None)
    rpc_url: AnyUrl | None = Field(default=None)
    clob_host: AnyHttpUrl | None = Field(default=None)
    wallet_address: str | None = Field(default=None)
    wallet_private_key: SecretStr | None = Field(default=None)
    gas_price_gwei: float | None = Field(default=None, ge=0)
    max_priority_fee_gwei: float | None = Field(default=None, ge=0)
    rake_percent: float = Field(default=0.02, ge=0, lt=0.25)
    haircut_percent: float = Field(default=0.12, ge=0, lt=0.25)
    worsen_percent: float = Field(default=0.03, ge=0, lt=0.25)
    lp_share_percent: float = Field(default=0.18, ge=0, lt=0.5)
    default_commit_lead_seconds: int = Field(default=86400, ge=60)
    default_reveal_lead_seconds: int = Field(default=172800, ge=120)
    max_web3_retries: int = Field(default=3, ge=1)
    resolution_refresh_interval_seconds: int = Field(default=300, ge=60)
    resolution_fetch_max_attempts: int = Field(default=2, ge=1)
    resolution_fetch_backoff_seconds: float = Field(default=0.5, ge=0)
    resolution_fetch_backoff_max_seconds: float = Field(default=4.0, ge=0)
    resolution_backfill_limit: int = Field(default=50, ge=0)
    resolution_gap_warn_threshold: int = Field(default=5, ge=0)
    resolution_gap_warn_seconds: int = Field(default=1800, ge=0)
    run_migrations_on_startup: bool = Field(default=True)
    resolved_retention_seconds: int = Field(default=86400, ge=3600)
    resolved_retention_dry_run: bool = Field(default=False)
    featured_categories: list[str] = Field(default_factory=list)
    featured_suggest_queries: list[str] = Field(default_factory=list)
    summary_enabled: bool = Field(default=True)
    summary_queue_key: str = Field(default="reveal_market_worker:summary_queue")
    summary_dead_letter_key: str = Field(default="reveal_market_worker:summary_dead_letter")
    summary_requested_ttl_seconds: int = Field(default=600, ge=60)
    summary_refresh_interval_seconds: int = Field(default=604800, ge=3600)
    summary_min_words: int = Field(default=200, ge=50)
    summary_max_words: int = Field(default=400, ge=100)
    summary_model: str = Field(default="gpt-5.1-mini")
    summary_source_label: str = Field(default="ai_enrichment")
    summary_prompt_template: str = Field(
        default=(
            "You are an analyst preparing a concise but well-researched summary for a prediction market.\n"
            "Write {min_words}-{max_words} words that:\n"
            "- Restate the core question in neutral, plain language.\n"
            "- Highlight the key drivers/risk factors investors should research.\n"
            "- Mention relevant timelines if they appear in the source data.\n"
            "Always disclose that this section is AI generated after a quick public-source scan.\n"
            "QUESTION: {title}\n"
            "CATEGORY: {category}\n"
            "TAGS: {tags}\n"
            "DESCRIPTION:\n"
            "{description}\n"
            "EXTRA CONTEXT:\n"
            "{extra_context}\n"
        )
    )
    summary_api_base_url: AnyHttpUrl | None = Field(default=cast(AnyHttpUrl, "https://api.openai.com/v1"))
    summary_api_key: SecretStr | None = Field(default=None)
    summary_http_timeout_seconds: float = Field(default=20.0, gt=0)
    summary_queue_poll_seconds: float = Field(default=2.0, gt=0)
    summary_retry_backoff_seconds: float = Field(default=30.0, ge=0)
    summary_retry_max_attempts: int = Field(default=3, ge=1)
    summary_fallback_enabled: bool = Field(default=True)
    container_heartbeat_seconds: int = Field(default=60, ge=10)
    prover_enabled: bool = Field(default=False)
    prover_base_url: AnyHttpUrl | None = Field(default=None)
    prover_timeout_seconds: float = Field(default=5.0, gt=0)
    proof_cache_prefix: str = Field(default="reveal_market:proof_receipts")
    proof_cache_ttl_seconds: int = Field(default=86400, ge=60)
    relayer_base_url: AnyHttpUrl | None = Field(default=None, description="Base URL for the Reveal relayer service")
    relayer_bearer_token: str | None = Field(default=None, description="Optional bearer token for relayer auth")
    relayer_queue_enabled: bool = Field(default=True, description="Enable Redis-backed relayer claim queue")
    relayer_queue_key: str = Field(default="reveal_market:relayer_queue", description="Redis key for relayer jobs")
    proof_queue_key: str = Field(default="reveal_market_worker:proof_queue")
    proof_queue_dedupe_key: str = Field(default="reveal_market_worker:proof_queue_dedupe")
    proof_queue_dead_letter_key: str = Field(default="reveal_market_worker:proof_queue_dead_letter")
    proof_queue_poll_seconds: float = Field(default=1.0, ge=0.1)
    proof_queue_max_concurrency: int = Field(default=2, ge=1)
    proof_queue_max_depth: int = Field(default=1000, ge=1)
    settlement_queue_key: str = Field(default="reveal_market_worker:settlement_queue")
    settlement_queue_dead_letter_key: str = Field(default="reveal_market_worker:settlement_queue_dead_letter")
    settlement_queue_poll_seconds: float = Field(default=1.0, ge=0.1)
    settlement_queue_max_concurrency: int = Field(default=2, ge=1)
    auto_settlement_enabled: bool = Field(
        default=False, description="Automatically request settlement proofs when data is present"
    )
    auto_settlement_tx_enabled: bool = Field(
        default=False,
        description="Automatically submit verifyAndSettle transactions once proofs are ready",
    )
    settlement_signer_private_key: SecretStr | None = Field(
        default=None, description="Private key for the oracle account that submits settlement transactions"
    )
    settlement_rpc_url: AnyUrl | None = Field(
        default=None, description="Optional RPC override for settlement submission (defaults to RM_RPC_URL)"
    )
    settlement_gas_price_gwei: float | None = Field(default=None, ge=0)
    settlement_max_priority_fee_gwei: float | None = Field(default=None, ge=0)
    goldsky_subgraph_url: AnyHttpUrl | None = Field(default=None)
    goldsky_api_key: SecretStr | None = Field(default=None)
    goldsky_timeout_seconds: float = Field(default=6.0, gt=0)
    market_progress_log_intervals: int = Field(default=10, ge=1)
    streamer_base_url: AnyHttpUrl = Field(
        default_factory=lambda: cast(AnyHttpUrl, str(PRESET.get("streamer_internal", "http://streamer:8100"))),
        description="Streamer base URL for orderbook/FX data",
    )
    streamer_timeout_seconds: float = Field(default=5.0, gt=0)

    @field_validator("featured_categories", "featured_suggest_queries", mode="before")
    @classmethod
    def _parse_csv(cls, value):
        if isinstance(value, str):
            return _split_csv(value)
        return value

    @field_validator(
        "polymarket_active_filter",
        "polymarket_archived_filter",
        "settlement_gas_price_gwei",
        "settlement_max_priority_fee_gwei",
        "goldsky_subgraph_url",
        "goldsky_api_key",
        mode="before",
    )
    @classmethod
    def _none_on_empty(cls, value):
        return _empty_to_none(value)

    @property
    def total_monetisation_percent(self) -> float:
        return float(self.rake_percent + self.haircut_percent + self.worsen_percent)

    @property
    def resolved_async_database_url(self) -> str:
        """Return an async-compatible database URL, deriving from the sync URL when needed."""

        override_async = os.getenv("RM_ASYNC_DATABASE_URL")
        if override_async:
            try:
                async_url = make_url(override_async)
                return async_url.render_as_string(hide_password=False)
            except Exception:
                # If the override is invalid, fall back to configured values.
                local_logger = logging.getLogger("reveal_market.worker.config")
                log_event(
                    local_logger,
                    logging.WARNING,
                    event="worker.config.async_db_url_invalid",
                    message="invalid RM_ASYNC_DATABASE_URL; falling back to derived async URL",
                    url=override_async,
                )
        if self.database_async_url:
            async_url = make_url(self.database_async_url)
            return async_url.render_as_string(hide_password=False)
        url = make_url(self.database_url)
        if url.drivername.startswith("postgresql"):
            url = url.set(drivername="postgresql+asyncpg")
        elif url.drivername.startswith("sqlite") and "+aiosqlite" not in url.drivername:
            url = url.set(drivername="sqlite+aiosqlite")
        return url.render_as_string(hide_password=False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings object, respecting optional env files."""
    env_file = os.getenv("SETTINGS_FILE")
    kwargs = {"_env_file": env_file} if env_file else {}
    return Settings(**kwargs)  # type: ignore[arg-type]


def reload_settings() -> Settings:
    """Clear cached settings and rebuild from the environment."""

    get_settings.cache_clear()
    return get_settings()


class MissingSettingsError(RuntimeError):
    """Raised when required configuration is absent."""


def _env_present(name: str) -> bool:
    value = os.getenv(name)
    return value is not None and value != ""


def validate_required_settings(settings: Settings) -> None:
    """Fail fast when required env vars are missing for the current mode."""

    prod_like = settings.environment.lower() not in {"dev", "development", "local", "test", "testing"}
    missing: list[str] = []

    def require(env_name: str, *, when: bool = True) -> None:
        if when and not _env_present(env_name):
            missing.append(env_name)

    # Always required in prod-like deployments (defaults acceptable locally)
    require("RM_DATABASE_URL", when=prod_like)
    require("RM_REDIS_URL", when=prod_like)

    # External dependencies
    if prod_like:
        require("RM_POLYMARKET_API_BASE")

    # Feature-gated requirements
    require("RM_SUMMARY_API_KEY", when=settings.summary_enabled and not settings.summary_fallback_enabled)
    require(
        "RM_PROVER_BASE_URL",
        when=settings.prover_enabled and (settings.auto_settlement_enabled or settings.prover_enabled),
    )
    require(
        "RM_SETTLEMENT_SIGNER_PRIVATE_KEY",
        when=settings.auto_settlement_tx_enabled,
    )
    require(
        "RM_SETTLEMENT_RPC_URL",
        when=settings.auto_settlement_tx_enabled and not _env_present("RM_RPC_URL"),
    )
    if missing:
        unique = sorted(set(missing))
        raise MissingSettingsError(f"Missing required environment variables: {', '.join(unique)}")


def sanitize_settings(settings: Settings) -> dict[str, Any]:
    """Return a redacted settings payload safe for logs."""

    sensitive_keys = {
        "database_url",
        "redis_url",
        "wallet_private_key",
        "summary_api_key",
        "rpc_url",
        "prover_base_url",
    }
    redacted: dict[str, Any] = {}
    for key, value in settings.model_dump().items():
        lower = key.lower()
        if lower in sensitive_keys or any(
            token in lower for token in ["key", "secret", "password", "token", "private"]
        ):
            continue
        redacted[key] = value
    return redacted
