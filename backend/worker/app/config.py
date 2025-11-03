"""Configuration primitives for the worker service."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime options sourced from env vars/`.env` for the worker."""

    model_config = SettingsConfigDict(env_prefix="RM_")

    database_url: str = Field(
        default="postgresql+psycopg2://market_admin:<REDACTED>@postgres:5432/reveal_market"
    )
    redis_url: str = Field(default="redis://redis:6379/0")
    polymarket_api_base: AnyHttpUrl = Field(default="https://strapi-matic.poly.market/api/markets")
    poll_interval_seconds: int = Field(default=30, ge=1)
    polymarket_timeout_seconds: float = Field(default=10.0, gt=0)
    polymarket_page_size: int = Field(default=100, ge=1, le=250)
    polymarket_max_pages: Optional[int] = Field(default=None, ge=1)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings object, respecting optional env files."""
    env_file = os.getenv("SETTINGS_FILE")
    kwargs = {"_env_file": env_file} if env_file else {}
    return Settings(**kwargs)  # type: ignore[arg-type]
