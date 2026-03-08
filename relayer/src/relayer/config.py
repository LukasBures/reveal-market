"""Configuration for the relayer service — Pydantic BaseSettings with RM_ prefix."""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, DotEnvSettingsSource, EnvSettingsSource, SettingsConfigDict

IPAllowEntry = ipaddress.IPv4Address | ipaddress.IPv6Address | ipaddress.IPv4Network | ipaddress.IPv6Network


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


class RelayerSettings(BaseSettings):
    """Runtime options sourced from env vars / .env for the relayer."""

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

    # --- Core chain config ---
    rpc_url: str
    chain_id: int

    # --- Relayer identity ---
    relayer_private_key: str
    relayer_escrow_address: str

    # --- Server binding ---
    relayer_host: str = Field(default="0.0.0.0")
    relayer_port: int = Field(default=8088)

    # --- Auth ---
    relayer_bearer_token: str | None = Field(default=None)
    relayer_allow_insecure_auth: bool = Field(default=False)

    # --- Chain health ---
    relayer_max_block_age_seconds: int = Field(default=60)
    relayer_min_balance_wei: int = Field(default=0)

    # --- Retry ---
    relayer_max_retries: int = Field(default=3, ge=1)
    relayer_retry_backoff_seconds: float = Field(default=0.5, ge=0)
    relayer_tx_timeout_seconds: int = Field(default=120, ge=1)

    # --- Queue ---
    relayer_queue_db_path: str = Field(default="relayer_queue.db")
    database_url: str | None = Field(default=None)
    relayer_queue_poll_seconds: float = Field(default=1.0, ge=0.1)
    relayer_queue_max_attempts: int = Field(default=5, ge=1)
    relayer_queue_max_payload_bytes: int = Field(default=131072, gt=0)
    relayer_queue_running_ttl_seconds: int | None = Field(default=None)

    # --- Fee / balance ---
    relayer_fee_bump_percent: float = Field(default=0.15, ge=0)
    relayer_min_escrow_token_balance_wei: int = Field(default=0)
    relayer_min_relayer_token_allowance_wei: int = Field(default=0)

    # --- HTTP ---
    relayer_http_timeout_seconds: int = Field(default=10, ge=1)

    # --- Preflight ---
    relayer_preflight_mode: str = Field(default="none")

    # --- Rate limiting ---
    relayer_rate_limit_requests: int = Field(default=30, ge=0)
    relayer_rate_limit_window_seconds: int = Field(default=60, ge=0)

    # --- IP allowlist ---
    relayer_ip_allowlist: list[IPAllowEntry] = Field(default_factory=list)
    relayer_trust_x_forwarded_for: bool = Field(default=False)
    relayer_trusted_proxy_cidrs: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = Field(default_factory=list)

    # --- API client (relayer → backend API) ---
    relayer_api_base_url: str | None = Field(default=None)
    relayer_api_bearer_token: str | None = Field(default=None)
    relayer_api_internal_secret: str | None = Field(default=None)
    relayer_api_timeout_seconds: int = Field(default=10, ge=1)
    relayer_health_deep_cache_ttl_seconds: int = Field(default=10, ge=0)
    relayer_api_client_max_age_seconds: int = Field(default=900, ge=0)
    relayer_api_health_failure_cooldown_seconds: int = Field(default=15, ge=0)

    # --- RPC circuit breaker ---
    relayer_rpc_circuit_breaker_threshold: int = Field(default=5, ge=1)
    relayer_rpc_circuit_breaker_window_seconds: float = Field(default=30.0, ge=0)
    relayer_rpc_circuit_breaker_cooldown_seconds: float = Field(default=30.0, ge=0)

    # --- Validators ---

    @field_validator("relayer_preflight_mode", mode="before")
    @classmethod
    def _normalize_preflight(cls, value: Any) -> str:
        if not isinstance(value, str):
            return str(value)
        mode = value.strip().lower()
        if mode in ("", "none", "off", "false", "0"):
            return "none"
        if mode in ("true", "1", "yes"):
            return "both"
        if mode in ("call", "estimate", "both"):
            return mode
        raise ValueError(f"Invalid preflight mode: {value}")

    @field_validator("relayer_ip_allowlist", mode="before")
    @classmethod
    def _parse_ip_allowlist(cls, value: Any) -> list[IPAllowEntry]:
        if isinstance(value, list):
            return value
        if not isinstance(value, str) or not value.strip():
            return []
        entries: list[IPAllowEntry] = []
        for item in value.split(","):
            v = item.strip()
            if not v:
                continue
            if "/" in v:
                entries.append(ipaddress.ip_network(v, strict=False))
            else:
                entries.append(ipaddress.ip_address(v))
        return entries

    @field_validator("relayer_trusted_proxy_cidrs", mode="before")
    @classmethod
    def _parse_proxy_cidrs(cls, value: Any) -> list:
        if isinstance(value, list):
            return value
        if not isinstance(value, str) or not value.strip():
            return []
        entries = []
        for item in value.split(","):
            v = item.strip()
            if not v:
                continue
            entries.append(ipaddress.ip_network(v, strict=False))
        return entries

    @model_validator(mode="after")
    def _compute_defaults_and_validate(self) -> RelayerSettings:
        # Derived default: queue_running_ttl_seconds
        if self.relayer_queue_running_ttl_seconds is None:
            object.__setattr__(self, "relayer_queue_running_ttl_seconds", self.relayer_tx_timeout_seconds + 30)

        # Bearer token requirement
        if not self.relayer_bearer_token and not self.relayer_allow_insecure_auth:
            raise ValueError("RM_RELAYER_BEARER_TOKEN is required unless RM_RELAYER_ALLOW_INSECURE_AUTH=true")

        # Rate limit constraint
        if self.relayer_rate_limit_requests > 0 and self.relayer_rate_limit_window_seconds <= 0:
            raise ValueError("RM_RELAYER_RATE_LIMIT_WINDOW_SECONDS must be > 0 when rate limiting is enabled")

        return self

    @property
    def queue_dsn(self) -> str | None:
        """Derive async-compatible queue DSN from RM_DATABASE_URL."""
        dsn = self.database_url
        if dsn and dsn.startswith("postgresql+psycopg2://"):
            dsn = "postgresql://" + dsn.split("postgresql+psycopg2://", 1)[1]
        return dsn


@lru_cache(maxsize=1)
def get_settings(**kwargs: Any) -> RelayerSettings:
    """Return a cached RelayerSettings instance."""
    return RelayerSettings(**kwargs)  # type: ignore[arg-type]


def reload_settings() -> RelayerSettings:
    """Clear cached settings and rebuild from the environment."""
    get_settings.cache_clear()
    return get_settings()


# Backward-compatible aliases
def load_config() -> RelayerSettings:
    return get_settings()


RelayerConfig = RelayerSettings
