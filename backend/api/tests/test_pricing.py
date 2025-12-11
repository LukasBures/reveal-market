from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from app.config import Settings
from app.pricing import _FX_CACHE, fetch_fx_price_sync, fetch_fx_quote
from app.schemas import FxQuoteResponse


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


class _FailingClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, *_args, **_kwargs):
        raise httpx.HTTPStatusError(
            "429",
            request=httpx.Request("GET", "http://example.com"),
            response=httpx.Response(429, request=httpx.Request("GET", "http://example.com")),
        )


@pytest.fixture(autouse=True)
def clear_fx_cache():
    _FX_CACHE.clear()
    yield
    _FX_CACHE.clear()


@pytest.mark.asyncio
async def test_fetch_fx_quote_handles_nested_coingecko(monkeypatch):
    payload = {"horizen": {"usd": 7.5}, "stale": False}
    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: _DummyClient(payload))
    result = await fetch_fx_quote(Settings(fx_feed_url="http://example.com"))
    assert result.zen_usd == Decimal("7.5")
    assert result.stale is False


@pytest.mark.asyncio
async def test_fetch_fx_quote_propagates_stale_flag(monkeypatch):
    payload = {"price": "8.1", "fx_stale": True}
    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: _DummyClient(payload))
    result = await fetch_fx_quote(Settings(fx_feed_url="http://example.com"))
    assert result.zen_usd == Decimal("8.1")
    assert result.stale is True


@pytest.mark.asyncio
async def test_fetch_fx_quote_uses_cache_on_error(monkeypatch):
    payload = {"price": "9.0", "stale": False}
    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: _DummyClient(payload))
    settings = Settings(fx_feed_url="http://example.com", fx_cache_ttl_seconds=30)
    first = await fetch_fx_quote(settings)
    assert first.zen_usd == Decimal("9.0")
    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: _FailingClient())
    cached = await fetch_fx_quote(settings)
    assert cached.zen_usd == Decimal("9.0")
    assert cached.stale is True


def test_fetch_fx_price_sync_delegates(monkeypatch):
    async def fake_quote(_settings):
        return FxQuoteResponse(zen_usd=Decimal("5.0"), stale=False, received_at=None)

    monkeypatch.setattr("app.pricing.fetch_fx_quote", fake_quote)
    price, stale, received_at = fetch_fx_price_sync(Settings(fx_feed_url="http://example.com"))
    assert price == Decimal("5.0")
    assert stale is False
    assert received_at is None
