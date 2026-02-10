# mypy: ignore-errors
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal

from prometheus_client import REGISTRY, Counter, Gauge

from .config import Settings
from .state import FatalWebsocketError, StreamState, iter_ws

logger = logging.getLogger("reveal_market.streamer.fx")


class PriceStreamer:
    """Maintains FX (ZEN/USD) via Binance WS with REST fallbacks."""

    _metric_fx_source_shared: Gauge | None = None
    _metric_fx_stale_shared: Gauge | None = None
    _metric_ws_connected_shared: Gauge | None = None
    _metric_ws_restarts_shared: Counter | None = None
    _metric_ws_ping_age_shared: Gauge | None = None
    _metric_rest_fallbacks_shared: Counter | None = None

    def __init__(self, state: StreamState, settings: Settings):
        self.state = state
        self.settings = settings
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()
        self.metric_fx_source: Gauge | None = None
        self.metric_fx_stale: Gauge | None = None
        self.metric_ws_connected: Gauge | None = None
        self.metric_ws_restarts: Counter | None = None
        self.metric_ws_ping_age: Gauge | None = None
        self.metric_rest_fallbacks: Counter | None = None
        self._init_metrics()

    def _init_metrics(self) -> None:
        if self.metric_fx_source is not None:
            return
        if PriceStreamer._metric_fx_source_shared is None:
            PriceStreamer._metric_fx_source_shared = Gauge(
                "streamer_fx_source", "Current FX source (labels)", ["source"], registry=REGISTRY
            )
            PriceStreamer._metric_fx_stale_shared = Gauge(
                "streamer_fx_stale", "FX stale flag (1=stale,0=fresh)", registry=REGISTRY
            )
            PriceStreamer._metric_ws_connected_shared = Gauge(
                "streamer_fx_ws_connected", "FX websocket connectivity (1/0)", registry=REGISTRY
            )
            PriceStreamer._metric_ws_restarts_shared = Counter(
                "streamer_fx_ws_restarts_total", "FX websocket restart attempts", registry=REGISTRY
            )
            PriceStreamer._metric_ws_ping_age_shared = Gauge(
                "streamer_fx_ws_ping_age_seconds", "Seconds since last FX WS ping/pong", registry=REGISTRY
            )
            PriceStreamer._metric_rest_fallbacks_shared = Counter(
                "streamer_fx_rest_fallbacks_total", "FX REST fallback fetches", registry=REGISTRY
            )
        self.metric_fx_source = PriceStreamer._metric_fx_source_shared
        self.metric_fx_stale = PriceStreamer._metric_fx_stale_shared
        self.metric_ws_connected = PriceStreamer._metric_ws_connected_shared
        self.metric_ws_restarts = PriceStreamer._metric_ws_restarts_shared
        self.metric_ws_ping_age = PriceStreamer._metric_ws_ping_age_shared
        self.metric_rest_fallbacks = PriceStreamer._metric_rest_fallbacks_shared

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._fx_refresh_loop(), name="fx-refresh"),
            asyncio.create_task(self._fx_ws_loop(), name="fx-ws-loop"),
        ]

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def _update_fx_metrics(self) -> None:
        if (
            not self.metric_fx_source
            or not self.metric_fx_stale
            or not self.metric_ws_connected
            or not self.metric_ws_ping_age
        ):
            return
        fx = self.state.fx_quote
        source = fx.source if fx else (self.state.fx_last_source or "unknown")
        stale_flag = 1 if (fx and fx.stale) or self.state.fx_last_update is None else 0
        self.metric_ws_connected.set(1 if self.state.fx_ws_connected else 0)
        self.metric_fx_stale.set(stale_flag)
        for label in ("binance_ws", "binance_rest", "cryptocompare_rest", "fallback", "unknown"):
            self.metric_fx_source.labels(source=label).set(1 if source == label else 0)
        ping_age = self.state.ws_ping_age_seconds()
        if ping_age is not None:
            self.metric_ws_ping_age.set(ping_age)

    async def _fx_refresh_loop(self) -> None:
        try:
            while not self._stop.is_set():
                await self._fx_refresh_once()
                await asyncio.sleep(self.settings.fx_rest_interval_seconds)
        except asyncio.CancelledError:
            return

    async def _fx_refresh_once(self) -> None:
        now = datetime.now(UTC)
        if self.state.fx_ws_last_update:
            ws_stale = (now - self.state.fx_ws_last_update).total_seconds() > self.settings.fx_ws_stale_ttl_seconds
        else:
            ws_stale = True
        if ws_stale:
            self.state.fx_ws_connected = False
        # Only hit REST when we have no quote or the current one is too old. WS staleness alone is not enough
        # if we still have a fresh quote within `fx_max_age_seconds`.
        age_seconds: float | None = None
        if self.state.fx_last_update:
            age_seconds = (now - self.state.fx_last_update).total_seconds()
        needs_rest = (age_seconds is None) or (age_seconds > self.settings.fx_max_age_seconds)
        if self.settings.fx_rest_enabled and needs_rest:
            reason = "ws_stale" if ws_stale else "max_age"
            logger.info(
                "FX WS stale, refreshing via REST",
                extra={
                    "event": "fx.rest.refresh",
                    "reason": reason,
                    "ws_connected": self.state.fx_ws_connected,
                    "last_update": self.state.fx_last_update.isoformat() if self.state.fx_last_update else None,
                },
            )
            await self.state.refresh_fx(label="binance_rest")
            if self.metric_rest_fallbacks:
                try:
                    self.metric_rest_fallbacks.inc()
                except Exception as exc:  # pragma: no cover
                    logger.debug("metric_rest_fallbacks_increment_failed", exc_info=exc)
        self._update_fx_metrics()

    async def _fx_ws_loop(self) -> None:
        urls = []
        if self.settings.fx_ws_urls:
            urls = list(self.settings.fx_ws_urls)
        elif self.settings.fx_primary_ws_url:
            urls = [self.settings.fx_primary_ws_url]
        if not urls:
            return
        attempt = 0
        while not self._stop.is_set():
            attempt += 1
            url = urls[(attempt - 1) % len(urls)]
            logger.info(
                "Connecting to FX websocket",
                extra={"event": "fx.ws.connect", "url": url, "attempt": attempt},
            )
            try:
                async for ws in iter_ws(
                    url,
                    name="fx-ws",
                    fatal_status={400, 401, 403, 404, 429},
                    ping_interval=self.settings.fx_ws_ping_interval_seconds,
                    read_timeout=self.settings.fx_ws_read_timeout_seconds,
                ):
                    if self._stop.is_set():
                        break
                    logger.info(
                        "FX websocket connected",
                        extra={
                            "event": "fx.ws.connected",
                            "url": url,
                            "attempt": attempt,
                        },
                    )
                    try:
                        self.metric_ws_restarts.inc()
                    except Exception as exc:  # pragma: no cover
                        logger.debug("metric_ws_restarts_increment_failed", exc_info=exc)
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        self.state.register_ws_ping()
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        await self._handle_fx_ws(data)
            except asyncio.CancelledError:
                raise
            except FatalWebsocketError as exc:
                self.state.fx_ws_connected = False
                self.state.fx_last_error = f"http_{exc.status_code}"
                logger.warning(
                    "FX ws disabled after fatal handshake status",
                    extra={"event": "fx.ws.disabled", "status": exc.status_code, "url": exc.url},
                )
                return
            except Exception as exc:  # pragma: no cover - reconnect path
                self.state.fx_ws_connected = False
                self.state.fx_last_error = str(exc)
                logger.warning(
                    "FX ws loop error",
                    extra={
                        "event": "fx.ws.error",
                        "error": str(exc),
                        "backoff_seconds": self.settings.ws_reconnect_seconds,
                    },
                )
            await asyncio.sleep(self.settings.ws_reconnect_seconds)

    async def _handle_fx_ws(self, data: dict) -> None:
        symbol = str(data.get("s") or "").upper()
        if symbol and symbol != "ZENUSDT":
            return
        bid = data.get("b")
        ask = data.get("a")
        last = data.get("c")
        price_val: Decimal | None = None
        if bid and ask:
            try:
                price_val = (Decimal(str(bid)) + Decimal(str(ask))) / Decimal(2)
            except (ArithmeticError, ValueError, TypeError):
                price_val = None
        if price_val is None and last:
            try:
                price_val = Decimal(str(last))
            except (ArithmeticError, ValueError, TypeError):
                price_val = None
        if price_val is None:
            return
        quote = self.state.register_fx(price_val, source="binance_ws", reason="binance_ws")
        if not quote:
            return
        self.state.fx_last_error = None
        self.state.fx_ws_connected = True
        logger.debug("FX quote updated from ws", extra={"event": "fx.ws.update", "price": str(price_val)})
        self._update_fx_metrics()
