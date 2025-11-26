from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from prometheus_client import Counter, Gauge
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BookParams

from .config import Settings
from .state import FatalWebsocketError, StreamState, iter_ws

logger = logging.getLogger("reveal_market.price_streamer.streamer")


class PriceStreamer:
    """Connects to Polymarket WS + REST, normalizes ticks, and publishes to Redis."""

    def __init__(self, state: StreamState, settings: Settings):
        self.state = state
        self.settings = settings
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()
        self._publish_cache: dict[str, dict] = {}
        self.clob_client: ClobClient | None = None
        if getattr(self.settings, "clob_host", None):
            try:
                self.clob_client = ClobClient(str(self.settings.clob_host))
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to initialise CLOB client", extra={"event": "clob.init.failed", "error": str(exc)}
                )
        # Prometheus instruments (registered lazily in tests to avoid duplicates)
        self.metric_fx_source = None
        self.metric_fx_stale = None
        self.metric_ws_connected = None
        self.metric_ws_restarts = None
        self.metric_ticks = None
        self._init_metrics()

    @staticmethod
    def _coerce_array(value: Any) -> list | None:
        """Parse lists or JSON-encoded lists from Polymarket payloads."""

        if isinstance(value, (list, tuple)):
            return list(value)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception:
                return None
            if isinstance(parsed, list):
                return parsed
        return None

    def _update_fx_metrics(self) -> None:
        """Refresh Prometheus gauges from current FX state."""

        if not self.metric_fx_source or not self.metric_fx_stale or not self.metric_ws_connected:
            return
        fx = self.state.fx_quote
        source = fx.source if fx else (self.state.fx_last_source or "unknown")
        stale_flag = 1 if (fx and fx.stale) or self.state.fx_last_update is None else 0
        self.metric_ws_connected.set(1 if self.state.fx_ws_connected else 0)
        self.metric_fx_stale.set(stale_flag)
        for label in ("binance_ws", "rtds_crypto", "coingecko_rest", "rest_fallback", "fallback", "unknown"):
            self.metric_fx_source.labels(source=label).set(1 if source == label else 0)

    def _init_metrics(self) -> None:
        # Only register once per process; Prometheus client raises on duplicates.
        if self.metric_fx_source is not None:
            return
        self.metric_fx_source = Gauge(
            "price_streamer_fx_source", "Current FX source (labels)", ["source"], registry=None
        )
        self.metric_fx_stale = Gauge("price_streamer_fx_stale", "FX stale flag (1=stale,0=fresh)", registry=None)
        self.metric_ws_connected = Gauge(
            "price_streamer_fx_ws_connected", "FX websocket connectivity (1/0)", registry=None
        )
        self.metric_ws_restarts = Counter(
            "price_streamer_fx_ws_restarts_total", "FX websocket restart attempts", registry=None
        )
        self.metric_ticks = Counter(
            "price_streamer_ticks_total", "Published ticks", ["source", "market", "outcome", "stale"], registry=None
        )

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._ws_loop(), name="ws-loop"),
            asyncio.create_task(self._rest_poll_loop(), name="rest-poll"),
            asyncio.create_task(self._fx_refresh_loop(), name="fx-refresh"),
            asyncio.create_task(self._flush_loop(), name="flush-loop"),
            asyncio.create_task(self._rtds_loop(), name="rtds-loop"),
            asyncio.create_task(self._fx_ws_loop(), name="fx-ws-loop"),
        ]

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _ws_loop(self) -> None:
        while not self._stop.is_set():
            # Avoid hammering the WS with empty subscriptions.
            if not self.state.subscriptions.assets:
                logger.debug(
                    "CLOB ws idle; no subscriptions yet",
                    extra={"event": "clob.ws.idle", "subscriptions": 0},
                )
                await asyncio.sleep(self.settings.ws_reconnect_seconds)
                continue
            logger.info(
                "Connecting to CLOB websocket",
                extra={
                    "event": "clob.ws.connect",
                    "subscriptions": len(self.state.subscriptions.assets),
                },
            )
            async for ws in iter_ws(self.settings.clob_ws_url, name="clob-ws"):
                if self._stop.is_set():
                    break
                try:
                    logger.info(
                        "CLOB websocket connected",
                        extra={
                            "event": "clob.ws.connected",
                            "url": self.settings.clob_ws_url,
                            "subscriptions": len(self.state.subscriptions.assets),
                        },
                    )
                    subscribe_payload = self.state.subscriptions.build_clob_subscribe()
                    logger.debug(
                        "Sending CLOB subscribe",
                        extra={
                            "event": "clob.ws.subscribe",
                            "payload": subscribe_payload,
                            "subscriptions": sorted(self.state.subscriptions.assets),
                        },
                    )
                    await ws.send(subscribe_payload)
                    msg_count = 0
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        try:
                            payload = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        msg_count += 1
                        if msg_count % 50 == 1:
                            logger.debug(
                                "Received CLOB payload",
                                extra={
                                    "event": "clob.ws.message",
                                    "count": msg_count,
                                    "subscriptions": len(self.state.subscriptions.assets),
                                },
                            )
                        # Polymarket may send batch payloads as a list; handle both shapes.
                        if isinstance(payload, list):
                            for item in payload:
                                if isinstance(item, dict):
                                    await self._handle_tick(item, source="ws")
                        elif isinstance(payload, dict):
                            await self._handle_tick(payload, source="ws")
                except Exception as exc:  # pragma: no cover - reconnect path
                    logger.warning("CLOB ws loop error", extra={"event": "clob.ws.error", "error": str(exc)})
                    await asyncio.sleep(self.settings.ws_reconnect_seconds)

    async def _rest_poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._poll_rest()
            except Exception as exc:  # pragma: no cover - network path
                logger.warning("REST poll failed", extra={"event": "polymarket.rest.failed", "error": str(exc)})
            await asyncio.sleep(self.settings.rest_poll_seconds)

    async def _fx_refresh_loop(self) -> None:
        while not self._stop.is_set():
            await self._fx_refresh_once()
            await asyncio.sleep(self.settings.fx_rest_interval_seconds)

    async def _fx_refresh_once(self) -> None:
        """Single iteration of FX refresh to simplify testing."""

        now = datetime.now(UTC)
        if self.state.fx_ws_last_update:
            ws_stale = (now - self.state.fx_ws_last_update).total_seconds() > self.settings.fx_ws_stale_ttl_seconds
        else:
            ws_stale = True
        if ws_stale:
            self.state.fx_ws_connected = False
        if self.settings.fx_rest_enabled and (
            ws_stale
            or not self.state.fx_last_update
            or (now - self.state.fx_last_update).total_seconds() > self.settings.fx_max_age_seconds
        ):
            await self.state.refresh_fx(label="coingecko_rest")
        self._update_fx_metrics()

    async def _flush_loop(self) -> None:
        interval = max(0.05, self.settings.publish_throttle_ms / 1000)
        while not self._stop.is_set():
            await asyncio.sleep(interval)
            if not self._publish_cache:
                continue
            to_publish = self._publish_cache
            self._publish_cache = {}
            for (market_id, outcome), payload in to_publish.items():
                await self.state.cache_tick(market_id, outcome, payload)

    async def _poll_rest(self) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(str(self.settings.clob_rest_markets_url))
            res.raise_for_status()
            payload = res.json()
            markets = payload if isinstance(payload, list) else payload.get("data") or []
            for market in markets:
                await self._normalize_and_publish(market, source="rest")
            logger.debug(
                "REST poll ingested markets",
                extra={"event": "clob.rest.poll", "count": len(markets)},
            )
            # Proactively subscribe with discovered token ids if we only had market placeholders.
            for market in markets:
                market_id = str(market.get("id") or market.get("marketId") or "")
                tokens = self.state.get_clob_tokens(market_id)
                if market_id and tokens and market_id in self.state.subscriptions.assets:
                    self.state.subscriptions.replace_asset(market_id, tokens)

    async def _fetch_midpoints(self, token_ids: list[str]) -> list[Decimal] | None:
        if not self.clob_client:
            return None
        params = [BookParams(token_id=str(token_id)) for token_id in token_ids if str(token_id)]
        if not params:
            return None
        try:
            midpoints = await asyncio.to_thread(self.clob_client.get_midpoints, params)
        except Exception as exc:  # pragma: no cover - network path
            logger.debug("CLOB midpoint fetch failed", extra={"event": "clob.midpoints.failed", "error": str(exc)})
            return None
        parsed: list[Decimal] = []
        if isinstance(midpoints, list):
            for entry in midpoints:
                if isinstance(entry, dict):
                    value = entry.get("midpoint") or entry.get("price") or entry.get("mid")
                else:
                    value = entry
                try:
                    parsed.append(Decimal(str(value)))
                except Exception as exc:
                    logger.debug(
                        "Skipping midpoint parse failure",
                        extra={"event": "clob.midpoints.parse_failed", "error": str(exc)},
                    )
                    continue
        return parsed or None

    async def _handle_tick(self, data: dict, source: str) -> None:
        event_type = (data.get("event_type") or data.get("type") or "").lower()
        if event_type in {"book", "price_change", "last_trade_price", "tick_size_change"}:
            await self._handle_market_event(data, source)
            return
        market = data.get("market") or data.get("marketId") or data.get("id")
        if not market:
            return
        await self._normalize_and_publish(data, source=source)

    async def _handle_market_event(self, data: dict, source: str) -> None:
        event_type = (data.get("event_type") or data.get("type") or "").lower()
        market = data.get("market") or data.get("marketId") or data.get("id")
        if not market:
            return
        if event_type == "last_trade_price":
            await self._publish_trade_event(market, data, source)
            return
        if event_type == "tick_size_change":
            payload = {
                "market_id": market,
                "type": "tick_size",
                "tick_size": data.get("new_tick_size") or data.get("tick_size"),
                "timestamp": datetime.now(UTC).isoformat(),
            }
            await self.state.cache_tick(market, "meta", payload)
            return
        if event_type == "book":
            bids = data.get("bids") or data.get("buys") or data.get("bid")
            asks = data.get("asks") or data.get("sells") or data.get("ask")
            best_bid = None
            best_ask = None
            if isinstance(bids, list) and bids:
                try:
                    best_bid = max(Decimal(str(b.get("price") if isinstance(b, dict) else b)) for b in bids)
                except Exception:
                    best_bid = None
            if isinstance(asks, list) and asks:
                try:
                    best_ask = min(Decimal(str(a.get("price") if isinstance(a, dict) else a)) for a in asks)
                except Exception:
                    best_ask = None
            payload = {
                "market_id": market,
                "type": "book",
                "best_bid": str(best_bid) if best_bid is not None else None,
                "best_ask": str(best_ask) if best_ask is not None else None,
                "display_best_bid": str(best_bid * (Decimal("1") - Decimal(str(self.settings.worsen_percent))))
                if best_bid is not None
                else None,
                "display_best_ask": str(best_ask * (Decimal("1") - Decimal(str(self.settings.worsen_percent))))
                if best_ask is not None
                else None,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            await self.state.cache_tick(market, "meta", payload)
            return
        # price_change falls back to normalize flow
        await self._normalize_and_publish(data, source=source)

    async def _publish_trade_event(self, market_id: str, data: dict, source: str) -> None:
        price = data.get("price") or data.get("last") or data.get("best_price") or data.get("p")
        size = data.get("size") or data.get("quantity") or data.get("s")
        side = data.get("side")
        ts = data.get("timestamp") or data.get("ts")
        if not ts:
            ts = datetime.now(UTC).isoformat()
        payload = {
            "market_id": market_id,
            "type": "trade",
            "price": str(price) if price is not None else None,
            "size": str(size) if size is not None else None,
            "side": side,
            "timestamp": ts,
            "source": source,
        }
        await self.state.cache_tick(market_id, "trades", payload)

    async def _normalize_and_publish(self, raw: dict, source: str) -> None:
        market_id = (
            raw.get("id")
            or raw.get("marketId")
            or raw.get("market")
            or raw.get("conditionId")
            or raw.get("condition_id")
        )
        raw_prices = raw.get("outcomePrices") or raw.get("prices") or raw.get("outcomes")
        prices = self._coerce_array(raw_prices) or []
        token_ids_raw = raw.get("clobTokenIds") or raw.get("clob_token_ids") or raw.get("tokenIds")
        token_ids = self._coerce_array(token_ids_raw) or []
        coerced_token_ids = [str(token) for token in token_ids if str(token).strip()]
        if coerced_token_ids:
            self.state.register_clob_tokens(str(market_id), coerced_token_ids)
            midpoints = await self._fetch_midpoints(coerced_token_ids)
            if midpoints and len(midpoints) == len(coerced_token_ids):
                prices = midpoints
        if not market_id or not prices or not isinstance(prices, (list, tuple)):
            return
        # Record last seen timestamp for diagnostics.
        self.state.last_seen[str(market_id)] = datetime.now(UTC)
        # Capture best bid/ask in both snake and camel variants.
        best_bid_raw = (
            raw.get("best_bid")
            or raw.get("bestBid")
            or raw.get("bestBidYes")
            or raw.get("best_bid_yes")
            or raw.get("bid")
        )
        best_ask_raw = (
            raw.get("best_ask")
            or raw.get("bestAsk")
            or raw.get("bestAskYes")
            or raw.get("best_ask_yes")
            or raw.get("ask")
        )
        try:
            best_bid_val = Decimal(str(best_bid_raw)) if best_bid_raw is not None else None
        except Exception:
            best_bid_val = None
        try:
            best_ask_val = Decimal(str(best_ask_raw)) if best_ask_raw is not None else None
        except Exception:
            best_ask_val = None
        fx = await self.state.get_fx()
        if fx.stale and fx.source != "fallback":
            logger.warning(
                "Skipping publish due to stale FX",
                extra={"event": "publish.skipped.fx_stale", "market_id": market_id, "fx_source": fx.source},
            )
            return
        ts = datetime.now(UTC).isoformat()
        for idx, price in enumerate(prices):
            try:
                base_price = Decimal(str(price))
            except Exception as exc:
                logger.debug("price parse failed", extra={"event": "price.parse.failed", "error": str(exc)})
                base_price = None
            if base_price is None:
                continue
            worsened = (base_price * (Decimal("1") - Decimal(str(self.settings.worsen_percent)))).quantize(
                Decimal("0.0001")
            )
            payload = {
                "market_id": market_id,
                "outcome": idx,
                "type": "price",
                "price": str(base_price),
                "display_price": str(worsened),
                "timestamp": ts,
                "fx_zen_usd": str(fx.zen_usd),
                "fx_raw_zen_usd": str(fx.raw_zen_usd or fx.zen_usd),
                "fx_stale": fx.stale,
                "source": source,
                "best_bid": str(best_bid_val) if best_bid_val is not None else None,
                "best_ask": str(best_ask_val) if best_ask_val is not None else None,
                "display_best_bid": str(
                    best_bid_val * (Decimal("1") - Decimal(str(self.settings.worsen_percent)))
                )
                if best_bid_val is not None
                else None,
                "display_best_ask": str(
                    best_ask_val * (Decimal("1") - Decimal(str(self.settings.worsen_percent)))
                )
                if best_ask_val is not None
                else None,
                "tick_size": raw.get("tick_size") or raw.get("min_tick") or raw.get("tickSize"),
                "status": raw.get("status") or raw.get("state"),
            }
            try:
                self.metric_ticks.labels(
                    source=source, market=str(market_id), outcome=str(idx), stale=str(fx.stale)
                ).inc()
            except Exception as exc:
                logger.debug(
                    "failed to emit metric_ticks",
                    extra={"event": "metrics.tick.error", "error": str(exc), "market_id": market_id},
                )
            # In tests without the flush loop running, publish immediately.
            if self._tasks:
                await self._throttled_publish(market_id, str(idx), payload)
            else:
                await self.state.cache_tick(market_id, str(idx), payload)

    async def _throttled_publish(self, market_id: str, outcome: str, payload: dict) -> None:
        key = (market_id, outcome)
        existing = self._publish_cache.get(key)
        if existing and existing.get("price") == payload.get("price"):
            return
        self._publish_cache[key] = payload

    async def _rtds_loop(self) -> None:
        if not self.settings.rtds_enabled:
            return
        # Prime symbol filters
        if self.settings.rtds_crypto_symbols:
            for sym in self.settings.rtds_crypto_symbols.split(","):
                trimmed = sym.strip()
                if trimmed:
                    self.state.rtds_symbols.add(trimmed)
        while not self._stop.is_set():
            try:
                async for ws in iter_ws(self.settings.rtds_ws_url, name="rtds-ws"):
                    if self._stop.is_set():
                        break
                    await self._send_rtds_subscribe(ws)
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        await self._handle_rtds(data)
                        await asyncio.sleep(0)
            except Exception as exc:  # pragma: no cover - reconnect path
                logger.warning("RTDS loop error", extra={"event": "rtds.error", "error": str(exc)})
            await asyncio.sleep(self.settings.ws_reconnect_seconds)

    async def _send_rtds_subscribe(self, ws) -> None:
        subs: list[dict] = []
        if self.state.rtds_symbols:
            subs.append(
                {
                    "topic": self.settings.rtds_topic_crypto,
                    "type": "update",
                    "filters": ",".join(sorted(self.state.rtds_symbols)),
                }
            )
        if subs:
            payload = json.dumps({"action": "subscribe", "subscriptions": subs})
            await ws.send(payload)

    async def _handle_rtds(self, data: dict) -> None:
        topic = data.get("topic")
        payload = data.get("payload") or {}
        if topic != self.settings.rtds_topic_crypto:
            return
        symbol = payload.get("symbol")
        value = payload.get("value")
        if not symbol or value is None:
            return
        try:
            price = Decimal(str(value))
        except Exception:
            return
        self.state._register_fx(price, source="rtds_crypto", allow_jump=True)

    async def _fx_ws_loop(self) -> None:
        if not self.settings.fx_ws_url:
            return
        logger.info(
            "Starting FX websocket listener",
            extra={"event": "fx.ws.connect", "url": self.settings.fx_ws_url},
        )
        while not self._stop.is_set():
            try:
                async for ws in iter_ws(
                    self.settings.fx_ws_url,
                    name="fx-ws",
                    fatal_status={400, 401, 403, 404, 429},
                ):
                    if self._stop.is_set():
                        break
                    logger.info(
                        "FX websocket connected",
                        extra={"event": "fx.ws.connected", "url": self.settings.fx_ws_url},
                    )
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        logger.debug(
                            "FX ws message received",
                            extra={"event": "fx.ws.message", "raw_keys": list(data.keys()) if isinstance(data, dict) else None},
                        )
                        await self._handle_fx_ws(data)
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
                logger.warning("FX ws loop error", extra={"event": "fx.ws.error", "error": str(exc)})
            await asyncio.sleep(self.settings.ws_reconnect_seconds)

    async def _handle_fx_ws(self, data: dict) -> None:
        # Binance ticker shape: b=best bid, a=best ask, c=last price
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
            except Exception:
                price_val = None
        if price_val is None and last:
            try:
                price_val = Decimal(str(last))
            except Exception:
                price_val = None
        if price_val is None:
            return
        quote = self.state._register_fx(price_val, source="binance_ws")
        if not quote:
            return
        logger.debug(
            "FX quote updated from ws",
            extra={"event": "fx.ws.update", "price": str(price_val)},
        )
        self.state.fx_last_error = None
        self.state.fx_ws_connected = True
        self.metric_ws_restarts.inc()
        self._update_fx_metrics()
