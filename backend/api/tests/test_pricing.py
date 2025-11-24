from __future__ import annotations

import pytest
from app.config import Settings
from app.pricing import fetch_fx_quote


class _DummyResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _DummyClient:
    def __init__(self, payload: dict):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, *_args, **_kwargs):
        return _DummyResponse(self._payload)


@pytest.mark.asyncio
async def test_fetch_fx_quote_handles_nested_coingecko(monkeypatch):
    payload = {"horizen": {"usd": 7.5}, "stale": False}
    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: _DummyClient(payload))
    result = await fetch_fx_quote(Settings(fx_feed_url="http://example.com"))
    assert result.zen_usd == 7.5
    assert result.stale is False


@pytest.mark.asyncio
async def test_fetch_fx_quote_propagates_stale_flag(monkeypatch):
    payload = {"price": "8.1", "fx_stale": True}
    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: _DummyClient(payload))
    result = await fetch_fx_quote(Settings(fx_feed_url="http://example.com"))
    assert result.zen_usd == 8.1
    assert result.stale is True
