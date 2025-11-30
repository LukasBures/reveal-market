from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.config import Settings
from app.data_streamer import DataStreamer
from app.state import FxQuote, StreamState


class PubSubState(StreamState):
    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.queue: asyncio.Queue = asyncio.Queue()
        self.cached: list[dict] = []

    async def cache_tick(self, market_id: str, outcome: str, payload: dict) -> None:
        await self.queue.put({"market_id": market_id, "outcome": outcome, "payload": payload})
        self.cached.append(payload)

    async def subscribe(self, market_id: str):  # type: ignore[override]
        queue = self.queue

        class DummyPubSub:
            def __init__(self, q: asyncio.Queue):
                self._q = q

            async def get_message(self, ignore_subscribe_messages=True, timeout=None):
                try:
                    return await asyncio.wait_for(self._q.get(), timeout=timeout or 0.5)
                except TimeoutError:
                    return None

            async def close(self):
                return

        return DummyPubSub(queue)


@pytest.mark.asyncio
async def test_clob_ws_integration_with_reconnect(monkeypatch):
    settings = Settings(ws_reconnect_seconds=0.01, rest_poll_seconds=5)
    state = PubSubState(settings)
    now = datetime.now(UTC)
    state.fx_quote = FxQuote(zen_usd=Decimal("1"), raw_zen_usd=Decimal("1"), fetched_at=now, stale=False, source="test")

    async def fake_fx():
        return state.fx_quote

    state.get_fx = fake_fx  # type: ignore[assignment]
    state.refresh_fx = fake_fx  # type: ignore[assignment]
    state.subscriptions.add_assets(["tok-a"])
    streamer = DataStreamer(state, settings)
    msgs = [
        json.dumps([{"id": "m-integ", "outcomePrices": [0.4, 0.6]}]),
        json.dumps([{"id": "m-integ", "outcomePrices": [0.5, 0.5]}]),
    ]
    sent_payloads: list[str] = []

    class DummyWS:
        def __init__(self, payloads):
            self.payloads = payloads
            self.sent = []

        async def send(self, payload):
            self.sent.append(payload)

        async def recv(self):
            if not self.payloads:
                streamer._stop.set()
                raise TimeoutError
            return self.payloads.pop(0)

    async def fake_iter_ws(url, name="ws", fatal_status=None):
        ws = DummyWS(msgs.copy())
        yield ws
        sent_payloads.extend(ws.sent)

    monkeypatch.setattr("app.data_streamer.iter_ws", fake_iter_ws)
    await asyncio.wait_for(streamer._ws_loop(), timeout=1)
    assert any(payload.get("price") for payload in state.cached)
    assert any("tok-a" in s for s in sent_payloads)


@pytest.mark.asyncio
async def test_rtds_dispatch_and_metrics(monkeypatch):
    settings = Settings()
    state = PubSubState(settings)
    state.subscriptions.add_assets(["tok-z"])
    streamer = DataStreamer(state, settings)
    streamer._ensure_rtds_client()
    try:
        # Directly dispatch RTDS payload.
        await streamer._handle_rtds(
            {"topic": settings.rtds_topic_clob, "payload": {"id": "m9", "outcomePrices": [0.7]}}
        )
        assert any(p.get("price") == "0.7" for p in state.cached)
    finally:
        if streamer.rtds_client:
            streamer.rtds_client.stop(wait=False)
