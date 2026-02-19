from __future__ import annotations

from app.config import Settings
from app.main import create_app
from app.state import StreamState

from tests.test_utils import DummyStreamer, noop


def test_logs_warning_when_rtds_disabled(monkeypatch, capsys):
    settings = Settings(rtds_enabled=False)
    state = StreamState(settings)

    state.startup = noop  # type: ignore[assignment]
    state.shutdown = noop  # type: ignore[assignment]
    monkeypatch.setattr("app.main.StreamState", lambda settings=None, metrics=None: state)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.main.DataStreamer", lambda *_args, **_kwargs: DummyStreamer())
    monkeypatch.setattr("app.main.PriceStreamer", lambda *_args, **_kwargs: DummyStreamer())

    create_app()
    captured = capsys.readouterr()
    assert "RTDS is disabled" in (captured.out or "")
