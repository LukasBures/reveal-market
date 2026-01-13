from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.state import StreamState


def test_should_log_stale_markets_throttles_by_interval():
    settings = Settings(market_stale_log_interval_seconds=300)
    state = StreamState(settings)
    now = datetime.now(UTC)

    assert state.should_log_stale_markets(5, min_interval_seconds=300) is True

    state._stale_log_last_at = now - timedelta(seconds=10)
    state._stale_log_last_count = 5
    assert state.should_log_stale_markets(5, min_interval_seconds=300) is False

    state._stale_log_last_at = now - timedelta(seconds=301)
    state._stale_log_last_count = 5
    assert state.should_log_stale_markets(5, min_interval_seconds=300) is True
