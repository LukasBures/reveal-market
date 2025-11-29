"""
Quick CLOB midpoint watcher using py-clob-client.

Usage:
    ./../.venv/bin/python app/tst.py
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import BookParams
except Exception as exc:  # pragma: no cover - probe script
    print("py_clob_client is missing; run with streamer/.venv active (pip install -e .[dev]).")
    raise SystemExit(exc) from exc

try:
    import httpx
except Exception as exc:  # pragma: no cover - probe script
    httpx = None
    print(f"[{time.strftime('%X')}] httpx not available ({exc}); fetch_top_market_tokens will be disabled")

CLOB_HOST = "https://clob.polymarket.com"
TOKENS: list[str] = []


def fetch_top_market_tokens(limit: int = 20) -> tuple[list[str], dict]:
    """Grab clobTokenIds for a likely-active open market (price changes topic)."""

    if not httpx:
        return [], {}
    url = "https://gamma-api.polymarket.com/markets"
    params = {"closed": "false", "limit": str(limit), "order": "-volume24hr"}
    try:
        res = httpx.get(url, params=params, timeout=10)
        res.raise_for_status()
        markets = res.json()
        if isinstance(markets, list):
            for market in markets:
                if market.get("closed") or market.get("archived"):
                    continue
                activity_hint = (
                    float(market.get("volume24hr", 0) or 0)
                    or float(market.get("bestBid", 0) or 0)
                    or float(market.get("bestAsk", 0) or 0)
                    or float(market.get("liquidityNum", 0) or 0)
                )
                if activity_hint <= 0:
                    continue
                tokens = market.get("clobTokenIds")
                parsed = json.loads(tokens) if isinstance(tokens, str) else tokens
                if isinstance(parsed, list) and parsed:
                    return [str(t) for t in parsed], market
    except Exception as exc:
        print(f"[{time.strftime('%X')}] failed to fetch top market tokens: {exc}")
    return [], {}


def watch_midpoints(token_ids: Iterable[str]) -> None:
    client = ClobClient(CLOB_HOST)
    params = [BookParams(token_id=str(t)) for t in token_ids if str(t).strip()]
    if not params:
        print("No token ids supplied.")
        return

    print(f"Monitoring {len(params)} token ids via {CLOB_HOST}: {[p.token_id for p in params]}")
    while True:
        try:
            mids = client.get_midpoints(params)
            ts = time.strftime("%X")
            print(f"[{ts}] midpoints raw={mids}")
            if not mids:
                print("  no midpoints returned; tokens may be inactive")
            for idx, token in enumerate(params):
                mid = None
                if isinstance(mids, list) and idx < len(mids):
                    mid = mids[idx]
                try:
                    last = client.get_last_trade_price(token.token_id)
                except Exception as exc:  # pragma: no cover - probe script
                    last = f"error: {exc}"
                print(f"  token={token.token_id} midpoint={mid} last_trade={last}")
        except Exception as exc:  # pragma: no cover - probe script
            print(f"[{time.strftime('%X')}] error fetching midpoints: {exc}")
        time.sleep(5)


if __name__ == "__main__":
    tokens, market = fetch_top_market_tokens(limit=20)
    if tokens:
        TOKENS = tokens
        print(
            f"Discovered active clobTokenIds: {TOKENS} "
            f"(id={market.get('id')} slug={market.get('slug')} question={market.get('question')})"
        )
    else:
        print("No token ids discovered; set TOKENS manually.")
        if not TOKENS:
            TOKENS = [
                "105104581338576429268357347529823581162598821797457643758239969314113345373365",
                "6671922635678023460317612186903727524883421159043360342126653511917319848209",
            ]
    watch_midpoints(TOKENS)
