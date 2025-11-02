from __future__ import annotations

import os
from functools import lru_cache

from pydantic import AnyHttpUrl, BaseSettings, Field


class Settings(BaseSettings):
    database_url: str = Field(
        default="postgresql+psycopg2://market_admin:<REDACTED>@postgres:5432/reveal_market"
    )
    redis_url: str = Field(default="redis://redis:6379/0")
    polymarket_api_base: AnyHttpUrl = Field(default="https://strapi-matic.poly.market/api/markets")
    poll_interval_seconds: int = Field(default=30)
    polymarket_timeout_seconds: float = Field(default=10.0)

    class Config:
        env_prefix = "RM_"
        env_file = os.getenv("SETTINGS_FILE", None)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[arg-type]
