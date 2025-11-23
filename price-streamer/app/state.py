from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from redis.asyncio import Redis
from websockets import connect

from .config import Settings, get_settings
from .subscriptions import SubscriptionManager

logger = logging.getLogger("reveal_market.price_streamer")


@dataclass(slots=True)
class FxQuote:
    zen_usd: Decimal
    fetched_at: datetime
    stale: bool


class StreamState:
    """Holds connections to Redis and FX cache."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.redis: Redis | None = None
        self.fx_quote: FxQuote | None = None
        self.fx_last_update: datetime | None = None
        self._fx_lock = asyncio.Lock()
        self.subscriptions = SubscriptionManager(max_items=self.settings.max_subscriptions)
        self.last_seen: dict[str, datetime] = {}
        self.last_published: dict[str, datetime] = {}
        self.tick_sizes: dict[str, Decimal] = {}
        self._rtds_connected = False
        self.rtds_symbols: set[str] = set()

    async def startup(self) -> None:
        self.redis = Redis.from_url(self.settings.redis_url, decode_responses=True)
        await self.refresh_fx()

    async def shutdown(self) -> None:
        if self.redis:
            await self.redis.aclose()

    async def refresh_fx(self) -> FxQuote:
        async with self._fx_lock:
            try:
                async with httpx.AsyncClient(timeout=self.settings.fx_timeout_seconds) as client:
                    res = await client.get(self.settings.fx_feed_url)
                    res.raise_for_status()
                    data = res.json()
                    price = data.get("price") or data.get("zen_usd") or data.get("zenUSD")
                    if price is None:
                        raise ValueError("FX feed missing zen_usd/price")
                    quote = FxQuote(zen_usd=Decimal(str(price)), fetched_at=datetime.now(UTC), stale=False)
                    self.fx_quote = quote
                    return quote
            except Exception as exc:  # pragma: no cover - network fallback
                logger.warning(
                    "FX refresh failed, falling back", extra={"event": "fx.refresh.failed", "error": str(exc)}
                )
                fallback = FxQuote(
                    zen_usd=Decimal(str(self.settings.fx_fallback_price)),
                    fetched_at=datetime.now(UTC),
                    stale=True,
                )
                self.fx_quote = fallback
                self.fx_last_update = fallback.fetched_at
                return fallback

    async def get_fx(self) -> FxQuote:
        if not self.fx_quote:
            return await self.refresh_fx()
        # Mark stale if older than threshold.
        if (
            self.fx_last_update
            and (datetime.now(UTC) - self.fx_last_update).total_seconds() > self.settings.fx_stale_after_seconds
        ):
            self.fx_quote = FxQuote(zen_usd=self.fx_quote.zen_usd, fetched_at=self.fx_last_update, stale=True)
        return self.fx_quote

    async def cache_tick(self, market_id: str, outcome: str, payload: dict) -> None:
        if not self.redis:
            return
        key = f"{self.settings.cache_prefix}:{market_id}:{outcome}"
        channel = f"{self.settings.pubsub_prefix}:{market_id}"
        mapping = {k: str(v) for k, v in payload.items()}
        if self.settings.signing_secret:
            mapping["sig"] = self._sign_payload(mapping)
        await self.redis.hset(key, mapping=mapping)
        await self.redis.publish(channel, json.dumps(mapping))
        self.last_seen[market_id] = datetime.now(UTC)
        self.last_published[market_id] = datetime.now(UTC)
        history_key = f"{self.settings.history_prefix}:{market_id}:{outcome}"
        await self.redis.lpush(history_key, json.dumps(mapping))
        await self.redis.ltrim(history_key, 0, self.settings.history_limit - 1)

    async def subscribe(self, market_id: str):
        if not self.redis:
            raise RuntimeError("Redis not initialised")
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(f"{self.settings.pubsub_prefix}:{market_id}")
        return pubsub

    async def get_history(self, market_id: str, outcome: str, limit: int) -> list[dict]:
        if not self.redis:
            return []
        history_key = f"{self.settings.history_prefix}:{market_id}:{outcome}"
        raw = await self.redis.lrange(history_key, 0, max(0, limit - 1))
        records = []
        for item in raw:
            try:
                parsed = json.loads(item)
                records.append(parsed)
            except Exception as exc:
                logger.debug(
                    "skipping malformed history entry", extra={"event": "history.parse.failed", "error": str(exc)}
                )
        return list(reversed(records))

    def stale_markets(self, stale_after_seconds: int = 60) -> list[str]:
        cutoff = datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
        return [mid for mid, ts in self.last_seen.items() if ts < cutoff]

    def _sign_payload(self, payload: dict) -> str:
        secret = self.settings.signing_secret
        if not secret:
            return ""
        message = "|".join(f"{k}:{payload[k]}" for k in sorted(payload.keys()))
        digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        return digest


async def iter_ws(ws_url: str):
    """Yield websocket connections, reconnecting on drop."""

    while True:
        try:
            async with connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
                yield ws
        except Exception as exc:  # pragma: no cover - reconnection path
            logger.warning("ws dropped; reconnecting", extra={"event": "ws.reconnect", "error": str(exc)})
            await asyncio.sleep(get_settings().ws_reconnect_seconds)
