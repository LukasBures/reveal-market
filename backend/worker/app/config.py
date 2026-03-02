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
MAX_GAS_PRICE_GWEI = 500.0


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
    polymarket_commit_batch_size: int = Field(
        default=3000,
        ge=0,
        description="Commit after this many markets are processed (0 = commit every page).",
    )
    polymarket_use_events_endpoint: bool = Field(
        default=True,
        description="Use Gamma /events pagination (false uses /markets to reduce payload size).",
    )
    worker_memory_log_enabled: bool = Field(
        default=False,
        description="Emit per-page memory snapshots in worker.sync.page logs.",
    )
    worker_memory_log_every_n_pages: int = Field(
        default=25,
        ge=1,
        description="Log memory snapshots every N pages when enabled.",
    )
    worker_memory_pressure_scan_interval_seconds: int = Field(
        default=600,
        ge=0,
        description="Minimum seconds between GC object scans for memory pressure diagnostics (0 disables scans).",
    )
    worker_memory_trim_threshold_mb: int = Field(
        default=0,
        ge=0,
        description="If >0, trigger GC/malloc_trim when RSS exceeds this threshold (MB).",
    )
    worker_memory_abort_threshold_mb: int = Field(
        default=0,
        ge=0,
        description="If >0, stop the sync tick when RSS exceeds this threshold (MB).",
    )
    db_query_warn_threshold: int = Field(default=200, ge=1)
    db_query_time_warn_ms: float = Field(default=500.0, ge=0)
    db_query_hotspot_limit: int = Field(
        default=5,
        ge=0,
        description="Top SQL query fingerprints to include when DB query budget warnings trigger (0 disables).",
    )
    db_query_hotspot_min_total_ms: float = Field(
        default=25.0,
        ge=0,
        description="Only include query hotspots with at least this cumulative time in a sync tick.",
    )
    polymarket_order: str = Field(default="id")
    polymarket_sort_ascending: bool = Field(default=False)
    polymarket_only_open_markets: bool | None = Field(default=None)
    polymarket_active_filter: bool | None = Field(default=None)
    polymarket_archived_filter: bool | None = Field(default=None)
    polymarket_max_retries: int = Field(default=3, ge=1)
    polymarket_retry_backoff_seconds: float = Field(default=0.2, ge=0)
    polymarket_retry_backoff_max_seconds: float = Field(default=2.0, ge=0)
    polymarket_sync_max_attempts: int = Field(default=3, ge=1)
    polymarket_sync_retry_backoff_seconds: float = Field(default=1.0, ge=0)
    polymarket_sync_retry_backoff_max_seconds: float = Field(default=15.0, ge=0)
    circuit_failure_threshold: int = Field(default=10, ge=1)
    circuit_window_seconds: int = Field(default=60, ge=1)
    circuit_cooldown_seconds: int = Field(default=90, ge=1)
    polymarket_rate_limit_requests: int | None = Field(default=100, ge=1)
    polymarket_rate_limit_window_seconds: float | None = Field(default=8.0, gt=0)
    polymarket_empty_page_tolerance: int = Field(default=2, ge=0)
    polymarket_stream_persist: bool = Field(default=False)
    polymarket_sync_lease_key: str = Field(default="reveal_market_worker:polymarket_sync_lease")
    polymarket_sync_lease_ttl_seconds: int = Field(default=120, ge=5)
    polymarket_sync_lease_jitter_seconds: float = Field(default=2.0, ge=0)
    polymarket_sync_lease_failure_cooldown_seconds: float = Field(
        default=30.0,
        ge=0,
        description="Local cooldown after failing to acquire a sync lease (seconds).",
    )
    polymarket_sync_lease_failure_jitter_seconds: float = Field(
        default=5.0,
        ge=0,
        description="Jitter added to the local cooldown after lease failure.",
    )
    polymarket_updated_at_cutoff_enabled: bool = Field(
        default=True,
        description="Stop pagination once updatedAt is older than the last successful sync marker.",
    )
    polymarket_updated_at_cutoff_key: str = Field(default="reveal_market_worker:polymarket_sync_updated_at")
    polymarket_updated_at_cutoff_grace_seconds: int = Field(
        default=60,
        ge=0,
        description="Grace window subtracted from the last updatedAt cutoff to avoid missing ties.",
    )
    polymarket_sync_cursor_key: str = Field(
        default="reveal_market_worker:polymarket_sync_cursor",
        description="Redis key storing last seen polymarket cursor tuple (timestamp/id).",
    )
    poll_interval_seconds: int = Field(default=300, ge=1)
    poll_interval_jitter_seconds: float = Field(default=3.0, ge=0)
    maintenance_poll_seconds: float = Field(
        default=300.0,
        ge=0,
        description="How often to run maintenance loops (0 disables).",
    )
    maintenance_lease_key: str = Field(default="reveal_market_worker:maintenance_lease")
    closed_markets_reconcile_enabled: bool = Field(
        default=True,
        description="Enable low-frequency refresh of closed markets that have commitments.",
    )
    closed_markets_reconcile_interval_seconds: int = Field(
        default=3600,
        ge=0,
        description="Minimum seconds between closed-market reconcile runs (0 disables).",
    )
    closed_markets_reconcile_batch_size: int = Field(
        default=25,
        ge=1,
        description="Markets to fetch per closed-market reconcile batch.",
    )
    closed_markets_reconcile_max_markets: int = Field(
        default=500,
        ge=1,
        description="Maximum markets to reconcile per maintenance tick.",
    )
    factory_backfill_limit: int = Field(
        default=200,
        ge=0,
        description="Maximum markets to backfill per maintenance tick (0 disables backfills).",
    )
    closed_markets_reconcile_stale_seconds: int = Field(
        default=21600,
        ge=0,
        description="Refresh markets whose source_updated_at is older than this threshold.",
    )
    closed_markets_reconcile_fetch_concurrency: int = Field(
        default=5,
        ge=1,
        description="Max concurrent Gamma fetches during closed-market reconcile.",
    )
    closed_markets_reconcile_last_key: str = Field(
        default="reveal_market_worker:closed_markets_reconcile_last",
        description="Redis key storing last closed-market reconcile timestamp.",
    )
    api_base_url: str | None = Field(
        default_factory=lambda: str(PRESET.get("api_internal_base_url", "http://localhost:8000"))
    )
    prime_markets_cache_enabled: bool = Field(default=True)
    markets_cache_limit: int = Field(default=30, ge=1, le=250)
    markets_cache_offset: int = Field(default=0, ge=0)
    markets_cache_order_by: str | None = Field(default="volume")
    markets_cache_prime_pages: int = Field(default=5, ge=1, le=1000)
    markets_cache_ttl_seconds: int = Field(default=300, ge=1)
    market_stats_ttl_seconds: int = Field(
        default=900,
        ge=0,
        description="TTL for per-market stats stored in Redis (0 disables writes).",
    )
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
    commit_cutoff_seconds: int = Field(default=300, ge=0)
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
    container_heartbeat_seconds: int = Field(default=60, ge=10)
    prover_base_url: AnyHttpUrl | None = Field(default=None)
    prover_timeout_seconds: float = Field(default=5.0, gt=0)
    prover_shared_secret: SecretStr | None = Field(default=None, alias="RM_PROVER_SHARED_SECRET")
    circuit_hash: str | None = Field(
        default=None,
        description="Expected prover circuit hash for validation (0x-prefixed).",
    )
    prover_startup_validation_enabled: bool = Field(
        default=True,
        description="Validate prover circuit hash alignment on startup.",
    )
    worker_mock_mode: bool = Field(
        default=False,
        description="Enable mock mode for Gamma/chain to speed local testing.",
    )
    chain_refresh_timeout_seconds: int = Field(
        default=30,
        ge=5,
        description="Timeout in seconds for on-chain settlement hydration",
    )
    proof_cache_prefix: str = Field(default="reveal_market:proof_receipts")
    proof_cache_ttl_seconds: int = Field(default=86400, ge=60)
    relayer_base_url: AnyHttpUrl | None = Field(default=None, description="Base URL for the Reveal relayer service")
    relayer_bearer_token: str | None = Field(default=None, description="Optional bearer token for relayer auth")
    relayer_internal_secret: SecretStr | None = Field(
        default=None, alias="RELAYER_API_INTERNAL_SECRET", description="Internal API secret for relayer calls"
    )
    relayer_http_timeout_seconds: float = Field(default=10.0, gt=0)
    relayer_queue_enabled: bool = Field(default=True, description="Enable Redis-backed relayer claim queue")
    relayer_queue_key: str = Field(default="reveal_market:relayer_queue", description="Redis key for relayer jobs")
    proof_queue_key: str = Field(default="reveal_market_worker:proof_queue")
    proof_queue_dedupe_key: str = Field(default="reveal_market_worker:proof_queue_dedupe")
    proof_queue_dedupe_ttl_seconds: int = Field(
        default=86400,
        ge=60,
        description="TTL (seconds) for proof queue dedupe entries",
    )
    proof_queue_dead_letter_key: str = Field(default="reveal_market_worker:proof_queue_dead_letter")
    proof_queue_poll_seconds: float = Field(default=1.0, ge=0.1)
    proof_queue_max_concurrency: int = Field(default=2, ge=1)
    proof_queue_max_depth: int = Field(default=1000, ge=1)
    proof_backfill_page_size: int = Field(
        default=250,
        ge=1,
        description="Max markets to inspect per backfill proof tick",
    )
    proof_failure_base_seconds: int = Field(
        default=120,
        ge=30,
        description="Base backoff for proof generation failures (seconds)",
    )
    proof_failure_max_seconds: int = Field(
        default=3600,
        ge=60,
        description="Max backoff for proof generation failures (seconds)",
    )
    proof_failure_max_attempts: int = Field(
        default=6,
        ge=1,
        description="Max consecutive proof failures before extended cooldown",
    )
    proof_failure_max_age_seconds: int = Field(
        default=86400,
        ge=3600,
        description="Max wall-clock seconds to keep retrying a proof before giving up",
    )
    settlement_queue_key: str = Field(default="reveal_market_worker:settlement_queue")
    settlement_queue_dedupe_key: str = Field(default="reveal_market_worker:settlement_queue_dedupe")
    settlement_queue_dedupe_ttl_seconds: int = Field(
        default=86400,
        ge=60,
        description="TTL (seconds) for settlement queue dedupe entries",
    )
    settlement_queue_dead_letter_key: str = Field(default="reveal_market_worker:settlement_queue_dead_letter")
    settlement_recovery_min_interval_seconds: int = Field(
        default=120,
        ge=0,
        description="Minimum seconds between settlement recovery passes (0 disables cooldown)",
    )
    proof_queue_dead_letter_max_items: int = Field(
        default=2000,
        ge=0,
        description="Max items to retain in proof queue dead letter (0 disables trimming)",
    )
    proof_queue_dead_letter_ttl_seconds: int = Field(
        default=604800,
        ge=0,
        description="TTL for proof queue dead letter entries (0 disables)",
    )
    proof_queue_dead_letter_trim_interval_seconds: float = Field(
        default=300.0,
        ge=0,
        description="Interval to trim proof queue DLQ outside enqueue (0 disables).",
    )
    settlement_queue_dead_letter_max_items: int = Field(
        default=2000,
        ge=0,
        description="Max items to retain in settlement dead letter (0 disables trimming)",
    )
    settlement_queue_dead_letter_ttl_seconds: int = Field(
        default=604800,
        ge=0,
        description="TTL for settlement dead letter entries (0 disables)",
    )
    settlement_queue_dead_letter_trim_interval_seconds: float = Field(
        default=300.0,
        ge=0,
        description="Interval to trim settlement DLQ outside enqueue (0 disables).",
    )
    maintenance_mode_enabled: bool = Field(
        default=True,
        description="Allow maintenance loop to run backfills/cleanup.",
    )
    db_latency_pace_enabled: bool = Field(default=True)
    db_latency_pace_ms: float = Field(default=300.0, ge=0)
    db_latency_pace_sleep_seconds: float = Field(default=1.0, ge=0)
    settlement_queue_poll_seconds: float = Field(default=1.0, ge=0.1)
    settlement_queue_max_concurrency: int = Field(default=2, ge=1)
    settlement_submission_lock_key_prefix: str = Field(
        default="reveal_market_worker:settlement_submit_lock",
        description="Redis key prefix for per-market settlement submission locks",
    )
    settlement_submission_lock_ttl_seconds: int = Field(
        default=600,
        ge=30,
        description="TTL for per-market settlement submission lock ownership",
    )
    settlement_submission_processing_stale_seconds: int = Field(
        default=900,
        ge=30,
        description="Age threshold to retry stale PROCESSING settlement submissions",
    )
    settlement_submission_failure_base_seconds: int = Field(
        default=120,
        ge=30,
        description="Base backoff for settlement submission failures (seconds)",
    )
    settlement_submission_failure_max_seconds: int = Field(
        default=3600,
        ge=60,
        description="Max backoff for settlement submission failures (seconds)",
    )
    settlement_submission_failure_max_attempts: int = Field(
        default=6,
        ge=1,
        description="Max consecutive settlement submission failures before extended cooldown",
    )
    settlement_submission_failure_max_age_seconds: int = Field(
        default=86400,
        ge=3600,
        description="Max wall-clock seconds to keep retrying a settlement submission",
    )
    lock_batches_use_relayer: bool = Field(
        default=False,
        description="Route lockBatches submissions through the relayer API instead of direct RPC",
    )
    lock_batches_poll_seconds: float = Field(
        default=60.0,
        ge=0,
        description="How often to run lock-batches in the background loop (0 disables)",
    )
    lock_batches_lease_key: str = Field(default="reveal_market_worker:lock_batches_lease")
    lock_batches_lease_ttl_seconds: int = Field(
        default=90,
        ge=5,
        description="Distributed lease TTL for lock-batches loop ownership",
    )
    lock_batches_lease_jitter_seconds: float = Field(
        default=2.0,
        ge=0,
        description="Optional jitter added to lock-batches lease TTL",
    )
    lock_batches_max_per_tick: int = Field(default=3, ge=1)
    lock_batches_relayer_poll_seconds: float = Field(default=2.0, ge=0.5)
    lock_batches_relayer_max_attempts: int = Field(default=15, ge=1)
    lock_batches_gas_limit: int = Field(default=800_000, ge=100_000)
    lock_batches_gas_price_gwei: float | None = Field(default=None, ge=0)
    lock_batches_max_priority_fee_gwei: float | None = Field(default=None, ge=0)
    lock_batches_failure_base_seconds: int = Field(
        default=300,
        ge=30,
        description="Base backoff for lock-batches failures (seconds)",
    )
    lock_batches_failure_max_seconds: int = Field(
        default=3600,
        ge=60,
        description="Max backoff for lock-batches failures (seconds)",
    )
    lock_batches_failure_max_attempts: int = Field(
        default=6,
        ge=1,
        description="Max consecutive lock-batches failures before extended cooldown",
    )
    settlement_recovery_limit: int = Field(
        default=50,
        ge=1,
        description="Max markets to inspect per recovery tick",
    )
    settlement_recovery_failure_base_seconds: int = Field(
        default=300,
        ge=30,
        description="Base backoff for settlement recovery failures (seconds)",
    )
    settlement_recovery_failure_max_seconds: int = Field(
        default=3600,
        ge=60,
        description="Max backoff for settlement recovery failures (seconds)",
    )
    settlement_recovery_failure_max_attempts: int = Field(
        default=6,
        ge=1,
        description="Max consecutive settlement recovery failures before extended cooldown",
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
        "lock_batches_gas_price_gwei",
        "lock_batches_max_priority_fee_gwei",
        "goldsky_subgraph_url",
        "goldsky_api_key",
        "prover_shared_secret",
        "relayer_internal_secret",
        mode="before",
    )
    @classmethod
    def _none_on_empty(cls, value):
        return _empty_to_none(value)

    @field_validator(
        "gas_price_gwei",
        "settlement_gas_price_gwei",
        "settlement_max_priority_fee_gwei",
        "lock_batches_gas_price_gwei",
        "lock_batches_max_priority_fee_gwei",
    )
    @classmethod
    def _validate_gas_price_bounds(cls, value):
        if value is None:
            return value
        if value > MAX_GAS_PRICE_GWEI:
            raise ValueError(f"gas_price_exceeds_safety_limit:{value}")
        return value

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
    require("RM_PROVER_BASE_URL", when=prod_like)
    require("RM_RPC_URL", when=prod_like)
    if settings.lock_batches_use_relayer:
        require("RM_RELAYER_BASE_URL")
    if prod_like and settings.relayer_base_url:
        if not settings.relayer_bearer_token and not settings.relayer_internal_secret:
            missing.append("RM_RELAYER_BEARER_TOKEN or RM_RELAYER_API_INTERNAL_SECRET")
    require("RM_SETTLEMENT_SIGNER_PRIVATE_KEY", when=prod_like)
    require("RM_SETTLEMENT_RPC_URL", when=prod_like and not _env_present("RM_RPC_URL"))
    if missing:
        unique = sorted(set(missing))
        raise MissingSettingsError(f"Missing required environment variables: {', '.join(unique)}")


def sanitize_settings(settings: Settings) -> dict[str, Any]:
    """Return a redacted settings payload safe for logs."""

    sensitive_keys = {
        "database_url",
        "redis_url",
        "wallet_private_key",
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
