from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.main import create_app
from app.state import FxQuote, StreamState
from fastapi.testclient import TestClient


def test_fx_websocket_stream(monkeypatch):
    state = StreamState()
    now = datetime.now(UTC)
    adjusted = Decimal("5.5") * (Decimal("1") - Decimal(str(state.settings.worsen_percent)))
    state.fx_quote = FxQuote(zen_usd=adjusted, raw_zen_usd=Decimal("5.5"), fetched_at=now, stale=False, source="test")
    state.fx_last_update = now

    # Keep startup/shutdown from doing network work
    async def noop():
        return None

    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]

    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)

    class DummyStreamer:
        async def start(self): ...

        async def stop(self): ...

    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())

    app = create_app()
    with TestClient(app) as client:
        for path in ("/fx/zen-usd", "/fx/zen-usdc", "/fx/zen-usdt"):
            with client.websocket_connect(path) as ws:
                message = ws.receive_json()
                expected = float(Decimal("5.5") * (Decimal("1") - Decimal(str(state.settings.worsen_percent))))
                assert message["zen_usd"] == expected
                assert message["raw_zen_usd"] == 5.5
                assert message["stale"] is False
                assert message["pair"] == "ZEN/USDC"
