from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from .config import Settings
from .state import StreamState, iter_ws

logger = logging.getLogger("reveal_market.price_streamer.streamer")


class PriceStreamer:
    """Connects to Polymarket WS + REST, normalizes ticks, and publishes to Redis."""

    def __init__(self, state: StreamState, settings: Settings):
        self.state = state
        self.settings = settings
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()
        self._publish_cache: dict[str, dict] = {}

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
                await asyncio.sleep(self.settings.ws_reconnect_seconds)
                continue
            async for ws in iter_ws(self.settings.clob_ws_url):
                if self._stop.is_set():
                    break
                try:
                    await ws.send(self.state.subscriptions.build_clob_subscribe())
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        await self._handle_tick(data, source="ws")
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
            now = datetime.now(UTC)
            ws_stale = False
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
            await asyncio.sleep(self.settings.fx_rest_interval_seconds)

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

    async def _handle_tick(self, data: dict, source: str) -> None:
        market = data.get("market") or data.get("marketId") or data.get("id")
        if not market:
            return
        await self._normalize_and_publish(data, source=source)

    async def _normalize_and_publish(self, raw: dict, source: str) -> None:
        market_id = raw.get("id") or raw.get("marketId") or raw.get("market")
        prices = raw.get("outcomePrices") or raw.get("prices") or raw.get("outcomes")
        if not market_id or not prices or not isinstance(prices, (list, tuple)):
            return
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
                "price": str(base_price),
                "display_price": str(worsened),
                "timestamp": ts,
                "fx_zen_usd": str(fx.zen_usd),
                "fx_raw_zen_usd": str(fx.raw_zen_usd or fx.zen_usd),
                "fx_stale": fx.stale,
                "source": source,
            }
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
                async for ws in iter_ws(self.settings.rtds_ws_url):
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
        while not self._stop.is_set():
            try:
                async for ws in iter_ws(self.settings.fx_ws_url):
                    if self._stop.is_set():
                        break
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        await self._handle_fx_ws(data)
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
        self.state.fx_last_error = None
        self.state.fx_ws_connected = True
