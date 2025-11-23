from __future__ import annotations

from pydantic import AliasChoices, AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STREAMER_", env_file=".env", extra="ignore")

    environment: str = Field(default="prod", validation_alias=AliasChoices("MODE", "ENVIRONMENT"))
    log_level: str = Field(default="INFO", validation_alias=AliasChoices("LOG_LEVEL"))

    redis_url: str = Field(
        default="redis://redis:6379/0", validation_alias=AliasChoices("STREAMER_REDIS_URL", "RM_REDIS_URL")
    )
    clob_ws_url: str = Field(default="wss://ws-subscriptions-clob.polymarket.com/market")
    clob_rest_markets_url: AnyHttpUrl = Field(default="https://gamma-api.polymarket.com/markets")
    rtds_ws_url: str = Field(default="wss://ws-live-data.polymarket.com")
    rtds_crypto_symbols: str | None = Field(
        default=None, description="Comma-separated symbols for crypto_prices (e.g., zenusdt,ethusdt)"
    )
    rtds_enabled: bool = Field(default=True)
    fx_feed_url: AnyHttpUrl = Field(default="https://gamma-api.polymarket.com/prices/zen-usd")
    fx_timeout_seconds: float = Field(default=5.0, gt=0)
    fx_fallback_price: float = Field(default=1.0, gt=0)
    worsen_percent: float = Field(default=0.03, ge=0, lt=0.25)
    haircut_percent: float = Field(default=0.12, ge=0, lt=0.25)
    rake_percent: float = Field(default=0.02, ge=0, lt=0.25)
    sse_heartbeat_seconds: int = Field(default=15, ge=1)
    rest_poll_seconds: int = Field(default=30, ge=5)
    ws_reconnect_seconds: int = Field(default=5, ge=1)
    publish_throttle_ms: int = Field(default=300, ge=50)
    max_subscriptions: int = Field(default=200, ge=1)
    cache_prefix: str = Field(default="price_streamer:latest")
    pubsub_prefix: str = Field(default="price_streamer:stream")
    history_prefix: str = Field(default="price_streamer:history")
    history_limit: int = Field(default=500, ge=10)
    api_host: str = Field(default="0.0.0.0")  # noqa: S104 - intentional service binding inside docker
    api_port: int = Field(default=8100)
    signing_secret: str | None = Field(default=None, description="Optional HMAC secret to sign payloads")

    @property
    def total_monetisation(self) -> float:
        return self.worsen_percent + self.haircut_percent + self.rake_percent


def get_settings() -> Settings:
    from functools import lru_cache

    @lru_cache(maxsize=1)
    def _load() -> Settings:
        return Settings()  # type: ignore[call-arg]

    return _load()
