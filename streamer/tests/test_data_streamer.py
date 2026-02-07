from __future__ import annotations

import asyncio
import logging

from app.config import Settings
from app.data_streamer import DataStreamer
from app.state import StreamState


def test_rest_poll_success_logs(caplog, monkeypatch):
    settings = Settings(rest_poll_seconds=5)
    state = StreamState(settings)
    streamer = DataStreamer(state, settings, metrics=None)

    async def _ok_poll():
        streamer._stop.set()
        return None

    monkeypatch.setattr(streamer, "_poll_rest", _ok_poll)
    caplog.set_level(logging.INFO, logger="reveal_market.streamer.data")

    state.active_connections = 1
    asyncio.run(streamer._rest_poll_loop())
    assert any(getattr(rec, "event", None) == "clob.rest.success" for rec in caplog.records)
