from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.config import Settings
from app.state import StreamState
from app.streamer import PriceStreamer


@pytest.mark.asyncio
async def test_rtds_fx_updates_quote():
    settings = Settings(rtds_enabled=True)
    state = StreamState(settings)
    streamer = PriceStreamer(state, settings)
    # Seed a stale quote
    state.fx_quote = None
    payload = {
        "topic": settings.rtds_topic_crypto,
        "payload": {"symbol": "zenusdt", "value": 1.23, "timestamp": int(datetime.now(UTC).timestamp() * 1000)},
    }
    await streamer._handle_rtds(payload)
    assert state.fx_quote is not None
    assert state.fx_quote.zen_usd == Decimal("1.23")
    assert state.fx_quote.stale is False
