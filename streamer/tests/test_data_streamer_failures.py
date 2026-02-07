from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.config import Settings
from app.data_streamer import DataStreamer
from app.state import StreamState


def test_rest_poll_failure_sets_last_error(caplog, monkeypatch):
    settings = Settings(rest_poll_seconds=5)
    state = StreamState(settings)
    streamer = DataStreamer(state, settings, metrics=None)

    async def _boom():
        streamer._stop.set()
        raise RuntimeError("boom")

    monkeypatch.setattr(streamer, "_poll_rest", _boom)
    caplog.set_level(logging.WARNING, logger="reveal_market.streamer.data")

    state.active_connections = 1
    asyncio.run(streamer._rest_poll_loop())
    assert state.clob_rest_last_error == "boom"
    assert any(getattr(rec, "event", None) == "polymarket.rest.failed" for rec in caplog.records)


def test_rtds_connection_transitions_update_state():
    settings = Settings(rtds_enabled=True)
    state = StreamState(settings)
    streamer = DataStreamer(state, settings, metrics=None)

    streamer._set_rtds_connected(True)
    assert state.rtds_connected is True
    assert state.rtds_last_error is None

    streamer._set_rtds_connected(False, error="offline")
    assert state.rtds_connected is False
    assert state.rtds_last_error == "offline"


def test_record_clob_ws_message_updates_timestamp():
    settings = Settings()
    state = StreamState(settings)
    streamer = DataStreamer(state, settings, metrics=None)
    before = datetime.now(UTC)

    streamer._record_clob_ws_message()
    assert state.clob_ws_last_message is not None
    assert state.clob_ws_last_message >= before
