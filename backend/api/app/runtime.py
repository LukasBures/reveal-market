"""Runtime state shared across the API process.

The FastAPI app imports this module once and then other modules attach handles
for Redis, background tasks, and metrics. Keeping these globals in one place
makes it easier for tests to override them while staying async-native.
"""

from __future__ import annotations

import asyncio
import logging
from threading import Event

import httpx
from prometheus_fastapi_instrumentator import Instrumentator
from redis.asyncio import Redis
from shared.db_metrics import attach_db_metrics
from shared.env_presets import get_preset, resolve_mode
from shared.indexers import AsyncGoldskyClient

from app.config import get_settings
from app.metrics import RequestMetrics

settings = get_settings()
logger = logging.getLogger("reveal_market.api")
mode_env = resolve_mode()
is_production = mode_env == "prod" or settings.environment.lower() == "production"
preset = get_preset()

TRENDING_MIN_LIQUIDITY = 0
TRENDING_MIN_VOLUME_24H = 0
TRENDING_MIN_ORDERBOOK = 0
TRENDING_MIN_TRADES = 0
TRENDING_MIN_SCORE = 0.0


def _sanitize_settings() -> dict[str, object]:
    sensitive_keys = {
        "database_url",
        "database_async_url",
        "redis_url",
        "rpc_url",
        "relayer_bearer_token",
    }
    redacted: dict[str, object] = {}
    for key, value in settings.model_dump().items():
        lower = key.lower()
        if lower in sensitive_keys or any(
            token in lower for token in ["key", "secret", "password", "token", "private"]
        ):
            continue
        redacted[key] = value
    return redacted


sanitized_config = _sanitize_settings()

instrumentator = Instrumentator()
# RequestMetrics tracks rolling latency/throughput to publish API heartbeats.
request_metrics = RequestMetrics(settings.slow_request_threshold_ms)

cache_client: Redis | None = None
cache_lock = asyncio.Lock()
shared_http_clients: dict[float, httpx.AsyncClient] = {}
shared_http_lock = asyncio.Lock()
heartbeat_stop_event: Event | None = None
metrics_task: asyncio.Task | None = None
cache_refresh_task: asyncio.Task | None = None
quote_sweeper_task: asyncio.Task | None = None
relayer_queue_task: asyncio.Task | None = None
goldsky_client: AsyncGoldskyClient | None = None


def configure_db_metrics(engine) -> None:
    attach_db_metrics(engine)
