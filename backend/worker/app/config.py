"""Configuration primitives for the worker service."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from pydantic import AliasChoices, AnyHttpUrl, AnyUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime options sourced from env vars/`.env` for the worker."""

    model_config = SettingsConfigDict(env_prefix="RM_")

    database_url: str = Field(
        default="postgresql+psycopg2://market_admin:<REDACTED>@postgres:5432/reveal_market"
    )
    redis_url: str = Field(default="redis://redis:6379/0")
    polymarket_api_base: AnyHttpUrl = Field(default="https://gamma-api.polymarket.com")
    polymarket_timeout_seconds: float = Field(default=10.0, gt=0)
    polymarket_page_size: int = Field(default=100, ge=1, le=250)
    polymarket_max_pages: Optional[int] = Field(default=None, ge=1)
    polymarket_order: str = Field(default="id")
    polymarket_sort_ascending: bool = Field(default=False)
    polymarket_closed_filter: Optional[bool] = Field(default=None)
    poll_interval_seconds: int = Field(default=30, ge=1)
    heartbeat_key: str = Field(default="reveal_market_worker:heartbeat")
    heartbeat_ttl_seconds: int = Field(default=120, ge=10)
    factory_address: Optional[str] = Field(default=None)
    rake_manager_address: Optional[str] = Field(default=None)
    verifier_address: Optional[str] = Field(default=None)
    rpc_url: Optional[AnyUrl] = Field(default=None)
    polygon_rpc_url: Optional[AnyUrl] = Field(
        default=None,
        validation_alias=AliasChoices("RM_POLYGON_RPC_URL", "POLYGON_RPC_URL"),
    )
    conditional_tokens_address: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("RM_POLYGON_CTF_ADDRESS", "POLYGON_CTF_ADDRESS"),
    )
    clob_host: Optional[AnyHttpUrl] = Field(
        default=None,
        validation_alias=AliasChoices("RM_POLYMARKET_CLOB_HOST", "POLYMARKET_CLOB_HOST"),
    )
    wallet_address: Optional[str] = Field(default=None)
    wallet_private_key: Optional[SecretStr] = Field(default=None)
    gas_price_gwei: Optional[float] = Field(default=None, ge=0)
    max_priority_fee_gwei: Optional[float] = Field(default=None, ge=0)
    auto_create_onchain_markets: bool = Field(default=False)
    default_commit_lead_seconds: int = Field(default=86400, ge=60)
    default_reveal_lead_seconds: int = Field(default=172800, ge=120)
    max_web3_retries: int = Field(default=3, ge=1)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings object, respecting optional env files."""
    env_file = os.getenv("SETTINGS_FILE")
    kwargs = {"_env_file": env_file} if env_file else {}
    return Settings(**kwargs)  # type: ignore[arg-type]
