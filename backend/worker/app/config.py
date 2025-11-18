"""Configuration primitives for the worker service."""

from __future__ import annotations

import csv
import os
from functools import lru_cache

from pydantic import AliasChoices, AnyHttpUrl, AnyUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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


class Settings(BaseSettings):
    """Runtime options sourced from env vars/`.env` for the worker."""

    model_config = SettingsConfigDict(env_prefix="RM_")

    app_name: str = Field(default="Reveal Market Worker")
    environment: str = Field(default="development")
    database_url: str = Field(default="postgresql+psycopg2://market_admin:<REDACTED>@postgres:5432/reveal_market")
    redis_url: str = Field(default="redis://redis:6379/0")
    polymarket_api_base: AnyHttpUrl = Field(default="https://gamma-api.polymarket.com")
    polymarket_timeout_seconds: float = Field(default=10.0, gt=0)
    polymarket_page_size: int = Field(default=100, ge=1, le=250)
    polymarket_max_pages: int | None = Field(default=None, ge=1)
    polymarket_order: str = Field(default="updatedAt")
    polymarket_sort_ascending: bool = Field(default=False)
    polymarket_closed_filter: bool | None = Field(default=False)
    polymarket_active_filter: bool | None = Field(default=True)
    polymarket_archived_filter: bool | None = Field(default=False)
    polymarket_network: str | None = Field(default="137")
    polymarket_max_retries: int = Field(default=3, ge=1)
    polymarket_retry_backoff_seconds: float = Field(default=0.2, ge=0)
    polymarket_retry_backoff_max_seconds: float = Field(default=2.0, ge=0)
    polymarket_sync_max_attempts: int = Field(default=3, ge=1)
    polymarket_sync_retry_backoff_seconds: float = Field(default=1.0, ge=0)
    polymarket_sync_retry_backoff_max_seconds: float = Field(default=15.0, ge=0)
    polymarket_rate_limit_requests: int | None = Field(default=100, ge=1)
    polymarket_rate_limit_window_seconds: float | None = Field(default=8.0, gt=0)
    polymarket_empty_page_tolerance: int = Field(default=2, ge=0)
    poll_interval_seconds: int = Field(default=60, ge=1)
    api_base_url: str | None = Field(default="http://localhost:8000")
    prime_markets_cache_enabled: bool = Field(default=False)
    markets_cache_limit: int = Field(default=18, ge=1, le=250)
    markets_cache_offset: int = Field(default=0, ge=0)
    markets_cache_ttl_seconds: int = Field(default=30, ge=1)
    cache_prime_timeout_seconds: float = Field(default=5.0, gt=0)
    category_cache_limit: int = Field(default=18, ge=1, le=250)
    suggest_cache_limit: int = Field(default=5, ge=1, le=25)
    heartbeat_key: str = Field(default="reveal_market_worker:heartbeat")
    heartbeat_ttl_seconds: int = Field(default=120, ge=10)
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
    polygon_rpc_url: AnyUrl | None = Field(
        default=None,
        validation_alias=AliasChoices("RM_POLYGON_RPC_URL", "POLYGON_RPC_URL"),
    )
    conditional_tokens_address: str | None = Field(
        default=None,
        validation_alias=AliasChoices("RM_POLYGON_CTF_ADDRESS", "POLYGON_CTF_ADDRESS"),
    )
    clob_host: AnyHttpUrl | None = Field(
        default=None,
        validation_alias=AliasChoices("RM_POLYMARKET_CLOB_HOST", "POLYMARKET_CLOB_HOST"),
    )
    wallet_address: str | None = Field(default=None)
    wallet_private_key: SecretStr | None = Field(default=None)
    gas_price_gwei: float | None = Field(default=None, ge=0)
    max_priority_fee_gwei: float | None = Field(default=None, ge=0)
    auto_create_onchain_markets: bool = Field(default=False)
    default_commit_lead_seconds: int = Field(default=86400, ge=60)
    default_reveal_lead_seconds: int = Field(default=172800, ge=120)
    max_web3_retries: int = Field(default=3, ge=1)
    resolution_refresh_interval_seconds: int = Field(default=300, ge=60)
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
    summary_api_base_url: AnyHttpUrl | None = Field(default="https://api.openai.com/v1")
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
    goldsky_subgraph_url: AnyHttpUrl | None = Field(default=None)
    goldsky_api_key: SecretStr | None = Field(default=None)
    goldsky_timeout_seconds: float = Field(default=6.0, gt=0)

    @field_validator("featured_categories", "featured_suggest_queries", mode="before")
    @classmethod
    def _parse_csv(cls, value):
        if isinstance(value, str):
            return _split_csv(value)
        return value


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
