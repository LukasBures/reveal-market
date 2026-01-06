from __future__ import annotations

from app import models


class _DummyResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _AsyncClientSuccess:
    def __init__(self, payload: dict):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False

    async def get(self, *args, **kwargs):
        return _DummyResponse(self.payload)


def _seed_market(db_session, event_id: str = "evt-history"):
    market = models.Market(
        event_id=event_id,
        title="History Market",
        oracle="0xabc",
        condition_id="cond-history",
    )
    db_session.add(market)
    db_session.flush()
    db_session.add_all(
        [
            models.MarketClobToken(market_id=market.id, token_id="token-yes", side="yes"),  # noqa: S106
            models.MarketClobToken(market_id=market.id, token_id="token-no", side="no"),  # noqa: S106
        ]
    )
    db_session.commit()
    return market


def test_market_history_endpoint_returns_history(client, db_session, monkeypatch):
    market = _seed_market(db_session)
    payload = {"history": [{"t": 1700000000, "p": 0.42}, {"t": 1700003600, "p": 0.43}]}
    monkeypatch.setattr("app.routes.markets.httpx.AsyncClient", lambda *args, **kwargs: _AsyncClientSuccess(payload))

    resp = client.get(f"/markets/{market.event_id}/history?outcome=0&interval=1d")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "clob"
    assert data["history"][0]["t"] == 1700000000
    assert data["history"][0]["p"] == 0.42
