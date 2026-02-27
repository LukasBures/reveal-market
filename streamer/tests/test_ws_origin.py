"""Tests for WebSocket Origin header validation (S2) and default limits (A1)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.config import Settings
from app.main import create_app
from app.state import FxQuote, StreamState
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.test_utils import DummyStreamer, noop


def _make_app(monkeypatch, *, environment: str = "local"):
    """Create an app with the given environment mode.

    Uses ``resolve_mode`` monkeypatch so preset CORS origins are resolved
    correctly (the ``create_app`` function overrides settings from presets).
    """
    monkeypatch.setattr("app.main.resolve_mode", lambda: environment)
    monkeypatch.setattr("app.env_presets.resolve_mode", lambda: environment)
    state = StreamState()
    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)
    state.fx_quote = FxQuote(
        zen_usd=Decimal("1.0"),
        raw_zen_usd=Decimal("1.0"),
        fetched_at=datetime.now(UTC),
        stale=False,
        source="test",
    )
    state.fx_last_update = datetime.now(UTC)
    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]
    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())
    monkeypatch.setattr("app.main.DataStreamer", lambda *_args, **_kwargs: DummyStreamer())
    app = create_app()
    return app, state


# ---------------------------------------------------------------------------
# S2: WebSocket Origin Validation
# ---------------------------------------------------------------------------


def test_ws_valid_origin_accepted(monkeypatch):
    """A WebSocket from a listed prod origin should be accepted."""
    app, _state = _make_app(monkeypatch, environment="prod")
    with TestClient(app) as client:
        # "https://revealmarket.xyz" is in the prod preset
        with client.websocket_connect("/fx/zen-usd", headers={"origin": "https://revealmarket.xyz"}) as ws:
            msg = ws.receive_json()
            assert "zen_usd" in msg


def test_ws_invalid_origin_rejected(monkeypatch):
    """A WebSocket from an unlisted origin should be rejected with 1008."""
    app, _state = _make_app(monkeypatch, environment="prod")
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/fx/zen-usd", headers={"origin": "https://evil.example.com"}) as ws:
                ws.receive_json()
        assert exc_info.value.code == 1008


def test_ws_missing_origin_rejected_in_prod(monkeypatch):
    """In prod, a missing Origin header should be rejected."""
    app, _state = _make_app(monkeypatch, environment="prod")
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/fx/zen-usd") as ws:
                ws.receive_json()
        assert exc_info.value.code == 1008


def test_ws_missing_origin_allowed_in_dev(monkeypatch):
    """In non-prod, missing Origin should be allowed for local dev tooling."""
    app, _state = _make_app(monkeypatch, environment="local")
    with TestClient(app) as client:
        with client.websocket_connect("/fx/zen-usd") as ws:
            msg = ws.receive_json()
            assert "zen_usd" in msg


# ---------------------------------------------------------------------------
# A1: Streamer WebSocket Default Limits
# ---------------------------------------------------------------------------


def test_default_max_connections_per_client():
    """Default max_connections_per_client should be 5 (not 0/disabled)."""
    s = Settings()
    assert s.max_connections_per_client == 5


def test_default_ws_max_messages_per_second():
    """Default ws_max_messages_per_second should be 100."""
    s = Settings()
    assert s.ws_max_messages_per_second == 100
