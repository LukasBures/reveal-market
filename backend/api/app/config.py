from __future__ import annotations

import os
from functools import lru_cache

from pydantic import AnyHttpUrl, BaseSettings, Field, field_validator


class Settings(BaseSettings):
    """Runtime configuration for the Reveal Market API service."""

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

    class Config:
        env_prefix = "RM_"
        env_file = os.getenv("SETTINGS_FILE", None)

    @field_validator("max_page_size")
    @classmethod
    def _validate_page_sizes(cls, value: int, values: dict[str, object]) -> int:
        default_page_size = values.get("default_page_size", 50)
        if isinstance(default_page_size, int) and value < default_page_size:
            raise ValueError("max_page_size must be >= default_page_size")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached configuration instance."""
    return Settings()  # type: ignore[arg-type]
