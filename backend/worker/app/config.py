import os
from dataclasses import dataclass


@dataclass
class Settings:
    database_url: str = os.getenv(
        "RM_DATABASE_URL", "postgresql+psycopg2://market_admin:<REDACTED>@postgres:5432/reveal_market"
    )
    redis_url: str = os.getenv("RM_REDIS_URL", "redis://redis:6379/0")
    polymarket_api_base: str = os.getenv("RM_POLYMARKET_API_BASE", "https://strapi-matic.poly.market/api/markets")
    poll_interval_seconds: int = int(os.getenv("RM_WORKER_POLL_INTERVAL", "30"))


settings = Settings()
