from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from prometheus_client import REGISTRY, Counter
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BookParams

from .config import Settings
from .rtds_client import PolymarketRTDSClient, Subscription
from .state import StreamState, get_http_client, iter_ws

if TYPE_CHECKING:
    from .metrics import StreamerMetrics

logger = logging.getLogger("reveal_market.streamer.data")
CLOB_PAGE_SIZE = 1000


class DataStreamer:
    """Streams Polymarket market data (CLOB WS/REST) and republishes to Redis/pubsub."""

    _metric_ticks_shared: Counter | None = None

    def __init__(self, state: StreamState, settings: Settings, metrics: StreamerMetrics | None = None):
        self.state = state
        self.settings = settings
        self.stream_metrics = metrics
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()
        self._publish_cache: dict[str, dict] = {}
        self.clob_client: ClobClient | None = None
        self._drop_log_counts: dict[tuple[str, str], int] = {}
        self._drop_log_last_emit: datetime | None = None
        self.rtds_client: PolymarketRTDSClient | None = None
        self._tune_http_logging()
        if getattr(self.settings, "clob_host", None):
            try:
                self.clob_client = ClobClient(str(self.settings.clob_host))
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to initialise CLOB client", extra={"event": "clob.init.failed", "error": str(exc)}
                )
        self.metric_ticks: Counter | None = None
        self._init_metrics()
        self._rtds_last_version: int = -1
        self._loop: asyncio.AbstractEventLoop | None = None

    @staticmethod
    def _coerce_array(value: Any) -> list | None:
        """Parse lists or JSON-encoded lists from Polymarket payloads."""

        if isinstance(value, (list, tuple)):
            return list(value)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return None
            if isinstance(parsed, list):
                return parsed
        return None

    def _extract_prices_for_validation(self, raw: dict) -> list[Decimal]:
        raw_prices = raw.get("outcomePrices") or raw.get("prices") or raw.get("outcomes")
        prices = self._coerce_array(raw_prices)
        parsed: list[Decimal] = []
        if prices:
            for value in prices:
                try:
                    parsed.append(Decimal(str(value)))
                except (ArithmeticError, ValueError, TypeError):
                    continue
            return parsed
        raw_tokens = raw.get("tokens")
        tokens = raw_tokens if isinstance(raw_tokens, list) else []
        for entry in tokens:
            if not isinstance(entry, dict):
                continue
            price_raw = entry.get("price")
            try:
                parsed.append(Decimal(str(price_raw)))
            except (ArithmeticError, ValueError, TypeError):
                continue
        return parsed

    def _validate_rest_market_with_reason(self, raw: dict) -> tuple[bool, str]:
        market_id = (
            raw.get("id")
            or raw.get("marketId")
            or raw.get("market")
            or raw.get("conditionId")
            or raw.get("condition_id")
        )
        if not market_id:
            return False, "missing_market_id"
        prices = self._extract_prices_for_validation(raw)
        if not prices:
            return False, "missing_prices"
        if len(prices) > 100:
            return False, "too_many_prices"
        for price in prices:
            if price.is_nan() or price.is_infinite():
                return False, "non_finite_price"
            if price < 0 or price > 1:
                return False, "price_out_of_range"
        if len(prices) == 2:
            total = prices[0] + prices[1]
            # Legacy/closed payloads can legitimately report [0, 0]; accept those.
            if total == 0:
                is_closed = bool(raw.get("closed") or raw.get("resolved") or raw.get("archived"))
                is_inactive = raw.get("active") is False
                if is_closed or is_inactive:
                    return True, "closed_zero_sum"
            if total < Decimal("0.9") or total > Decimal("1.1"):
                return False, "binary_sum_out_of_range"
        return True, "ok"

    def _validate_rest_market(self, raw: dict) -> bool:
        is_valid, _reason = self._validate_rest_market_with_reason(raw)
        return is_valid

    @staticmethod
    def _summarize_invalid_reasons(invalid_reasons: dict[str, int]) -> list[dict[str, int | str]]:
        ordered = sorted(invalid_reasons.items(), key=lambda item: item[1], reverse=True)
        return [{"reason": reason, "count": count} for reason, count in ordered]

    @staticmethod
    def _tune_http_logging() -> None:
        """Silence verbose httpx/httpcore access logs during tight rest-poll loops."""

        for name in ("httpx", "httpcore"):
            noisy = logging.getLogger(name)
            noisy.setLevel(logging.WARNING)

    def _record_drop_log(self, source: str, *, reason: str, payload_keys: list[str]) -> None:
        """Aggregate noisy drop logs to avoid spamming identical messages."""

        key = (source, reason)
        self._drop_log_counts[key] = self._drop_log_counts.get(key, 0) + 1
        now = datetime.now(UTC)
        should_emit = self._drop_log_last_emit is None or (now - self._drop_log_last_emit).total_seconds() >= 30
        if not should_emit:
            return

        if self._drop_log_counts:
            summary = [{"source": k[0], "reason": k[1], "count": v} for k, v in self._drop_log_counts.items()]
            logger.info(
                "Dropping payloads missing market/prices",
                extra={
                    "event": "ingest.drop.summary",
                    "drops": summary,
                    "payload_keys": payload_keys,
                },
            )
            self._drop_log_counts.clear()
        self._drop_log_last_emit = now

    def _init_metrics(self) -> None:
        if self.metric_ticks is not None:
            return
        if DataStreamer._metric_ticks_shared is None:
            DataStreamer._metric_ticks_shared = Counter(
                "streamer_ticks_total",
                "Published ticks",
                ["source", "stale"],
                registry=REGISTRY,
            )
        self.metric_ticks = DataStreamer._metric_ticks_shared

    def _set_clob_ws_connected(self, connected: bool, *, error: str | None = None) -> None:
        self.state.clob_ws_connected = connected
        if connected:
            self.state.clob_ws_last_error = None
        elif error:
            self.state.clob_ws_last_error = error
        if self.stream_metrics:
            with suppress(Exception):
                self.stream_metrics.record_clob_ws_connected(connected)

    def _record_clob_ws_message(self) -> None:
        now = datetime.now(UTC)
        self.state.clob_ws_last_message = now
        if self.stream_metrics:
            with suppress(Exception):
                self.stream_metrics.record_clob_ws_message(now)

    def _record_clob_rest_poll(self, *, success: bool, ts: datetime | None = None) -> None:
        now = ts or datetime.now(UTC)
        self.state.clob_rest_last_poll = now
        if success:
            self.state.clob_rest_last_success = now
            self.state.clob_rest_last_error = None
        if self.stream_metrics:
            with suppress(Exception):
                self.stream_metrics.record_clob_rest_poll(now)
                if success:
                    self.stream_metrics.record_clob_rest_success(now)

    def _set_rtds_connected(self, connected: bool, *, error: str | None = None) -> None:
        self.state.rtds_connected = connected
        if connected:
            self.state.rtds_last_error = None
        elif error:
            self.state.rtds_last_error = error
        if self.stream_metrics:
            with suppress(Exception):
                self.stream_metrics.record_rtds_ws_connected(connected)

    def _record_rtds_message(self) -> None:
        now = datetime.now(UTC)
        self.state.rtds_last_message = now
        if self.stream_metrics:
            with suppress(Exception):
                self.stream_metrics.record_rtds_message(now)

    def _ensure_rtds_client(self) -> None:
        """Initialise a lightweight RTDS client for subscription fan-out tests."""

        if self.rtds_client is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - fallback for sync callers
            loop = asyncio.get_event_loop()
        self._loop = loop

        def _dispatch(raw: dict[str, Any]) -> None:
            if not isinstance(raw, dict):
                return
            try:
                asyncio.run_coroutine_threadsafe(self._handle_rtds(raw), loop)
            except RuntimeError as exc:  # pragma: no cover - loop closed
                logger.debug(
                    "Failed to dispatch RTDS payload",
                    extra={"event": "rtds.dispatch.failed", "error": str(exc)},
                )

        self.rtds_client = PolymarketRTDSClient(
            url=self.settings.rtds_ws_url,
            on_raw_message=_dispatch,
            ping_interval=self.settings.rtds_ping_seconds,
            ping_timeout=max(3, self.settings.rtds_ping_seconds // 2),
            reconnect=False,
            backoff_initial=self.settings.ws_reconnect_seconds,
            backoff_max=max(self.settings.ws_reconnect_seconds, 1) * 5,
            logger=logging.getLogger("reveal_market.streamer.rtds"),
        )
        subs = self._build_rtds_subscriptions()
        if subs:
            with suppress(Exception):
                self.rtds_client.add_subscriptions(subs)

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._ws_loop(), name="ws-loop"),
            asyncio.create_task(self._rest_poll_loop(), name="rest-poll"),
            asyncio.create_task(self._flush_loop(), name="flush-loop"),
        ]
        if self.stream_metrics:
            with suppress(Exception):
                self.stream_metrics.record_rtds_enabled(self.settings.rtds_enabled)
                self.stream_metrics.record_clob_ws_connected(False)
                self.stream_metrics.record_rtds_ws_connected(False)
        if self.settings.rtds_enabled:
            self._tasks.append(asyncio.create_task(self._rtds_loop(), name="rtds-loop"))

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.rtds_client:
            with suppress(Exception):
                self.rtds_client.stop(wait=False)

    async def _ws_loop(self) -> None:
        while not self._stop.is_set():
            if not self.state.subscriptions.assets:
                if self.state.clob_ws_connected:
                    self._set_clob_ws_connected(False)
                logger.debug(
                    "CLOB ws idle; no subscriptions yet",
                    extra={
                        "event": "clob.ws.idle",
                        "subscriptions": 0,
                        "backoff_seconds": self.settings.ws_reconnect_seconds,
                    },
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
            try:
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
                        self.state.clob_ws_last_connect = datetime.now(UTC)
                        self._set_clob_ws_connected(True)
                        last_version = await self._refresh_clob_subscription(ws, last_version=-1)
                        msg_count = 0
                        last_data_time = time.monotonic()
                        while not self._stop.is_set():
                            try:
                                raw = await asyncio.wait_for(ws.recv(), timeout=1)
                            except TimeoutError:
                                if time.monotonic() - last_data_time > self.settings.ws_stale_timeout_seconds:
                                    logger.warning(
                                        "CLOB ws stale — no data messages received, forcing reconnect",
                                        extra={
                                            "event": "clob.ws.stale",
                                            "silent_seconds": self.settings.ws_stale_timeout_seconds,
                                        },
                                    )
                                    break
                                last_version = await self._refresh_clob_subscription(ws, last_version)
                                continue
                            last_data_time = time.monotonic()
                            self._record_clob_ws_message()
                            try:
                                payload = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            msg_count += 1
                            if msg_count % 50 == 1:
                                logger.info(
                                    "Received CLOB payload batch",
                                    extra={
                                        "event": "clob.ws.message",
                                        "count": msg_count,
                                        "subscriptions": len(self.state.subscriptions.assets),
                                    },
                                )
                            if isinstance(payload, list):
                                for item in payload:
                                    if isinstance(item, dict):
                                        await self._handle_tick(item, source="ws")
                            elif isinstance(payload, dict):
                                await self._handle_tick(payload, source="ws")
                            last_version = await self._refresh_clob_subscription(ws, last_version)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        self._set_clob_ws_connected(False, error=str(exc))
                        logger.warning(
                            "CLOB ws loop error",
                            extra={
                                "event": "clob.ws.error",
                                "error": str(exc),
                                "backoff_seconds": self.settings.ws_reconnect_seconds,
                            },
                        )
                        await asyncio.sleep(self.settings.ws_reconnect_seconds)
                if self.state.clob_ws_connected:
                    self._set_clob_ws_connected(False)
            except asyncio.CancelledError:
                raise

    async def _rest_poll_loop(self) -> None:
        while not self._stop.is_set():
            if self.state.active_connections <= 0 and not self.state.subscriptions.assets:
                await asyncio.sleep(self.settings.rest_poll_seconds)
                continue
            self._record_clob_rest_poll(success=False)
            try:
                await self._poll_rest()
                self._record_clob_rest_poll(success=True)
                logger.info(
                    "REST poll succeeded",
                    extra={
                        "event": "clob.rest.success",
                        "last_success": self.state.clob_rest_last_success.isoformat()
                        if self.state.clob_rest_last_success
                        else None,
                    },
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - network path
                self.state.clob_rest_last_error = str(exc)
                self._record_clob_rest_poll(success=False)
                logger.warning("REST poll failed", extra={"event": "polymarket.rest.failed", "error": str(exc)})
            await asyncio.sleep(self.settings.rest_poll_seconds)

    async def _flush_loop(self) -> None:
        interval = max(0.05, self.settings.publish_throttle_ms / 1000)
        try:
            while not self._stop.is_set():
                await asyncio.sleep(interval)
                if not self._publish_cache:
                    continue
                to_publish = self._publish_cache
                self._publish_cache = {}
                for key, payload in to_publish.items():
                    market_id, outcome = key.split(":", 1)
                    try:
                        await self.state.cache_tick(market_id, outcome, payload)
                    except Exception as exc:  # pragma: no cover - redis/runtime guard
                        logger.warning(
                            "tick publish failed",
                            extra={
                                "event": "stream.publish.failed",
                                "market_id": market_id,
                                "outcome": outcome,
                                "error": str(exc),
                            },
                        )
        except asyncio.CancelledError:
            return

    async def _poll_rest(self) -> None:
        total = 0
        cursor: str | None = None
        client = await get_http_client(10)
        while True:
            params: dict[str, int | str] = {"limit": CLOB_PAGE_SIZE}
            if cursor:
                # Polymarket CLOB REST expects next_cursor for pagination.
                params["next_cursor"] = cursor
                # Keep legacy cursor param for compatibility if upstream changes.
                params["cursor"] = cursor
            res = await client.get(str(self.settings.clob_rest_url), params=params)
            res.raise_for_status()
            payload = res.json()
            markets = payload if isinstance(payload, list) else payload.get("data") or []
            if not markets:
                if cursor:
                    logger.warning(
                        "CLOB REST returned empty page; stopping poll",
                        extra={"event": "clob.rest.empty", "cursor": cursor},
                    )
                break
            valid_markets: list[dict[str, Any]] = []
            invalid_reasons: dict[str, int] = {}
            for market in markets:
                if not isinstance(market, dict):
                    reason = "non_dict_payload"
                    invalid_reasons[reason] = invalid_reasons.get(reason, 0) + 1
                    if self.stream_metrics:
                        with suppress(Exception):
                            self.stream_metrics.record_drop("ingest", "invalid_payload")
                            self.stream_metrics.record_ingest_drop("rest", "invalid_payload")
                    continue

                is_valid, reason = self._validate_rest_market_with_reason(market)
                if not is_valid:
                    invalid_reasons[reason] = invalid_reasons.get(reason, 0) + 1
                    if self.stream_metrics:
                        with suppress(Exception):
                            self.stream_metrics.record_drop("ingest", "invalid_payload")
                            self.stream_metrics.record_ingest_drop("rest", "invalid_payload")
                    continue
                valid_markets.append(market)
                await self._normalize_and_publish(market, source="rest")

            if invalid_reasons:
                logger.warning(
                    "CLOB REST payloads failed validation",
                    extra={
                        "event": "clob.rest.invalid_payload.summary",
                        "invalid_count": sum(invalid_reasons.values()),
                        "invalid_reasons": self._summarize_invalid_reasons(invalid_reasons),
                        "page_size": len(markets) if isinstance(markets, list) else 0,
                        "cursor": cursor,
                    },
                )

            total += len(valid_markets)
            for market in valid_markets:
                market_id = str(market.get("id") or market.get("marketId") or "")
                tokens = self.state.get_clob_tokens(market_id)
                if market_id and tokens and market_id in self.state.subscriptions.assets:
                    self.state.subscriptions.replace_asset(market_id, tokens)
            cursor_val = payload.get("next_cursor") or payload.get("nextCursor") if isinstance(payload, dict) else None
            if cursor_val and cursor_val == cursor:
                logger.warning(
                    "CLOB REST cursor stalled; ending poll",
                    extra={"event": "clob.rest.cursor.stalled", "cursor": cursor_val},
                )
                break
            cursor = cursor_val or None
            if cursor is None:
                break
        logger.debug(
            "REST poll ingested markets",
            extra={"event": "clob.rest.poll", "count": total, "cursor": cursor},
        )

    async def _fetch_midpoints(self, token_ids: list[str]) -> list[Decimal] | None:
        if not self.clob_client:
            return None
        params = [BookParams(token_id=str(token_id)) for token_id in token_ids if str(token_id)]
        if not params:
            return None
        try:
            midpoints = await asyncio.to_thread(self.clob_client.get_midpoints, params)
        except Exception as exc:  # pragma: no cover - network path
            logger.info("CLOB midpoint fetch failed", extra={"event": "clob.midpoints.failed", "error": str(exc)})
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
                except (ArithmeticError, ValueError, TypeError) as exc:
                    logger.info(
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
            if self.stream_metrics:
                with suppress(Exception):
                    self.stream_metrics.record_ingest_drop(source, "missing_market_or_prices")
            return
        await self._normalize_and_publish(data, source=source)

    async def _handle_market_event(self, data: dict, source: str) -> None:
        event_type = (data.get("event_type") or data.get("type") or "").lower()
        market = data.get("market") or data.get("marketId") or data.get("id")
        if not market:
            if self.stream_metrics:
                with suppress(Exception):
                    self.stream_metrics.record_ingest_drop(source, "missing_market_or_prices")
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
            depth_limit = 5
            depth_bids: list[dict] = []
            depth_asks: list[dict] = []
            if isinstance(bids, list) and bids:
                parsed_bids: list[tuple[Decimal, Decimal | None]] = []
                for entry in bids:
                    price_raw = entry.get("price") if isinstance(entry, dict) else entry
                    size_raw = entry.get("size") if isinstance(entry, dict) else None
                    try:
                        price_val = Decimal(str(price_raw))
                    except (ArithmeticError, ValueError, TypeError):
                        continue
                    try:
                        size_val = Decimal(str(size_raw)) if size_raw is not None else None
                    except (ArithmeticError, ValueError, TypeError):
                        size_val = None
                    parsed_bids.append((price_val, size_val))
                if parsed_bids:
                    best_bid = max(p[0] for p in parsed_bids)
                    for price_val, size_val in sorted(parsed_bids, key=lambda p: p[0], reverse=True)[:depth_limit]:
                        depth_bids.append(
                            {"price": str(price_val), "size": str(size_val) if size_val is not None else None}
                        )
            if isinstance(asks, list) and asks:
                parsed_asks: list[tuple[Decimal, Decimal | None]] = []
                for entry in asks:
                    price_raw = entry.get("price") if isinstance(entry, dict) else entry
                    size_raw = entry.get("size") if isinstance(entry, dict) else None
                    try:
                        price_val = Decimal(str(price_raw))
                    except (ArithmeticError, ValueError, TypeError):
                        continue
                    try:
                        size_val = Decimal(str(size_raw)) if size_raw is not None else None
                    except (ArithmeticError, ValueError, TypeError):
                        size_val = None
                    parsed_asks.append((price_val, size_val))
                if parsed_asks:
                    best_ask = min(p[0] for p in parsed_asks)
                    for price_val, size_val in sorted(parsed_asks, key=lambda p: p[0])[:depth_limit]:
                        depth_asks.append(
                            {"price": str(price_val), "size": str(size_val) if size_val is not None else None}
                        )
            payload = {
                "market_id": market,
                "type": "book",
                "best_bid": str(best_bid) if best_bid is not None else None,
                "best_ask": str(best_ask) if best_ask is not None else None,
                "midpoint": str((best_bid + best_ask) / 2) if best_bid is not None and best_ask is not None else None,
                "display_best_bid": str(best_bid * (Decimal("1") - Decimal(str(self.settings.worsen_percent))))
                if best_bid is not None
                else None,
                "display_best_ask": str(best_ask * (Decimal("1") - Decimal(str(self.settings.worsen_percent))))
                if best_ask is not None
                else None,
                "display_midpoint": (
                    str(((best_bid + best_ask) / 2) * (Decimal("1") - Decimal(str(self.settings.worsen_percent))))
                    if best_bid is not None and best_ask is not None
                    else None
                ),
                "spread": str(best_ask - best_bid) if best_bid is not None and best_ask is not None else None,
                "depth_bids": depth_bids,
                "depth_asks": depth_asks,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            await self.state.cache_tick(market, "meta", payload)
            return
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

    @staticmethod
    def _extract_tokens(raw: dict) -> tuple[list[Decimal], list[str]]:
        """Parse token prices and IDs from a raw tick payload."""
        raw_tokens = raw.get("tokens")
        tokens = raw_tokens if isinstance(raw_tokens, list) else []
        token_prices: list[Decimal] = []
        token_ids: list[str] = []
        for entry in tokens:
            if not isinstance(entry, dict):
                continue
            price_raw = entry.get("price")
            try:
                token_prices.append(Decimal(str(price_raw)))
            except (ArithmeticError, ValueError, TypeError) as exc:
                logger.debug("Invalid token price in payload: %s (%s)", price_raw, exc)
            token_id_raw = entry.get("token_id") or entry.get("tokenId") or entry.get("id")
            if token_id_raw is not None:
                token_ids.append(str(token_id_raw))
        return token_prices, token_ids

    @staticmethod
    def _extract_bid_ask(raw: dict) -> tuple[Decimal | None, Decimal | None]:
        """Parse best bid/ask from a raw tick payload."""
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
        except (ArithmeticError, ValueError, TypeError):
            best_bid_val = None
        try:
            best_ask_val = Decimal(str(best_ask_raw)) if best_ask_raw is not None else None
        except (ArithmeticError, ValueError, TypeError):
            best_ask_val = None
        return best_bid_val, best_ask_val

    async def _normalize_and_publish(self, raw: dict, source: str) -> None:
        market_id = (
            raw.get("id")
            or raw.get("marketId")
            or raw.get("market")
            or raw.get("conditionId")
            or raw.get("condition_id")
        )
        raw_prices = raw.get("outcomePrices") or raw.get("prices") or raw.get("outcomes")
        token_prices, token_ids_from_tokens = self._extract_tokens(raw)
        prices = self._coerce_array(raw_prices) or token_prices
        token_ids_raw = raw.get("clobTokenIds") or raw.get("clob_token_ids") or raw.get("tokenIds")
        token_ids = self._coerce_array(token_ids_raw) or token_ids_from_tokens
        coerced_token_ids = [str(token) for token in token_ids if str(token).strip()]
        if market_id and coerced_token_ids:
            self.state.register_clob_tokens(str(market_id), coerced_token_ids)
            midpoints = await self._fetch_midpoints(coerced_token_ids)
            if midpoints and len(midpoints) == len(coerced_token_ids):
                prices = midpoints
        if not market_id or not prices or not isinstance(prices, (list, tuple)):
            if self.stream_metrics:
                reason = "missing_market" if not market_id else "missing_prices"
                try:
                    self.stream_metrics.record_drop("ingest", reason)
                    self.stream_metrics.record_ingest_drop(source, reason)
                except Exception as exc:
                    logger.info("Failed to record drop metric", exc_info=exc)
            self._record_drop_log(source, reason="missing_market_or_prices", payload_keys=list(raw.keys()))
            return
        self.state.last_seen[str(market_id)] = datetime.now(UTC)
        if self.stream_metrics:
            with suppress(Exception):
                self.stream_metrics.market_staleness.labels(market_id=str(market_id)).set(0)
        best_bid_val, best_ask_val = self._extract_bid_ask(raw)
        fx = await self.state.get_fx()
        if fx.stale and not self.settings.publish_when_fx_stale:
            logger.warning(
                "Skipping publish due to stale FX",
                extra={
                    "event": "publish.skipped.fx_stale",
                    "market_id": market_id,
                    "fx_source": fx.source,
                    "policy": "block",
                },
            )
            if self.stream_metrics:
                with suppress(Exception):
                    self.stream_metrics.record_drop("ingest", "fx_stale")
            return
        ts = datetime.now(UTC).isoformat()
        for idx, price in enumerate(prices):
            try:
                base_price = Decimal(str(price))
            except (ArithmeticError, ValueError, TypeError) as exc:
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
                "display_best_bid": str(best_bid_val * (Decimal("1") - Decimal(str(self.settings.worsen_percent))))
                if best_bid_val is not None
                else None,
                "display_best_ask": str(best_ask_val * (Decimal("1") - Decimal(str(self.settings.worsen_percent))))
                if best_ask_val is not None
                else None,
                "tick_size": raw.get("tick_size") or raw.get("min_tick") or raw.get("tickSize"),
                "status": raw.get("status") or raw.get("state"),
            }
            try:
                if self.metric_ticks:
                    self.metric_ticks.labels(
                        source=source, stale=str(fx.stale)
                    ).inc()
            except Exception as exc:
                logger.debug(
                    "failed to emit metric_ticks",
                    extra={"event": "metrics.tick.error", "error": str(exc), "market_id": market_id},
                )
            if self._tasks:
                await self._throttled_publish(market_id, str(idx), payload)
            else:
                await self.state.cache_tick(market_id, str(idx), payload)

    async def _throttled_publish(self, market_id: str, outcome: str, payload: dict) -> None:
        key = f"{market_id}:{outcome}"
        existing = self._publish_cache.get(key)
        if existing and existing.get("price") == payload.get("price"):
            return
        self._publish_cache[key] = payload

    async def _maybe_refresh_rtds_subscriptions(self) -> None:
        """Send updated RTDS subscription set when assets/symbols change."""

        if self.rtds_client is None:
            self._ensure_rtds_client()
        if not self.rtds_client:
            return
        latest_version = max(self.state.subscriptions.version, getattr(self.state, "rtds_symbols_version", 0))
        if latest_version == self._rtds_last_version:
            return
        subs = self._build_rtds_subscriptions()
        if not subs:
            self._rtds_last_version = latest_version
            return
        try:
            self.rtds_client.add_subscriptions(subs)
            self._rtds_last_version = latest_version
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Failed to refresh RTDS subscriptions",
                extra={"event": "rtds.refresh.failed", "error": str(exc)},
            )

    async def _rtds_loop(self) -> None:
        if not self.settings.rtds_enabled:
            return
        while not self._stop.is_set():
            try:
                subs = self._build_rtds_subscriptions()
                current_version = max(self.state.subscriptions.version, getattr(self.state, "rtds_symbols_version", 0))
                if not subs:
                    await asyncio.sleep(self.settings.ws_reconnect_seconds)
                    continue
                async for ws in iter_ws(
                    self.settings.rtds_ws_url,
                    name="rtds",
                    ping_interval=self.settings.rtds_ping_seconds,
                    ping_timeout=max(3, self.settings.rtds_ping_seconds // 2),
                    read_timeout=self.settings.ws_reconnect_seconds,
                ):
                    if self._stop.is_set():
                        break
                    self.state.rtds_last_connect = datetime.now(UTC)
                    self._set_rtds_connected(True)
                    await ws.send(json.dumps({"action": "subscribe", "subscriptions": [s.to_wire() for s in subs]}))
                    self._rtds_last_version = current_version
                    try:
                        async for raw in ws:
                            if self._stop.is_set():
                                break
                            self._record_rtds_message()
                            try:
                                payload = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            await self._handle_rtds(payload)
                            latest_version = max(
                                self.state.subscriptions.version, getattr(self.state, "rtds_symbols_version", 0)
                            )
                            if latest_version != self._rtds_last_version:
                                subs = self._build_rtds_subscriptions()
                                if not subs:
                                    break
                                await ws.send(
                                    json.dumps({"action": "subscribe", "subscriptions": [s.to_wire() for s in subs]})
                                )
                                self._rtds_last_version = latest_version
                    except TimeoutError:
                        continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - reconnect path
                self._set_rtds_connected(False, error=str(exc))
                logger.warning("RTDS loop error", extra={"event": "rtds.error", "error": str(exc)})
            if self.state.rtds_connected:
                self._set_rtds_connected(False)
            await asyncio.sleep(self.settings.ws_reconnect_seconds)

    def _build_rtds_subscriptions(self) -> list[Subscription]:
        assets = sorted(self.state.subscriptions.assets)
        symbols = sorted(self.state.rtds_symbols)
        if not assets and not symbols:
            return []
        filters: list[str] = []
        seen: set[str] = set()
        for asset in assets:
            if asset in seen:
                continue
            if len(filters) >= self.settings.max_subscriptions:
                break
            filters.append(asset)
            seen.add(asset)
        if len(filters) < self.settings.max_subscriptions:
            for symbol in symbols:
                if symbol in seen:
                    continue
                if len(filters) >= self.settings.max_subscriptions:
                    break
                filters.append(symbol)
                seen.add(symbol)
        if not filters:
            return []
        return [
            Subscription(
                topic=self.settings.rtds_topic_clob,
                type="agg_orderbook",
                filters=filters,
            )
        ]

    async def _refresh_clob_subscription(self, ws, last_version: int) -> int:
        current_version = self.state.subscriptions.version
        if current_version != last_version:
            payload = self.state.subscriptions.build_clob_subscribe()
            logger.debug(
                "Sending CLOB subscribe",
                extra={
                    "event": "clob.ws.subscribe",
                    "payload": payload,
                    "subscriptions": sorted(self.state.subscriptions.assets),
                },
            )
            await ws.send(payload)
            return current_version
        return last_version

    async def _handle_rtds(self, data: dict) -> None:
        topic = data.get("topic")
        payload = data.get("payload")
        if topic != self.settings.rtds_topic_clob or payload is None:
            return
        # RTDS market data: payload may be a dict or list; normalize to our tick handler.
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    await self._handle_tick(item, source="rtds")
        elif isinstance(payload, dict):
            await self._handle_tick(payload, source="rtds")
