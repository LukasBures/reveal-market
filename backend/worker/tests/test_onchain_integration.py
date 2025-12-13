from __future__ import annotations

from types import SimpleNamespace

from app.config import Settings
from app.onchain import maybe_create_onchain_market
from pydantic import SecretStr


def test_onchain_creation_skips_when_disabled(monkeypatch):
    settings = Settings()
    market = SimpleNamespace(event_id="evt", oracle="0xabc", collateral=None, market_address=None, rake_bps=None)

    class Session:
        def flush(self):
            self.flushed = True

    session = Session()
    result = maybe_create_onchain_market(settings, market, session)
    assert result is None
    assert not hasattr(session, "flushed")


def test_onchain_creation_missing_config(monkeypatch):
    data = Settings(auto_create_onchain_markets=True)
    market = SimpleNamespace(event_id="evt", oracle="0xabc", collateral=None, market_address=None, rake_bps=None)

    class Session:
        def flush(self):
            self.flushed = True

    session = Session()
    result = maybe_create_onchain_market(data, market, session)
    assert result is None
    assert not hasattr(session, "flushed")


def test_onchain_creation_happy_path(monkeypatch):
    settings = Settings(auto_create_onchain_markets=True)
    settings.factory_address = "0x1234567890abcdef1234567890abcdef12345678"
    settings.rpc_url = "https://unit.test"  # type: ignore[assignment]
    settings.wallet_private_key = SecretStr("0x1000000000000000000000000000000000000000000000000000000000000000")
    settings.wallet_address = "0xfeedfeedfeedfeedfeedfeedfeedfeedfeedfeed"
    market = SimpleNamespace(
        event_id="evt",
        oracle="0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
        collateral=None,
        market_address=None,
        rake_bps=None,
    )

    class Session:
        def __init__(self):
            self.flushed = False

        def flush(self):
            self.flushed = True

    session = Session()

    async def fake_send(**kwargs):
        return "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 1

    async def fake_next_market_id(*args, **kwargs):
        return 1

    async def fake_predict_address(*args, **kwargs):
        return "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

    monkeypatch.setattr("app.onchain._send_create_market_transaction", fake_send)
    monkeypatch.setattr("app.onchain.get_next_market_id", fake_next_market_id)
    monkeypatch.setattr("app.onchain.predict_market_address", fake_predict_address)

    result = maybe_create_onchain_market(settings, market, session)
    assert result == "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert session.flushed is True
    assert market.market_address == result
    assert market.onchain_market_id == 1
