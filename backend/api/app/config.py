from __future__ import annotations

import os
from functools import lru_cache

from pydantic import AnyHttpUrl, Field, ValidationInfo, field_validator
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
    redis_url: str = Field(default="redis://redis:6379/0")

    polymarket_api_base: AnyHttpUrl = Field(default="https://strapi-matic.poly.market/api/markets")
    polymarket_timeout_seconds: float = Field(default=5.0)

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
