from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
from pydantic import AnyHttpUrl
from redis.asyncio import Redis
from websockets import connect
from websockets.exceptions import InvalidStatus

from .config import Settings, get_settings, redact_url
from .subscriptions import SubscriptionManager

if TYPE_CHECKING:
    from .metrics import StreamerMetrics

logger = logging.getLogger("reveal_market.streamer")

shared_http_clients: dict[float, httpx.AsyncClient] = {}
shared_http_lock = asyncio.Lock()


async def get_http_client(timeout: float) -> httpx.AsyncClient:
    timeout_value = float(timeout)
    async with shared_http_lock:
        client = shared_http_clients.get(timeout_value)
        if client is not None and getattr(client, "is_closed", False):
            await client.aclose()
            shared_http_clients.pop(timeout_value, None)
            client = None
        if client is None:
            client = httpx.AsyncClient(timeout=timeout_value)
            shared_http_clients[timeout_value] = client
        return client


class FatalWebsocketError(Exception):
    """Raised when a websocket handshake fails with a fatal status code."""

    def __init__(self, status_code: int, url: str):
        super().__init__(f"ws rejected with status {status_code} ({url})")
        self.status_code = status_code
        self.url = url


@dataclass(slots=True)
class FxQuote:
    zen_usd: Decimal
    fetched_at: datetime
    stale: bool
    raw_zen_usd: Decimal | None = None
    source: str = "unknown"


class StreamState:
    """Holds connections to Redis and FX cache."""

    _SOURCE_PRIORITY: dict[str, int] = {
        "binance_ws": 0,
        "binance_rest": 1,
        "cryptocompare_rest": 2,
    }
    _WS_SOURCES: set[str] = {"binance_ws"}

    def __init__(self, settings: Settings | None = None, metrics: StreamerMetrics | None = None):
        self.settings = settings or get_settings()
        self.redis: Redis | None = None
        self.redis_error: str | None = None
        self.fx_quote: FxQuote | None = None
        self.fx_last_update: datetime | None = None
        self.fx_ws_last_update: datetime | None = None
        self.fx_last_source: str | None = None
        self.fx_ws_connected: bool = False
        self.fx_last_error: str | None = None
        self._fx_prev_price: Decimal | None = None
        self._fx_prev_price_ts: datetime | None = None
        self._fx_rejection_count: int = 0
        self._fx_lock = asyncio.Lock()
        self.clob_ws_connected: bool = False
        self.clob_ws_last_message: datetime | None = None
        self.clob_ws_last_connect: datetime | None = None
        self.clob_ws_last_error: str | None = None
        self.clob_rest_last_poll: datetime | None = None
        self.clob_rest_last_success: datetime | None = None
        self.clob_rest_last_error: str | None = None
        self.rtds_connected: bool = False
        self.rtds_last_message: datetime | None = None
        self.rtds_last_connect: datetime | None = None
        self.rtds_last_error: str | None = None
        self.subscriptions = SubscriptionManager(max_items=self.settings.max_subscriptions)
        self.last_seen: dict[str, datetime] = {}
        self.last_published: dict[str, datetime] = {}
        self.tick_sizes: dict[str, Decimal] = {}
        self.rtds_symbols: set[str] = set()
        self.rtds_symbols_version: int = 0
        self.market_tokens: dict[str, list[str]] = {}
        self.metrics = metrics
        self._asset_refcounts: dict[str, int] = {}
        self._symbol_refcounts: dict[str, int] = {}
        self._pinned_symbols: set[str] = set()
        self._acquired_history: set[str] = set()
        self._history_last_ts: dict[str, datetime] = {}
        self.active_connections: int = 0
        self._last_ws_ping: datetime | None = None
        self._stale_log_last_at: datetime | None = None
        self._stale_log_last_count: int = 0
        self._health_snapshot: dict | None = None
        self._health_snapshot_ts: datetime | None = None

    async def startup(self) -> None:
        try:
            self.redis = Redis.from_url(
                self.settings.redis_url,
                decode_responses=True,
                max_connections=30,
                socket_timeout=5.0,
                socket_connect_timeout=3.0,
                retry_on_timeout=True,
                health_check_interval=30,
            )
            await self.redis.ping()
            self.redis_error = None
        except Exception as exc:
            self.redis = None
            self.redis_error = str(exc)
            logger.warning(
                "redis unavailable; continuing in degraded mode",
                extra={"event": "streamer.redis.unavailable", "error": str(exc)},
            )
        await self._load_cache_snapshot()
        await self.refresh_fx()

    _MAX_TRACKING_ENTRIES = 5000
    _STALE_ENTRY_TTL = timedelta(hours=1)

    def evict_stale_entries(self) -> int:
        """Remove entries older than 1 hour from tracking dicts. Returns eviction count."""
        now = datetime.now(UTC)
        cutoff = now - self._STALE_ENTRY_TTL
        evicted = 0
        for d in (self.last_seen, self.last_published, self._history_last_ts):
            stale_keys = [k for k, v in d.items() if v < cutoff]
            for k in stale_keys:
                d.pop(k, None)
                evicted += 1
        # Cap non-timestamped dicts by size
        for sized_d in (self.tick_sizes, self.market_tokens):
            if len(sized_d) > self._MAX_TRACKING_ENTRIES:
                excess = len(sized_d) - self._MAX_TRACKING_ENTRIES
                for k in list(sized_d)[:excess]:
                    sized_d.pop(k, None)
                    evicted += 1
        return evicted

    async def shutdown(self) -> None:
        if self.redis:
            await self.redis.aclose()

    async def _load_cache_snapshot(self) -> None:
        if not self.settings.cache_snapshot_path or not self.redis:
            return
        path = self.settings.cache_snapshot_path
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            logger.warning(
                "cache snapshot file missing",
                extra={"event": "cache.snapshot.missing", "path": path},
            )
            return
        except Exception as exc:
            logger.warning(
                "cache snapshot load failed",
                extra={"event": "cache.snapshot.failed", "path": path, "error": str(exc)},
            )
            return
        entries = payload.get("entries")
        if not isinstance(entries, list):
            logger.warning(
                "cache snapshot invalid",
                extra={"event": "cache.snapshot.invalid", "path": path},
            )
            return
        restored = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            market_id = str(entry.get("market_id") or "")
            outcome = str(entry.get("outcome") or "")
            data = entry.get("data")
            if not market_id or not outcome or not isinstance(data, dict):
                continue
            try:
                await self.cache_tick(market_id, outcome, data)
                restored += 1
            except Exception as exc:
                logger.debug(
                    "cache snapshot entry failed",
                    extra={"event": "cache.snapshot.entry_failed", "market_id": market_id, "error": str(exc)},
                )
        logger.info(
            "cache snapshot restored",
            extra={"event": "cache.snapshot.restored", "path": path, "count": restored},
        )

    def cached_health_snapshot(self) -> dict | None:
        ttl_seconds = max(int(self.settings.health_deep_cache_ttl_seconds or 0), 0)
        if ttl_seconds <= 0:
            return None
        if not self._health_snapshot or not self._health_snapshot_ts:
            return None
        age = (datetime.now(UTC) - self._health_snapshot_ts).total_seconds()
        if age > ttl_seconds:
            return None
        return self._health_snapshot

    def store_health_snapshot(self, payload: dict) -> None:
        self._health_snapshot = payload
        self._health_snapshot_ts = datetime.now(UTC)

    async def _fetch_fx_from_url(self, url: AnyHttpUrl, label: str) -> FxQuote | None:
        client = await get_http_client(self.settings.fx_timeout_seconds)
        res = await client.get(str(url))
        res.raise_for_status()
        data = res.json()
        price = (
            data.get("price")
            or data.get("zen_usd")
            or data.get("zenUSD")
            or data.get("horizen", {}).get("usd")
            or data.get("USD")
            or data.get("usd")
        )
        if price is None:
            return None
        return self.register_fx(Decimal(str(price)), source=label, allow_jump=True)

    async def refresh_fx(self, *, label: str = "binance_rest") -> FxQuote:
        async with self._fx_lock:
            try:
                quote: FxQuote | None = None
                primary_url = self.settings.fx_primary_rest_url
                if self._is_self_fx_url(primary_url):
                    logger.warning(
                        "FX feed URL points to streamer itself; skipping",
                        extra={
                            "event": "fx.refresh.self_url",
                            "source": label or "binance_rest",
                            "url": self._redact_url(primary_url),
                        },
                    )
                else:
                    quote = await self._fetch_fx_from_url(primary_url, label or "binance_rest")
                if not quote and self.settings.fx_secondary_rest_url:
                    secondary_url = self.settings.fx_secondary_rest_url
                    if self._is_self_fx_url(secondary_url):
                        logger.warning(
                            "FX feed URL points to streamer itself; skipping",
                            extra={
                                "event": "fx.refresh.self_url",
                                "source": "cryptocompare_rest",
                                "url": self._redact_url(secondary_url),
                            },
                        )
                    else:
                        quote = await self._fetch_fx_from_url(secondary_url, "cryptocompare_rest")
                if quote:
                    return quote
                # If the REST payload was ignored due to priority/filters, keep the existing quote without
                # spamming rejection logs.
                if self.fx_last_error is None and self.fx_quote:
                    logger.info(
                        "REST FX ignored; keeping current quote",
                        extra={
                            "event": "fx.refresh.ignored",
                            "source": label or "binance_rest",
                            "last_source": self.fx_last_source or "unknown",
                            "stale": self.fx_quote.stale,
                        },
                    )
                    return self.fx_quote
                logger.info(
                    "REST FX rejected by sanity checks",
                    extra={
                        "event": "fx.refresh.rejected",
                        "source": label or "binance_rest",
                        "last_error": self.fx_last_error,
                    },
                )
                # If we already have a usable quote, keep it instead of zeroing out to fallback.
                if self.fx_quote:
                    logger.info(
                        "Reusing existing FX quote after refresh rejection",
                        extra={
                            "event": "fx.refresh.reuse_existing",
                            "source": self.fx_last_source or "unknown",
                            "stale": self.fx_quote.stale,
                            "last_error": self.fx_last_error,
                        },
                    )
                    return self.fx_quote
                raise ValueError("FX quote rejected by sanity checks")
            except Exception as exc:  # pragma: no cover - network fallback
                logger.warning(
                    "FX refresh failed, falling back",
                    extra={"event": "fx.refresh.failed", "error": str(exc), "source": label},
                )
                fallback_price = Decimal(str(self.settings.fx_fallback_price))
                fallback = FxQuote(
                    zen_usd=self._apply_fx_worsen(fallback_price),
                    raw_zen_usd=fallback_price,
                    fetched_at=datetime.now(UTC),
                    stale=True,
                    source="fallback",
                )
                self._update_fx(fallback)
                return fallback

    async def get_fx(self) -> FxQuote:
        if not self.fx_quote:
            return await self.refresh_fx()
        # Mark stale if older than threshold.
        if (
            self.fx_last_update
            and (datetime.now(UTC) - self.fx_last_update).total_seconds() > self.settings.fx_max_age_seconds
        ):
            self.fx_quote = FxQuote(
                zen_usd=self.fx_quote.zen_usd,
                raw_zen_usd=self.fx_quote.raw_zen_usd or self.fx_quote.zen_usd,
                fetched_at=self.fx_last_update,
                stale=True,
                source=self.fx_last_source or "unknown",
            )
        return self.fx_quote

    def snapshot_last_seen(self) -> dict[str, str]:
        """Return ISO timestamps of last seen market updates for diagnostics."""

        return {k: v.isoformat() for k, v in self.last_seen.items()}

    def register_ws_ping(self) -> None:
        self._last_ws_ping = datetime.now(UTC)

    def ws_ping_age_seconds(self) -> float | None:
        if not self._last_ws_ping:
            return None
        return (datetime.now(UTC) - self._last_ws_ping).total_seconds()

    async def cache_tick(self, market_id: str, outcome: str, payload: dict) -> None:
        if not self.redis:
            return
        now = datetime.now(UTC)
        key = f"{self.settings.cache_prefix}:{market_id}:{outcome}"
        channel = f"{self.settings.pubsub_prefix}:{market_id}"
        # Preserve structured fields by JSON-encoding lists/dicts; fall back to string for scalars.
        mapping = {
            k: json.dumps(v) if isinstance(v, (list, dict)) else ("" if v is None else str(v))
            for k, v in payload.items()
        }
        if self.settings.signing_secret:
            mapping["sig"] = self._sign_payload(mapping)
        try:
            pipe = self.redis.pipeline(transaction=False)
            pipe.hset(key, mapping=mapping)  # type: ignore[misc]
            if self.settings.cache_ttl_seconds > 0:
                pipe.expire(key, self.settings.cache_ttl_seconds)  # type: ignore[misc]
            await pipe.execute()
            await self.redis.publish(channel, json.dumps(mapping))  # type: ignore[misc]
        except Exception as exc:
            logger.warning(
                "cache tick failed",
                extra={"event": "stream.cache_tick.failed", "market_id": market_id, "error": str(exc)},
            )
            return
        self.last_seen[market_id] = now
        self.last_published[market_id] = now
        if self.metrics:
            # Reset staleness gauge to fresh on publish.
            self.metrics.market_staleness.labels(market_id=market_id).set(0)
        await self._store_history(market_id, outcome, payload, now)

    def _should_store_history(self, market_id: str) -> bool:
        if market_id in self.subscriptions.assets:
            return True
        tokens = self.market_tokens.get(market_id) or []
        return any(token in self.subscriptions.assets for token in tokens)

    async def _store_history(self, market_id: str, outcome: str, payload: dict, now: datetime) -> None:
        if not self.redis:
            return
        if not outcome.isdigit():
            return
        if payload.get("type") != "price":
            return
        if self.settings.history_limit <= 0:
            return
        if not self._should_store_history(market_id):
            return
        history_key = f"{self.settings.history_prefix}:{market_id}:{outcome}"
        debounce_seconds = float(self.settings.history_debounce_seconds or 0)
        if debounce_seconds > 0:
            last_ts = self._history_last_ts.get(history_key)
            if last_ts and (now - last_ts).total_seconds() < debounce_seconds:
                return
        try:
            serialized = json.dumps(payload, default=str)
            pipe = self.redis.pipeline(transaction=False)
            pipe.lpush(history_key, serialized)  # type: ignore[misc]
            pipe.ltrim(history_key, 0, max(self.settings.history_limit - 1, 0))  # type: ignore[misc]
            if self.settings.history_ttl_seconds > 0:
                pipe.expire(history_key, self.settings.history_ttl_seconds)
            await pipe.execute()
            self._history_last_ts[history_key] = now
        except Exception as exc:
            logger.debug(
                "history write failed",
                extra={
                    "event": "history.write.failed",
                    "market_id": market_id,
                    "outcome": outcome,
                    "error": str(exc),
                },
            )
            return

    @staticmethod
    def _redact_url(url: AnyHttpUrl) -> str:
        return redact_url(str(url))

    def _is_self_fx_url(self, url: AnyHttpUrl) -> bool:
        parsed = urlparse(str(url))
        if not parsed.hostname:
            return False
        parsed_host = parsed.hostname.lower()

        def _effective_port(port: int | None, scheme: str | None) -> int | None:
            if port is not None:
                return port
            if scheme == "https":
                return 443
            if scheme == "http":
                return 80
            return None

        parsed_port = _effective_port(parsed.port, parsed.scheme)
        candidates: list[tuple[str, int | None, str | None]] = []
        api_host = (self.settings.api_host or "").lower()
        if api_host:
            candidates.append((api_host, self.settings.api_port, "http"))
            if api_host == "0.0.0.0":  # noqa: S104 - intentional comparison for local bindings  # nosec B104
                candidates.extend(
                    [
                        ("127.0.0.1", self.settings.api_port, "http"),
                        ("localhost", self.settings.api_port, "http"),
                    ]
                )
        for base_url in (self.settings.internal_base_url, self.settings.public_base_url):
            if not base_url:
                continue
            base_parsed = urlparse(str(base_url))
            if base_parsed.hostname:
                candidates.append((base_parsed.hostname.lower(), base_parsed.port, base_parsed.scheme))

        for host, port, scheme in candidates:
            if parsed_host != host:
                continue
            cand_port = _effective_port(port, scheme)
            if parsed_port == cand_port:
                return True
        return False

    async def subscribe(self, market_id: str):
        if not self.redis:
            raise RuntimeError("Redis not initialised")
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(f"{self.settings.pubsub_prefix}:{market_id}")
        return pubsub

    def register_clob_tokens(self, market_id: str, token_ids: list[str]) -> None:
        if not market_id or not token_ids:
            return
        deduped = list(dict.fromkeys(token_ids))
        self.market_tokens[market_id] = deduped
        # If we previously subscribed using the market_id placeholder, swap to concrete token ids.
        if market_id in self.subscriptions.assets:
            self.subscriptions.replace_asset(market_id, deduped)
        if market_id in self._asset_refcounts:
            count = self._asset_refcounts.pop(market_id)
            for tok in deduped:
                self._asset_refcounts[tok] = self._asset_refcounts.get(tok, 0) + count
                self.subscriptions.add_assets([tok])

    @staticmethod
    def _normalize_rtds_symbol(symbol: str) -> str | None:
        trimmed = str(symbol).strip()
        if not trimmed:
            return None
        if len(trimmed) > 64:
            return None
        if not re.fullmatch(r"[A-Za-z0-9:_-]+", trimmed):
            return None
        return trimmed

    def sanitize_rtds_symbols(self, symbols: Iterable[str], *, max_items: int) -> list[str]:
        parsed: list[str] = []
        seen: set[str] = set()
        capped = max(int(max_items), 0)
        for symbol in symbols:
            normalized = self._normalize_rtds_symbol(str(symbol))
            if normalized is None or normalized in seen:
                continue
            seen.add(normalized)
            parsed.append(normalized)
            if capped and len(parsed) >= capped:
                break
        return parsed

    def add_rtds_symbols(self, symbols: Iterable[str]) -> list[str]:
        added: list[str] = []
        for sym in self.sanitize_rtds_symbols(symbols, max_items=self.settings.max_subscriptions):
            if sym in self._pinned_symbols:
                continue
            if sym not in self.rtds_symbols and len(self.rtds_symbols) >= self.settings.max_subscriptions:
                logger.warning(
                    "RTDS symbol cap reached; ignoring symbol",
                    extra={
                        "event": "stream.symbols.cap",
                        "symbol": sym,
                        "count": len(self.rtds_symbols),
                        "max": self.settings.max_subscriptions,
                    },
                )
                continue
            self._pinned_symbols.add(sym)
            if sym not in self.rtds_symbols:
                self.rtds_symbols.add(sym)
                added.append(sym)
        if added:
            self.rtds_symbols_version += 1
        return added

    def remove_rtds_symbols(self, symbols: Iterable[str]) -> list[str]:
        removed: list[str] = []
        for sym in self.sanitize_rtds_symbols(symbols, max_items=self.settings.max_subscriptions):
            self._pinned_symbols.discard(sym)
            if self._symbol_refcounts.get(sym, 0) <= 0 and sym in self.rtds_symbols:
                self.rtds_symbols.remove(sym)
                removed.append(sym)
        if removed:
            self.rtds_symbols_version += 1
        return removed

    def acquire_rtds_symbols(self, symbols: Iterable[str]) -> list[str]:
        added: list[str] = []
        for sym in self.sanitize_rtds_symbols(symbols, max_items=self.settings.max_subscriptions):
            existing_count = self._symbol_refcounts.get(sym, 0)
            if (
                existing_count == 0
                and sym not in self.rtds_symbols
                and len(self.rtds_symbols) >= self.settings.max_subscriptions
            ):
                logger.warning(
                    "RTDS symbol cap reached; ignoring symbol",
                    extra={
                        "event": "stream.symbols.cap",
                        "symbol": sym,
                        "count": len(self.rtds_symbols),
                        "max": self.settings.max_subscriptions,
                    },
                )
                continue
            self._symbol_refcounts[sym] = existing_count + 1
            if existing_count == 0 and sym not in self.rtds_symbols:
                self.rtds_symbols.add(sym)
                added.append(sym)
        if added:
            self.rtds_symbols_version += 1
        return added

    def release_rtds_symbols(self, symbols: Iterable[str]) -> list[str]:
        removed: list[str] = []
        for sym in self.sanitize_rtds_symbols(symbols, max_items=self.settings.max_subscriptions):
            count = self._symbol_refcounts.get(sym, 0)
            if count <= 0:
                continue
            if count == 1:
                self._symbol_refcounts.pop(sym, None)
                if sym not in self._pinned_symbols and sym in self.rtds_symbols:
                    self.rtds_symbols.remove(sym)
                    removed.append(sym)
            else:
                self._symbol_refcounts[sym] = count - 1
        if removed:
            self.rtds_symbols_version += 1
        return removed

    def get_clob_tokens(self, market_id: str) -> list[str]:
        return self.market_tokens.get(market_id, [])

    async def get_history(self, market_id: str, outcome: str, limit: int) -> list[dict]:
        if not self.redis:
            return []
        history_key = f"{self.settings.history_prefix}:{market_id}:{outcome}"
        raw = await self.redis.lrange(history_key, 0, max(0, limit - 1))  # type: ignore[misc]
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

    async def get_latest(self, market_id: str, outcome: str) -> dict[str, str]:
        """Return the latest cached payload for the given market/outcome."""

        if not self.redis:
            return {}
        key = f"{self.settings.cache_prefix}:{market_id}:{outcome}"
        data = await self.redis.hgetall(key)  # type: ignore[misc]
        return data or {}

    async def get_bootstrap_payloads(self, market_id: str, *, max_outcomes: int = 6) -> list[str]:
        """Return cached price payloads for a market to bootstrap new streams."""

        if not self.redis or not market_id or max_outcomes <= 0:
            return []

        outcomes: list[str] = []
        tokens = self.market_tokens.get(market_id)
        if tokens:
            outcomes = [str(idx) for idx in range(min(len(tokens), max_outcomes))]
        else:
            outcomes = await self._discover_cached_outcomes(market_id, max_outcomes)
            if not outcomes:
                outcomes = [str(idx) for idx in range(min(2, max_outcomes))]

        payloads: list[str] = []
        for outcome in outcomes:
            cached = await self.get_latest(market_id, outcome)
            if cached:
                payloads.append(json.dumps(cached))
        return payloads

    async def _discover_cached_outcomes(self, market_id: str, max_outcomes: int) -> list[str]:
        if not self.redis or max_outcomes <= 0:
            return []
        scan_iter = getattr(self.redis, "scan_iter", None)
        if scan_iter is None:
            return []
        pattern = f"{self.settings.cache_prefix}:{market_id}:*"
        outcomes: list[str] = []
        try:
            async for key in scan_iter(match=pattern, count=100):
                key_str = str(key)
                outcome = key_str.rsplit(":", 1)[-1]
                if not outcome.isdigit():
                    continue
                outcomes.append(outcome)
                if len(outcomes) >= max_outcomes:
                    break
        except Exception as exc:
            logger.debug(
                "bootstrap outcome scan failed",
                extra={"event": "stream.bootstrap.scan_failed", "market_id": market_id, "error": str(exc)},
            )
            return []
        unique = sorted(set(outcomes), key=int)
        return unique[:max_outcomes]

    def _staleness_targets(self) -> set[str]:
        assets = self.subscriptions.assets
        if not assets:
            return set()
        tracked: set[str] = {market_id for market_id in self.last_seen if market_id in assets}
        for market_id, tokens in self.market_tokens.items():
            if market_id in tracked:
                continue
            if market_id in assets or any(token in assets for token in tokens):
                tracked.add(market_id)
        return tracked

    def stale_markets(self, stale_after_seconds: int = 60) -> list[str]:
        now = datetime.now(UTC)
        evict_after_seconds = max(
            stale_after_seconds, getattr(self.settings, "market_stale_evict_seconds", stale_after_seconds)
        )
        evicted: list[str] = []
        for market_id, ts in list(self.last_seen.items()):
            age_seconds = (now - ts).total_seconds()
            if age_seconds > evict_after_seconds:
                evicted.append(market_id)
                self.last_seen.pop(market_id, None)
                if self.metrics:
                    with suppress(Exception):
                        self.metrics.market_staleness.remove(market_id)
        if evicted:
            logger.info(
                "evicted long-stale markets from tracking",
                extra={"event": "stream.stale.evict", "count": len(evicted), "evicted_sample": evicted[:10]},
            )
        tracked = self._staleness_targets()
        if not tracked:
            if self.metrics:
                self.metrics.stale_market_total.set(0)
            return []
        filtered_last_seen = {market_id: ts for market_id, ts in self.last_seen.items() if market_id in tracked}
        if self.metrics:
            return self.metrics.record_staleness(filtered_last_seen, stale_after=stale_after_seconds)
        cutoff = now - timedelta(seconds=stale_after_seconds)
        return [mid for mid, ts in filtered_last_seen.items() if ts < cutoff]

    def should_log_stale_markets(self, count: int, *, min_interval_seconds: int) -> bool:
        if count <= 0:
            self._stale_log_last_count = 0
            self._stale_log_last_at = None
            return False
        now = datetime.now(UTC)
        last_at = self._stale_log_last_at
        last_count = self._stale_log_last_count
        if last_at is None or count != last_count:
            self._stale_log_last_at = now
            self._stale_log_last_count = count
            return True
        if min_interval_seconds <= 0:
            self._stale_log_last_at = now
            self._stale_log_last_count = count
            return True
        if (now - last_at).total_seconds() >= min_interval_seconds:
            self._stale_log_last_at = now
            self._stale_log_last_count = count
            return True
        return False

    def acquire_assets(self, assets: Iterable[str]) -> list[str]:
        added: list[str] = []
        for asset in assets:
            key = str(asset)
            if (
                key not in self.subscriptions.assets
                and len(self.subscriptions.assets) >= self.settings.max_subscriptions
            ):
                logger.warning(
                    "subscription cap reached; ignoring asset",
                    extra={
                        "event": "stream.assets.cap",
                        "asset": key,
                        "count": len(self.subscriptions.assets),
                        "max": self.settings.max_subscriptions,
                    },
                )
                continue
            prev = self._asset_refcounts.get(key, 0)
            self._asset_refcounts[key] = prev + 1
            if prev == 0:
                added.append(key)
                self.subscriptions.add_assets([key])
                self._acquired_history.add(key)
        return added

    def force_remove_assets(self, assets: Iterable[str]) -> None:
        """Remove assets from subscriptions regardless of refcount (ops-only)."""

        for asset in assets:
            key = str(asset)
            self._asset_refcounts.pop(key, None)
            if key in self.subscriptions.assets:
                self.subscriptions.remove_asset(key)

    def release_assets(self, assets: Iterable[str]) -> None:
        for asset in assets:
            key = str(asset)
            if key in self._asset_refcounts:
                self._asset_refcounts[key] -= 1
                if self._asset_refcounts[key] <= 0:
                    self._asset_refcounts.pop(key, None)
                    self.subscriptions.remove_asset(key)
                continue
            tokens = self.market_tokens.get(key) or []
            if not tokens:
                continue
            for token in tokens:
                if token not in self._asset_refcounts:
                    continue
                self._asset_refcounts[token] -= 1
                if self._asset_refcounts[token] <= 0:
                    self._asset_refcounts.pop(token, None)
                    self.subscriptions.remove_asset(token)

    def _sign_payload(self, payload: dict) -> str:
        secret = self.settings.signing_secret
        if not secret:
            return ""
        message = "|".join(f"{k}:{payload[k]}" for k in sorted(payload.keys()))
        digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        return digest

    def _update_fx(self, quote: FxQuote, *, reason: str | None = None, quiet: bool = False) -> None:
        prev_source = self.fx_last_source or "unknown"
        self.fx_quote = quote
        self.fx_last_update = quote.fetched_at
        self.fx_last_source = quote.source
        if quote.source != "fallback":
            self._fx_prev_price = quote.raw_zen_usd or quote.zen_usd
            self._fx_prev_price_ts = quote.fetched_at
        self.fx_last_error = None
        if quote.source in self._WS_SOURCES:
            self.fx_ws_connected = True
            self.fx_ws_last_update = quote.fetched_at
        log_fn = logger.debug if quiet else logger.info
        log_fn(
            "FX source updated",
            extra={
                "event": "fx.source.update",
                "source": quote.source,
                "previous_source": prev_source,
                "stale": quote.stale,
                "raw_zen_usd": str(quote.raw_zen_usd or quote.zen_usd),
                "zen_usd": str(quote.zen_usd),
                "reason": reason or "update",
            },
        )

    def _apply_fx_worsen(self, price: Decimal) -> Decimal:
        """Apply worsen% to the raw FX price before exposing downstream."""
        worsened = price * (Decimal("1") - Decimal(str(self.settings.worsen_percent)))
        return worsened.quantize(Decimal("0.00000001"))

    def register_fx(
        self, price: Decimal, *, source: str, allow_jump: bool = False, reason: str | None = None
    ) -> FxQuote | None:
        if price <= 0:
            self.fx_last_error = "price_non_positive"
            logger.warning(
                "Rejecting FX non-positive price",
                extra={"event": "fx.reject.non_positive", "price": str(price), "source": source},
            )
            return None
        if self.fx_last_source == "fallback":
            allow_jump = True
        if self._fx_prev_price is None:
            allow_jump = True  # Seed quote should not be blocked by jump checks.
        now = datetime.now(UTC)
        is_current_stale = False
        if self.fx_last_update and (now - self.fx_last_update).total_seconds() > self.settings.fx_max_age_seconds:
            is_current_stale = True
            if self.fx_quote:
                self.fx_quote = FxQuote(
                    zen_usd=self.fx_quote.zen_usd,
                    raw_zen_usd=self.fx_quote.raw_zen_usd or self.fx_quote.zen_usd,
                    fetched_at=self.fx_last_update,
                    stale=True,
                    source=self.fx_last_source or "unknown",
                )
        if price < Decimal(str(self.settings.fx_min_price)) or price > Decimal(str(self.settings.fx_max_price)):
            self.fx_last_error = "price_out_of_bounds"
            self._fx_rejection_count += 1
            if self._fx_rejection_count >= self.settings.fx_max_consecutive_rejections:
                self.fx_ws_connected = False
            logger.warning(
                "Rejecting FX out-of-bounds",
                extra={
                    "event": "fx.reject.bounds",
                    "price": str(price),
                    "min": self.settings.fx_min_price,
                    "max": self.settings.fx_max_price,
                    "rejections": self._fx_rejection_count,
                    "source": source,
                },
            )
            return None
        if not allow_jump and self._fx_prev_price and self._fx_prev_price_ts:
            delta_seconds = (now - self._fx_prev_price_ts).total_seconds()
            if delta_seconds < self.settings.fx_jump_window_seconds:
                change_pct = abs(price - self._fx_prev_price) / self._fx_prev_price * Decimal("100")
                if change_pct > Decimal(str(self.settings.fx_max_jump_percent)):
                    self.fx_last_error = f"jump_{change_pct:.2f}pct"
                    self._fx_rejection_count += 1
                    if self._fx_rejection_count >= self.settings.fx_max_consecutive_rejections:
                        self.fx_ws_connected = False
                    logger.warning(
                        "Rejecting FX jump",
                        extra={
                            "event": "fx.jump.rejected",
                            "change_pct": float(change_pct),
                            "window_seconds": delta_seconds,
                            "rejections": self._fx_rejection_count,
                            "price": str(price),
                            "prev_price": str(self._fx_prev_price),
                            "source": source,
                            "allow_jump": allow_jump,
                        },
                    )
                    return None
        adjusted_price = self._apply_fx_worsen(price)
        if source not in self._SOURCE_PRIORITY:
            logger.debug(
                "Ignoring FX update from unknown source",
                extra={"event": "fx.update.ignored_source", "source": source, "reason": reason or "unknown"},
            )
            return None
        last_source = self.fx_last_source if isinstance(self.fx_last_source, str) else ""
        current_priority = self._SOURCE_PRIORITY.get(last_source, 99)
        new_priority = self._SOURCE_PRIORITY.get(source, 99)
        quiet_update = False
        if self.fx_quote and not is_current_stale and not self.fx_quote.stale:
            if last_source == source:
                quiet_update = True
            elif current_priority < new_priority:
                logger.debug(
                    "Ignoring FX update due to priority",
                    extra={
                        "event": "fx.update.ignored",
                        "current_source": self.fx_last_source,
                        "incoming_source": source,
                        "reason": reason or "priority",
                    },
                )
                return None
        quote = FxQuote(zen_usd=adjusted_price, raw_zen_usd=price, fetched_at=now, stale=False, source=source)
        self._update_fx(quote, reason=reason, quiet=quiet_update)
        self._fx_rejection_count = 0
        return quote


class _AsyncWebSocket:
    """Proxy websocket that supports async iteration with optional read timeout."""

    def __init__(self, ws, *, timeout: float | int | None, name: str, url: str):
        self._ws = ws
        self._timeout = timeout
        self._name = name
        self._url = url

    def __getattr__(self, item):
        return getattr(self._ws, item)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            if self._timeout is None:
                return await self._ws.recv()
            return await asyncio.wait_for(self._ws.recv(), timeout=self._timeout)
        except TimeoutError as exc:
            raise TimeoutError(f"{self._name} read timeout after {self._timeout}s ({self._url})") from exc


async def iter_ws(
    ws_url: str,
    *,
    name: str = "ws",
    fatal_status: set[int] | None = None,
    ping_interval: float | int | None = None,
    ping_timeout: float | int | None = None,
    read_timeout: float | int | None = None,
):
    """Yield websocket connections, reconnecting on drop. Optionally bail on fatal HTTP statuses."""

    fatal_status = fatal_status or set()
    while True:
        try:
            async with connect(
                ws_url,
                ping_interval=ping_interval if ping_interval is not None else 5,
                ping_timeout=ping_timeout if ping_timeout is not None else 20,
            ) as ws:
                yield _AsyncWebSocket(ws, timeout=read_timeout, name=name, url=ws_url)
        except InvalidStatus as exc:  # pragma: no cover - reconnection path
            status_code = getattr(getattr(exc, "response", None), "status_code", None) or getattr(
                exc, "status_code", None
            )
            logger.warning(
                "ws dropped; reconnecting",
                extra={"event": f"{name}.ws.reconnect", "error": f"http_{status_code}", "url": ws_url},
            )
            if status_code in fatal_status:
                logger.warning(
                    "ws rejected with fatal status; giving up",
                    extra={"event": f"{name}.ws.fatal", "status": status_code, "url": ws_url},
                )
                raise FatalWebsocketError(status_code or -1, ws_url) from exc
            await asyncio.sleep(get_settings().ws_reconnect_seconds)
        except Exception as exc:  # pragma: no cover - reconnection path
            logger.warning(
                "ws dropped; reconnecting",
                extra={"event": f"{name}.ws.reconnect", "error": str(exc), "url": ws_url},
            )
            await asyncio.sleep(get_settings().ws_reconnect_seconds)
