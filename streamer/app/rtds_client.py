from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import websocket  # type: ignore[import-not-found]  # pip install websocket-client

"""
Polymarket Real-Time Data Streaming (RTDS) client.

- Connects to wss://ws-live-data.polymarket.com
- Supports public topics only (no clob_user auth).
- Handles automatic reconnect with backoff.
- Keeps a registry of subscriptions and re-subscribes on reconnect.
- Dispatches messages via pluggable router / callbacks.
"""

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Subscription:
    """
    Represents a subscription entry to RTDS.

    Example payload on the wire:
    {
        "topic": "clob_market",
        "type": "agg_orderbook",
        "filters": ["1096..."],
    }
    """

    topic: str
    type: str = "*"
    filters: Any | None = None

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "topic": self.topic,
            "type": self.type,
        }
        if self.filters is not None:
            filters = self.filters
            # RTDS expects filters as a JSON string; normalise iterables to JSON for compatibility.
            if isinstance(filters, Iterable) and not isinstance(filters, (str, bytes)):
                try:
                    filters = json.dumps(list(filters))
                except (TypeError, ValueError):
                    filters = str(filters)
            payload["filters"] = filters
        return payload


@dataclass
class RTDSMessage:
    """
    Generic RTDS message envelope.

    Expected wire format:
    {
        "topic": "clob_market",
        "type": "agg_orderbook",
        "payload": {...}
    }
    """

    topic: str
    type: str
    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Router for topic/type → handler
# ---------------------------------------------------------------------------

HandlerFn = Callable[[RTDSMessage], None]


class RTDSRouter:
    """
    Simple in-process router that maps (topic, type) → handler function.

    You can:
    - register(topic="clob_market", type="agg_orderbook", handler=fn)
    - register(topic="crypto_prices", type="update", handler=fn)
    - register(topic="*", type="*", handler=fn) for a catch-all
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(__name__)
        self._handlers: dict[tuple[str, str], HandlerFn] = {}
        self._wildcard_topic_handlers: dict[str, HandlerFn] = {}
        self._wildcard_type_handlers: dict[str, HandlerFn] = {}
        self._catch_all: HandlerFn | None = None

    def register(
        self,
        topic: str,
        message_type: str,
        handler: HandlerFn,
    ) -> None:
        """
        Register a handler.

        topic/type can be "*".
        Precedence:
          1. exact (topic, type)
          2. (topic, "*")
          3. ("*", type)
          4. ("*", "*") catch-all
        """
        if topic == "*" and message_type == "*":
            self._catch_all = handler
        elif topic == "*" and message_type != "*":
            self._wildcard_topic_handlers[message_type] = handler
        elif topic != "*" and message_type == "*":
            self._wildcard_type_handlers[topic] = handler
        else:
            self._handlers[(topic, message_type)] = handler

    def dispatch(self, msg: RTDSMessage) -> None:
        """
        Dispatch a message to the most specific handler.
        """
        topic, type_ = msg.topic, msg.type

        handler = self._handlers.get((topic, type_))
        if handler:
            handler(msg)
            return

        handler = self._wildcard_type_handlers.get(topic)
        if handler:
            handler(msg)
            return

        handler = self._wildcard_topic_handlers.get(type_)
        if handler:
            handler(msg)
            return

        if self._catch_all:
            self._catch_all(msg)
            return

        # No handler; optional debug log
        self._logger.debug(
            "No handler for RTDS message topic=%s type=%s",
            topic,
            type_,
        )


# ---------------------------------------------------------------------------
# RTDS client
# ---------------------------------------------------------------------------


class PolymarketRTDSClient:
    """
    Low-level RTDS WebSocket client.

    Features:
    - Connect to RTDS URL (defaults to wss://ws-live-data.polymarket.com)
    - Maintain subscriptions and re-subscribe on reconnect
    - Automatic ping/pong via websocket-client
    - Reconnect loop with exponential backoff
    - Thread-safe subscribe() API
    """

    def __init__(
        self,
        url: str = "wss://ws-live-data.polymarket.com",
        router: RTDSRouter | None = None,
        on_raw_message: Callable[[dict[str, Any]], None] | None = None,
        on_connect: Callable[[PolymarketRTDSClient], None] | None = None,
        on_disconnect: Callable[[PolymarketRTDSClient], None] | None = None,
        ping_interval: int = 20,
        ping_timeout: int = 10,
        reconnect: bool = True,
        max_retries: int | None = None,
        backoff_initial: float = 1.0,
        backoff_max: float = 30.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.url = url
        self.router = router or RTDSRouter()
        self.on_raw_message = on_raw_message
        self.on_connect_cb = on_connect
        self.on_disconnect_cb = on_disconnect
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.reconnect = reconnect
        self.max_retries = max_retries
        self.backoff_initial = backoff_initial
        self.backoff_max = backoff_max

        self._logger = logger or logging.getLogger("polymarket_rtds")
        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._subscriptions: list[Subscription] = []
        self._sub_lock = threading.Lock()

        self._retry_count = 0

    # ------------------------------ public API ------------------------------

    def add_subscription(self, subscription: Subscription) -> None:
        """
        Register a subscription and, if already connected, send it immediately.
        """
        with self._sub_lock:
            if subscription not in self._subscriptions:
                self._subscriptions.append(subscription)

        if self._ws is not None:
            try:
                self._send_subscriptions([subscription])
            except (TypeError, ValueError):
                self._logger.exception("Failed to send subscription to RTDS")

    def add_subscriptions(self, subs: list[Subscription]) -> None:
        """
        Register multiple subscriptions at once.
        """
        to_send: list[Subscription] = []
        with self._sub_lock:
            for sub in subs:
                if sub not in self._subscriptions:
                    self._subscriptions.append(sub)
                    to_send.append(sub)

        if self._ws is not None and to_send:
            try:
                self._send_subscriptions(to_send)
            except (TypeError, ValueError):
                self._logger.exception("Failed to send subscriptions to RTDS")

    def start_in_thread(self, name: str = "PolymarketRTDSClient") -> None:
        """
        Start the client run loop in a background thread.
        """
        if self._thread and self._thread.is_alive():
            self._logger.warning("RTDS client thread already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_forever, name=name, daemon=True)
        self._thread.start()

    def stop(self, wait: bool = True) -> None:
        """
        Signal the client to stop and close the WebSocket.
        """
        self._stop_event.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception as exc:  # pragma: no cover - defensive guard
                self._logger.exception("Error while closing WebSocket: %s", exc)

        if wait and self._thread:
            self._thread.join(timeout=5)

    # ---------------------------- internal logic ----------------------------

    def _run_forever(self) -> None:
        """
        Main reconnect loop.
        """
        backoff = self.backoff_initial

        while not self._stop_event.is_set():
            self._logger.info("Connecting to Polymarket RTDS at %s", self.url)

            self._ws = websocket.WebSocketApp(
                self.url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )

            # Run connection (blocks until closed or error)
            self._ws.run_forever(
                ping_interval=self.ping_interval,
                ping_timeout=self.ping_timeout,
                ping_payload="PING",
                origin=None,
            )

            # On exit from run_forever
            if self._stop_event.is_set():
                self._logger.info("RTDS client stop requested, exiting loop")
                break

            self._retry_count += 1
            if self.max_retries is not None and self._retry_count > self.max_retries:
                self._logger.error(
                    "Maximum RTDS reconnect attempts reached (%s). Stopping.",
                    self.max_retries,
                )
                break

            if not self.reconnect:
                self._logger.info("Reconnect disabled, exiting loop")
                break

            self._logger.warning(
                "RTDS connection lost, retrying in %.1f seconds (attempt %d)",
                backoff,
                self._retry_count,
            )
            time.sleep(backoff)
            backoff = min(self.backoff_max, backoff * 2)

    # ---------------------------- WebSocket callbacks -----------------------

    def _on_open(self, _ws: Any) -> None:
        self._logger.info("RTDS WebSocket connection opened")

        # Reset retry counters
        self._retry_count = 0

        # Re-send all subscriptions
        with self._sub_lock:
            subs_copy = list(self._subscriptions)

        if subs_copy:
            self._logger.info("Re-subscribing to %d RTDS subscriptions", len(subs_copy))
            try:
                self._send_subscriptions(subs_copy)
            except (TypeError, ValueError):
                self._logger.exception("Failed to send initial subscriptions")

        # Fire on_connect callback
        if self.on_connect_cb:
            try:
                self.on_connect_cb(self)
            except Exception as exc:  # pragma: no cover - defensive guard
                self._logger.exception("on_connect callback raised: %s", exc)

    def _on_message(self, _ws: Any, message: str) -> None:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            self._logger.warning("Received non-JSON message from RTDS: %r", message)
            return

        # Optional raw-message callback (for logging / tracing)
        if self.on_raw_message:
            try:
                self.on_raw_message(data)
            except Exception as exc:  # pragma: no cover - defensive callback guard
                self._logger.exception("on_raw_message callback raised: %s", exc)

        topic = data.get("topic")
        type_ = data.get("type")
        payload = data.get("payload")

        if not topic or not type_:
            self._logger.debug("Ignoring RTDS message without topic/type: %s", data)
            return

        msg = RTDSMessage(topic=topic, type=type_, payload=payload, raw=data)

        try:
            self.router.dispatch(msg)
        except Exception as exc:  # pragma: no cover - defensive dispatch guard
            self._logger.exception("Error while dispatching RTDS message topic=%s type=%s error=%s", topic, type_, exc)

    def _on_error(self, _ws: Any, error: Any) -> None:
        self._logger.error("RTDS WebSocket error: %s", error)

    def _on_close(
        self,
        _ws: Any,
        close_status_code: int | None,
        close_msg: str | None,
    ) -> None:
        self._logger.warning("RTDS WebSocket closed (code=%s, msg=%s)", close_status_code, close_msg)
        if self.on_disconnect_cb:
            try:
                self.on_disconnect_cb(self)
            except Exception as exc:  # pragma: no cover - defensive guard
                self._logger.exception("on_disconnect callback raised: %s", exc)

    # ---------------------------- helpers -----------------------------------

    def _send_subscriptions(self, subs: list[Subscription]) -> None:
        """
        Send a subscription message for given subscriptions.

        Wire format:
        {
            "subscriptions": [
                {"topic": "...", "type": "...", "filters": ...},
                ...
            ]
        }
        """
        if not self._ws:
            raise RuntimeError("WebSocket is not initialized")

        payload = {
            "action": "subscribe",
            "subscriptions": [s.to_wire() for s in subs],
        }
        msg = json.dumps(payload)
        self._logger.debug("Sending RTDS subscriptions: %s", msg)
        self._ws.send(msg)
