from __future__ import annotations

import os
from decimal import Decimal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .storage import ensure_async_db_url


class Settings(BaseSettings):
    """Environment-driven configuration for the hedger."""

    model_config = SettingsConfigDict(env_prefix="HEDGER_", env_file=".env", extra="ignore")

    environment: str = Field(default="prod")
    log_level: str = Field(default="INFO")
    api_host: str = Field(default="0.0.0.0")  # noqa: S104 - service must bind for docker/compose
    api_port: int = Field(default=8090)

    database_url: str = Field(
        default="postgresql+asyncpg://market_admin:<REDACTED>@postgres:5432/reveal_market",
        validation_alias=AliasChoices("RM_DATABASE_URL", "HEDGER_DATABASE_URL"),
    )
    redis_url: str = Field(default="redis://redis:6379/0")

    polymarket_api_base: str = Field(default="https://gamma-api.polymarket.com")
    polymarket_timeout_seconds: int = Field(default=10)
    polymarket_retry_attempts: int = Field(default=3)
    polymarket_retry_backoff_seconds: float = Field(default=0.5)

    fx_feed_url: str = Field(
        default="http://streamer:8100/fx/zen-usd",
        description="Primary FX feed (align with API/streamer endpoint).",
    )
    fx_feed_alt_url: str | None = Field(
        default=None,
        description="Optional secondary FX feed used only if the primary feed is unreachable or stale.",
    )
    fx_timeout_seconds: int = Field(default=5)
    fx_max_age_seconds: int = Field(default=60)
    fx_haircut_bps: int = Field(default=500, description="FX haircut in basis points (500 = 5%)")
    fx_fallback_price: Decimal = Field(default=Decimal("1"), description="Fallback ZEN/USD price when feed is down")
    pricing_signer_address: str | None = Field(
        default=None, description="Expected signer address for API-issued quotes (optional validation)."
    )

    redis_lock_ttl_seconds: int = Field(default=10)
    redis_idempotency_ttl_seconds: int = Field(default=86400)
    commit_stream_name: str = Field(default="horizen_commits")

    max_slippage_bps: int = Field(default=100, description="Maximum acceptable slippage for hedges")

    risk_max_global_exposure_usd: Decimal = Field(default=Decimal("250000"))
    risk_max_per_market_usd: Decimal = Field(default=Decimal("75000"))
    risk_coverage_ratio_target: float = Field(default=0.98)
    risk_lp_utilization_limit: float = Field(default=0.85)
    float_min_zen: Decimal = Field(default=Decimal("5000"))
    risk_max_commit_zen: Decimal = Field(
        default=Decimal("1000"),
        ge=Decimal("0"),
        description="Per-commit stake limit in ZEN",
    )
    rake_percent: Decimal = Field(default=Decimal("0.02"), ge=Decimal("0"), lt=Decimal("0.25"))
    haircut_percent: Decimal = Field(default=Decimal("0.12"), ge=Decimal("0"), lt=Decimal("0.25"))
    worsen_percent: Decimal = Field(default=Decimal("0.03"), ge=Decimal("0"), lt=Decimal("0.25"))
    lp_share_percent: Decimal = Field(default=Decimal("0.18"), ge=Decimal("0"), lt=Decimal("0.5"))
    vault_rpc_url: str | None = Field(default="http://localhost:8545")
    vault_private_key: str | None = Field(default="0x" + "00" * 31 + "01")
    vault_sender_address: str | None = Field(default="0x" + "00" * 19 + "01")
    vault_chain_id: int = Field(default=1337, ge=1)
    vault_gas_price_gwei: int | None = Field(default=5, ge=0)

    settlement_poll_seconds: int = Field(default=20)
    heartbeat_interval_seconds: int = Field(default=60)
    event_poll_interval_seconds: int = Field(default=10)
    run_migrations_on_startup: bool = Field(default=True)
    metrics_enabled: bool = Field(default=True)

    prover_base_url: str = Field(default="http://prover:8085")
    prover_timeout_seconds: int = Field(default=30)
    prover_shared_secret: str | None = Field(default=None)
    bridge_endpoint: str = Field(default="https://bridge.revealmarket.xyz/submit")
    lp_vault_address: str = Field(default="0x0000000000000000000000000000000000000000")

    @property
    def total_monetisation(self) -> Decimal:
        return self.haircut_percent + self.worsen_percent + self.rake_percent


def get_settings() -> Settings:
    """Load settings once per process."""

    from functools import lru_cache

    @lru_cache(maxsize=1)
    def _load() -> Settings:
        cfg = Settings()  # type: ignore[call-arg]
        rm_dsn = os.getenv("RM_DATABASE_URL")
        if rm_dsn:
            cfg.database_url = ensure_async_db_url(rm_dsn)
        else:
            cfg.database_url = ensure_async_db_url(cfg.database_url)
        return cfg

    return _load()
