from __future__ import annotations

import os
from functools import lru_cache

from pydantic import AliasChoices, AnyHttpUrl, AnyUrl, Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the Reveal Market API service."""

    model_config = SettingsConfigDict(env_prefix="RM_")

    app_name: str = Field(default="Reveal Market API")
    environment: str = Field(default="development")
    version: str = Field(default="1.0.0")

    database_url: str = Field(
        default="postgresql+psycopg2://market_admin:<REDACTED>@postgres:5432/reveal_market"
    )
    database_echo: bool = Field(default=False)
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    redis_url: str = Field(default="redis://redis:6379/0")
    factory_address: str | None = Field(default=None)
    market_implementation_address: str | None = Field(default=None)
    rake_manager_address: str | None = Field(default=None)
    verifier_address: str | None = Field(default=None)
    rpc_url: AnyUrl | None = Field(default=None)
    wallet_address: str | None = Field(default=None)
    wallet_private_key: SecretStr | None = Field(default=None)
    gas_price_gwei: float | None = Field(default=None, ge=0)
    max_priority_fee_gwei: float | None = Field(default=None, ge=0)
    cache_ttl_seconds: int = Field(default=30, ge=1)

    polymarket_api_base: AnyHttpUrl = Field(default="https://gamma-api.polymarket.com")
    polymarket_timeout_seconds: float = Field(default=5.0)
    polymarket_order: str = Field(default="id")
    polymarket_sort_ascending: bool = Field(default=False)
    polymarket_closed_filter: bool | None = Field(default=None)
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

    default_page_size: int = Field(default=50)
    max_page_size: int = Field(default=250)

    @field_validator("max_page_size")
    @classmethod
    def _validate_page_sizes(cls, value: int, info: ValidationInfo) -> int:
        default_page_size = info.data.get("default_page_size", 50)
        if isinstance(default_page_size, int) and value < default_page_size:
            raise ValueError("max_page_size must be >= default_page_size")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached configuration instance."""
    env_file = os.getenv("SETTINGS_FILE")
    settings_kwargs = {"_env_file": env_file} if env_file else {}
    return Settings(**settings_kwargs)  # type: ignore[arg-type]
