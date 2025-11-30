from __future__ import annotations

from urllib.parse import urlparse, urlunparse

from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STREAMER_", env_file=".env", extra="ignore", env_ignore_empty=True)

    environment: str = Field(default="prod", description="Deployment environment label")
    log_level: str = Field(default="INFO", description="Python logging level")

    redis_url: str = Field(default="redis://redis:6379/0", description="Redis connection string for caching/pubsup")
    clob_ws_url: str = Field(
        default="wss://ws-subscriptions-clob.polymarket.com/ws/market", description="Polymarket CLOB websocket URL"
    )
    clob_rest_markets_url: AnyHttpUrl = Field(
        default="https://gamma-api.polymarket.com/markets",
        description="Polymarket Gamma REST markets endpoint (for seeding token IDs)",
    )
    clob_host: AnyHttpUrl | None = Field(
        default="https://clob.polymarket.com",
        description="Optional Polymarket CLOB host used by py_clob_client for midpoint fetches",
    )
    rtds_ws_url: str = Field(default="wss://ws-live-data.polymarket.com", description="Secondary WS (RTDS market data)")
    rtds_ping_seconds: int = Field(default=10, ge=3, description="RTDS ping interval in seconds")
    rtds_topic_clob: str = Field(default="clob_market", description="RTDS topic for orderbook data")
    fx_primary_rest_url: AnyHttpUrl = Field(
        default="https://api.binance.com/api/v3/ticker/price?symbol=ZENUSDT",
        description="Primary REST fallback for FX (Binance HTTP).",
    )
    fx_secondary_rest_url: AnyHttpUrl | None = Field(
        default="https://min-api.cryptocompare.com/data/price?fsym=ZEN&tsyms=USD",
        description="Secondary REST fallback for FX (CryptoCompare).",
    )
    fx_primary_ws_url: str | None = Field(
        default="wss://stream.binance.com:9443/ws/zenusdt@ticker",
        description="Primary FX websocket (ZEN/USDT ticker).",
    )
    fx_ws_stale_ttl_seconds: int = Field(default=5, ge=3, description="Seconds before FX WS is considered stale")
    fx_max_age_seconds: int = Field(default=60, ge=5, description="Max acceptable age for FX quote before refresh")
    fx_max_jump_percent: float = Field(default=20.0, ge=0, description="Max allowed FX price jump percent")
    fx_jump_window_seconds: int = Field(default=10, ge=1, description="Window in seconds for FX jump detection")
    fx_min_price: float = Field(default=3.0, gt=0, description="Minimum sane FX price")
    fx_max_price: float = Field(default=300.0, gt=0, description="Maximum sane FX price")
    fx_max_consecutive_rejections: int = Field(
        default=3, ge=1, description="Disable WS after this many consecutive FX rejections"
    )
    fx_rest_enabled: bool = Field(default=True, description="Enable REST fallback when WS is stale")
    fx_rest_interval_seconds: int = Field(default=10, ge=5, description="Interval between FX REST refresh attempts")
    fx_timeout_seconds: float = Field(default=5.0, gt=0, description="HTTP timeout for FX REST requests")
    fx_fallback_price: float = Field(default=0.0, ge=0, description="Hard fallback FX price when all sources fail")
    market_stale_seconds: int = Field(default=60, ge=10, description="Threshold to consider market data stale")
    worsen_percent: float = Field(default=0.03, ge=0, lt=0.25, description="Percent worsen applied to displayed odds")
    haircut_percent: float = Field(default=0.12, ge=0, lt=0.25, description="Percent haircut applied to hedging")
    rake_percent: float = Field(default=0.02, ge=0, lt=0.25, description="Protocol rake percent")
    sse_heartbeat_seconds: int = Field(default=15, ge=1, description="SSE heartbeat interval")
    rest_poll_seconds: int = Field(default=30, ge=5, description="CLOB REST poll interval")
    ws_reconnect_seconds: float = Field(default=5.0, ge=0.01, description="Backoff between WS reconnect attempts")
    rtds_enabled: bool = Field(default=False, description="Enable RTDS websocket ingestion (disabled by default)")
    publish_throttle_ms: int = Field(default=300, ge=50, description="Throttle for publishing ticks to Redis (ms)")
    max_subscriptions: int = Field(default=200, ge=1, description="Maximum tracked upstream subscriptions")
    cache_prefix: str = Field(default="streamer:latest", description="Redis key prefix for latest ticks")
    pubsub_prefix: str = Field(default="streamer:stream", description="Redis pubsub channel prefix for streams")
    history_prefix: str = Field(default="streamer:history", description="Redis key prefix for tick history")
    history_limit: int = Field(default=500, ge=10, description="Max history entries per outcome")
    history_ttl_seconds: int = Field(
        default=86400, ge=0, description="Optional TTL for per-outcome history keys (0 disables expiration)"
    )
    history_debounce_seconds: float = Field(
        default=0.0, ge=0.0, description="Minimum seconds between history entries for the same market/outcome"
    )
    api_host: str = Field(default="0.0.0.0", description="Host binding for FastAPI app")  # noqa: S104 - intentional
    api_port: int = Field(default=8100, description="Port for FastAPI app")
    signing_secret: str | None = Field(default=None, description="Optional HMAC secret to sign payloads")
    control_token: str | None = Field(
        default=None, description="Optional token required for control/ops endpoints (set to enable mutations)"
    )
    access_token: str | None = Field(default=None, description="Optional token required for SSE/WS client access")
    max_active_connections: int = Field(
        default=1000, ge=1, description="Maximum concurrent SSE/WS connections (process-local guard)"
    )
    rate_limit_per_minute: int = Field(
        default=0, ge=0, description="Optional per-client request/connection cap per minute (0 disables)"
    )
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"], description="CORS allow-origins list")
    cors_allow_methods: list[str] = Field(default_factory=lambda: ["*"], description="CORS allow-methods list")
    cors_allow_headers: list[str] = Field(default_factory=lambda: ["*"], description="CORS allow-headers list")
    cors_allow_credentials: bool = Field(default=False, description="CORS allow-credentials flag")
    public_base_url: AnyHttpUrl | None = Field(
        default="https://stream.revealmarket.xyz", description="Public HTTPS streamer host used by browsers."
    )
    internal_base_url: AnyHttpUrl | None = Field(
        default="http://streamer:8100", description="Internal streamer host used by server components."
    )

    @property
    def total_monetization(self) -> float:
        return self.worsen_percent + self.haircut_percent + self.rake_percent

    @field_validator("cors_allow_origins", "cors_allow_methods", "cors_allow_headers", mode="before")
    @classmethod
    def _coerce_csv(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("fx_primary_ws_url", mode="before")
    @classmethod
    def _normalize_fx_ws(cls, value: str | None):
        if value is None:
            return value
        if not isinstance(value, str):
            return value
        parsed = urlparse(value)
        if parsed.scheme and parsed.scheme.lower() != "wss":
            raise ValueError("STREAMER_FX_PRIMARY_WS_URL must use wss://")
        path = (parsed.path or "").lower()
        if not (path.startswith("/ws/") or path.startswith("/stream")):
            raise ValueError("STREAMER_FX_PRIMARY_WS_URL must include /ws/<stream> or /stream?streams=…")
        normalized = urlunparse(
            (
                "wss",
                parsed.netloc,
                path,
                parsed.params,
                parsed.query,
                parsed.fragment,
            )
        )
        return normalized

    @field_validator("clob_ws_url", mode="before")
    @classmethod
    def _normalize_clob_ws(cls, value: str):
        parsed = urlparse(value)
        if parsed.scheme and parsed.scheme.lower() != "wss":
            raise ValueError("STREAMER_CLOB_WS_URL must use wss://")
        path = (parsed.path or "").lower()
        # Require a concrete channel (e.g., /ws/market or /ws/user)
        if not path.startswith("/ws/") or path.rstrip("/").count("/") < 2:
            raise ValueError("STREAMER_CLOB_WS_URL must include /ws/<channel>")
        return urlunparse(
            (
                "wss",
                parsed.netloc,
                path,
                parsed.params,
                parsed.query,
                parsed.fragment,
            )
        )

    @field_validator("public_base_url")
    @classmethod
    def _require_https(cls, value: AnyHttpUrl | None):
        if value and value.scheme != "https":
            raise ValueError("STREAMER_PUBLIC_BASE_URL must use https://")
        return value

    @property
    def cors_allow_origins_resolved(self) -> list[str]:
        """Return the configured CORS origins, normalized and deduplicated."""

        if self.cors_allow_origins == ["*"]:
            return ["*"]

        normalized: list[str] = []
        for origin in self.cors_allow_origins:
            trimmed = origin.rstrip("/")
            if trimmed and trimmed not in normalized:
                normalized.append(trimmed)

        return normalized


def get_settings() -> Settings:
    from functools import lru_cache

    @lru_cache(maxsize=1)
    def _load() -> Settings:
        return Settings()  # type: ignore[call-arg]

    return _load()
