"""Runtime state shared across the API process.

The FastAPI app imports this module once and then other modules attach handles
for Redis, background tasks, and metrics. Keeping these globals in one place
makes it easier for tests to override them while staying async-native.
"""

from __future__ import annotations

import asyncio
import logging
from threading import Event

from prometheus_fastapi_instrumentator import Instrumentator
from redis.asyncio import Redis
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

sanitized_config = {
    key: value
    for key, value in settings.model_dump().items()
    if not any(secret in key for secret in ["key", "private", "secret", "password"])
}

instrumentator = Instrumentator()
# RequestMetrics tracks rolling latency/throughput to publish API heartbeats.
request_metrics = RequestMetrics(settings.slow_request_threshold_ms)

cache_client: Redis | None = None
cache_lock = asyncio.Lock()
heartbeat_stop_event: Event | None = None
metrics_task: asyncio.Task | None = None
cache_refresh_task: asyncio.Task | None = None
quote_sweeper_task: asyncio.Task | None = None
goldsky_client: AsyncGoldskyClient | None = None
