from __future__ import annotations

import csv
import os
from collections.abc import Iterable
from functools import lru_cache

from pydantic import AnyHttpUrl, AnyUrl, Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, DotEnvSettingsSource, EnvSettingsSource, SettingsConfigDict
from shared.env_presets import get_preset
from sqlalchemy.engine import make_url

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


def _preset_list(key: str) -> list[str]:
    preset_value = PRESET.get(key, [])
    if isinstance(preset_value, Iterable) and not isinstance(preset_value, (str, bytes)):
        return [str(item) for item in preset_value]
    return []


def _empty_to_none(value):
    """Convert empty strings to None so optional URLs/keys can be omitted."""

    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def _normalize_circuit_hash(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if trimmed.startswith("0x") and len(trimmed) == 66:
        return trimmed
    return None


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
    """Runtime configuration for the Reveal Market API service."""

    model_config = SettingsConfigDict(env_prefix="RM_", extra="ignore")

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

    app_name: str = Field(default="Reveal Market API")
    environment: str = Field(default="development")
    version: str = Field(default="1.0.0")

    database_url: str = Field(default="postgresql+psycopg2://market_admin:<REDACTED>@postgres:5432/reveal_market")
    database_async_url: str | None = Field(
        default=None,
        description="Optional async driver URL; defaults to database_url converted to asyncpg",
    )
    database_echo: bool = Field(default=False)
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    redis_url: str = Field(default="redis://redis:6379/0")
    schema_version_key: str = Field(default="reveal_market:schema_version")
    factory_address: str | None = Field(default=None)
    market_implementation_address: str | None = Field(default=None)
    rake_manager_address: str | None = Field(default=None)
    rpc_url: AnyUrl | None = Field(default=AnyUrl("https://horizen-testnet.rpc.caldera.xyz/http"))
    wallet_address: str | None = Field(default=None)
    wallet_private_key: SecretStr | None = Field(default=None)
    oracle_address: str | None = Field(default=None)
    gas_price_gwei: float | None = Field(default=None, ge=0)
    max_priority_fee_gwei: float | None = Field(default=None, ge=0)
    rake_percent: float = Field(default=0.02, ge=0, lt=0.25)
    haircut_percent: float = Field(default=0.12, ge=0, lt=0.25)
    worsen_percent: float = Field(default=0.03, ge=0, lt=0.25)
    pricing_edge_percent: float = Field(default=0.05, ge=0, lt=0.25)
    lp_share_percent: float = Field(default=0.18, ge=0, lt=0.5)
    cache_ttl_seconds: int = Field(default=300, ge=1)
    cacheable_market_limit: int = Field(default=180, ge=1, le=1200)
    cacheable_market_offset_limit: int = Field(default=10000, ge=0)
    market_record_cache_ttl_seconds: int = Field(default=600, ge=30)
    cache_hydrate_on_startup: bool = Field(default=True)
    cache_hydrate_limit: int = Field(default=180, ge=1, le=1200)
    cache_hydrate_order_by: str | None = Field(default="volume")
    cache_refresh_enabled: bool = Field(default=True)
    cache_refresh_interval_seconds: int = Field(default=180, ge=15)
    cache_refresh_limit: int = Field(default=180, ge=1, le=1200)
    cache_hydrate_page_size: int = Field(default=30, ge=1, le=250)
    cache_connect_retries: int = Field(default=3, ge=1)
    cache_connect_retry_delay_seconds: float = Field(default=1.0, ge=0)
    claim_bundles_cache_ttl_seconds: int = Field(default=300, ge=5, description="Cache TTL for claim bundle responses")
    rate_limit_enabled: bool = Field(default=False)
    rate_limit_requests_per_window: int = Field(default=300, ge=1)
    rate_limit_window_seconds: int = Field(default=60, ge=1)
    rate_limit_whitelist: list[str] = Field(default_factory=list)
    rate_limit_trusted_proxies: list[str] = Field(default_factory=list)
    fx_feed_url: AnyHttpUrl = Field(default=AnyHttpUrl("http://streamer:8100/fx/zen-usd"))
    fx_timeout_seconds: float = Field(default=5.0, gt=0)
    fx_fallback_price: float = Field(default=0.0, ge=0)
    fx_cache_ttl_seconds: float = Field(default=60.0, ge=1.0)
    max_stake_zen: float = Field(default=0.1, gt=0, description="Per-quote max stake in ZEN")
    max_user_stake_per_market_zen: float = Field(
        default=0.5, gt=0, description="Per-user cumulative stake per market in ZEN"
    )
    max_market_stake_zen: float = Field(default=5.0, gt=0, description="Total stake cap per market in ZEN")
    bet_cap_ttl_seconds: int = Field(default=86400, ge=60, description="TTL for bet cap counters in Redis")
    quote_store_ttl_seconds: int = Field(default=900, ge=60, description="TTL for issued quotes (replay guard)")
    quote_expiry_sweep_interval_seconds: int = Field(
        default=60, ge=15, description="Interval for sweeping expired quotes from the ledger"
    )

    polymarket_api_base: AnyHttpUrl = Field(default=AnyHttpUrl("https://gamma-api.polymarket.com"))
    polymarket_timeout_seconds: float = Field(default=5.0)
    polymarket_order: str = Field(default="id")
    polymarket_sort_ascending: bool = Field(default=False)
    polymarket_only_open_markets: bool | None = Field(default=False)
    clob_host: AnyHttpUrl | None = Field(default=None)
    goldsky_subgraph_url: AnyHttpUrl | None = Field(default=None)
    goldsky_api_key: SecretStr | None = Field(default=None)
    goldsky_timeout_seconds: float = Field(default=5.0, gt=0)

    default_page_size: int = Field(default=50)
    max_page_size: int = Field(default=250)
    allowed_hosts: list[str] = Field(default_factory=lambda: _preset_list("api_allowed_hosts"))
    cors_allow_origins: list[str] = Field(default_factory=lambda: _preset_list("api_cors_origins"))
    cors_allow_methods: list[str] = Field(default_factory=lambda: ["GET", "HEAD", "OPTIONS", "POST"])
    cors_allow_headers: list[str] = Field(default_factory=lambda: ["*"])
    cors_allow_credentials: bool = Field(default=False)
    enable_security_headers: bool = Field(default=True)
    market_category_allowlist: list[str] = Field(default_factory=list)
    heartbeat_key: str = Field(default="reveal_market_worker:heartbeat")
    api_heartbeat_key: str = Field(default="reveal_market_api:heartbeat")
    container_heartbeat_seconds: int = Field(default=60, ge=10)
    api_heartbeat_ttl_seconds: int = Field(default=180, ge=30)
    performance_heartbeat_interval_seconds: int = Field(default=60, ge=10)
    worker_heartbeat_stale_seconds: int = Field(default=420, ge=30)
    slow_request_threshold_ms: float = Field(default=500.0, ge=10)
    health_cache_ttl_seconds: int = Field(default=10, ge=0)
    health_deep_cache_ttl_seconds: int = Field(default=10, ge=0)
    db_query_warn_threshold: int = Field(default=50, ge=1)
    db_query_time_warn_ms: float = Field(default=150.0, ge=0)
    run_migrations_on_startup: bool = Field(default=True)
    pricing_signer_private_key: SecretStr | None = Field(default=None)
    pricing_chain_id: int | None = Field(default=2651420, ge=1, description="Chain id used for quote signatures")
    pricing_quote_ttl_seconds: int = Field(default=120, ge=15, le=600)
    authorization_signer_private_key: SecretStr | None = Field(
        default=None, description="Private key for the on-chain authorization signer (CommitAuth signatures)"
    )
    relayer_base_url: AnyHttpUrl | None = Field(default=None, description="Base URL for the Reveal relayer service")
    relayer_bearer_token: str | None = Field(default=None, description="Optional bearer token for relayer auth")
    relayer_retry_attempts: int = Field(default=2, ge=0, description="Retry attempts for relayer commit/claim calls")
    relayer_retry_backoff_seconds: float = Field(default=0.5, ge=0, description="Backoff between relayer retries")
    relayer_circuit_failure_threshold: int = Field(default=10, ge=1)
    relayer_circuit_window_seconds: int = Field(default=60, ge=1)
    relayer_circuit_cooldown_seconds: int = Field(default=90, ge=1)
    relayer_queue_enabled: bool = Field(default=True, description="Enable Redis-backed relayer job queue fallback")
    relayer_queue_key: str = Field(default="reveal_market:relayer_queue", description="Redis list key for relayer jobs")
    relayer_queue_result_ttl_seconds: int = Field(
        default=3600, ge=60, description="TTL for relayer job results in Redis"
    )
    relayer_queue_max_attempts: int = Field(
        default=5, ge=1, description="Max attempts before marking relayer job failed"
    )
    relayer_webhook_secret: str | None = Field(
        default=None, description="Shared secret for relayer/prover ingestion hooks"
    )
    internal_api_secret: SecretStr | None = Field(
        default=None, description="Shared secret required for internal API endpoints"
    )
    proof_queue_key: str = Field(
        default="reveal_market_worker:proof_queue",
        description="Redis list key for proof generation jobs",
    )
    proof_queue_dedupe_key: str = Field(
        default="reveal_market_worker:proof_queue_dedupe",
        description="Redis set key for proof queue dedupe",
    )
    ticket_size_wei: int = Field(
        default=100_000_000_000_000_000, ge=1, description="Fixed ticket size (wei) used for commitWithAuthorization"
    )
    commit_cutoff_seconds: int = Field(
        default=300, ge=0, description="Seconds before closes_at to halt new commits/quotes"
    )
    relayer_escrow_address: str | None = Field(
        default=None, description="RelayerEscrow contract address for balance lookups"
    )
    commit_nonce_ttl_seconds: int = Field(
        default=600, ge=60, description="TTL (seconds) for commit authorization signatures"
    )
    verifier_address: str | None = Field(default=None, description="Verifier contract address for market creation")
    authorization_signer: str | None = Field(default=None, description="Authorization signer address for markets")
    circuit_hash: str | None = Field(
        default=None, description="Settlement circuit hash for market creation (requires PROVER_CIRCUIT_HASH)"
    )
    market_max_commitments: int = Field(default=10_000, ge=1, description="Max commitments per market")
    market_protocol_liability_cap_wei: int = Field(
        default=0, ge=0, description="Protocol liability cap per market (wei); 0 = unlimited"
    )
    market_commit_lead_seconds: int = Field(
        default=86400, ge=60, description="Seconds from now to set commit deadline when auto-creating markets"
    )
    market_reveal_lead_seconds: int = Field(
        default=172800,
        ge=60,
        description="Seconds after commit deadline to set reveal deadline when auto-creating markets",
    )

    @field_validator("max_page_size")
    @classmethod
    def _validate_page_sizes(cls, value: int, info: ValidationInfo) -> int:
        default_page_size = info.data.get("default_page_size", 50)
        if isinstance(default_page_size, int) and value < default_page_size:
            raise ValueError("max_page_size must be >= default_page_size")
        return value

    @field_validator("circuit_hash", mode="before")
    @classmethod
    def _hydrate_circuit_hash(cls, value: str | None) -> str:
        env_hash = os.getenv("PROVER_CIRCUIT_HASH")
        normalized = _normalize_circuit_hash(env_hash)
        if normalized:
            return normalized
        raise ValueError("PROVER_CIRCUIT_HASH must be set to a 0x-prefixed 32-byte hash")

    @field_validator("circuit_hash")
    @classmethod
    def _validate_circuit_hash(cls, value: str) -> str:
        normalized = _normalize_circuit_hash(value)
        if not normalized:
            raise ValueError("circuit_hash must be a 0x-prefixed 32-byte hash")
        return normalized

    @field_validator(
        "allowed_hosts",
        "cors_allow_origins",
        "cors_allow_methods",
        "cors_allow_headers",
        "market_category_allowlist",
        "rate_limit_whitelist",
        "rate_limit_trusted_proxies",
        mode="before",
    )
    @classmethod
    def _coerce_csv(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return _split_csv(value)
        return value

    @field_validator(
        "goldsky_subgraph_url",
        "goldsky_api_key",
        mode="before",
    )
    @classmethod
    def _none_on_empty(cls, value):
        return _empty_to_none(value)

    @field_validator("rate_limit_enabled", mode="before")
    @classmethod
    def _default_rate_limit(cls, value):
        """Enable rate limiting by default in non-dev environments unless explicitly disabled."""

        env_value = os.getenv("RM_RATE_LIMIT_ENABLED")
        if env_value is not None:
            return value
        env = (os.getenv("RM_ENVIRONMENT") or "development").lower()
        if env not in {"dev", "development", "local", "test", "testing"}:
            return True
        return value

    @property
    def total_monetization_percent(self) -> float:
        """Return the combined monetization percentage (haircut + worsen + rake)."""

        return float(self.rake_percent + self.haircut_percent + self.worsen_percent)

    @property
    def resolved_async_database_url(self) -> str:
        """Return an async-compatible database URL, deriving from the sync URL when needed."""

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
    """Return a cached configuration instance."""
    env_file = os.getenv("SETTINGS_FILE")
    settings_kwargs = {"_env_file": env_file} if env_file else {}
    return Settings(**settings_kwargs)  # type: ignore[arg-type]
