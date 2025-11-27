"""
Quick CLOB WS watcher for active Polymarket markets.

Usage:
    ./../.venv/bin/python app/tst.py
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Iterable

import websockets

try:
    import httpx
except Exception as exc:  # pragma: no cover - probe script
    httpx = None
    print(f"[{time.strftime('%X')}] httpx not available ({exc}); token discovery will be disabled")

CLOB_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
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


async def watch_ws(token_ids: Iterable[str]) -> None:
    assets = [str(t).strip() for t in token_ids if str(t).strip()]
    if not assets:
        print("No token ids supplied.")
        return

    attempt = 0
    while True:
        attempt += 1
        print(f"\n[{time.strftime('%X')}] connecting (attempt {attempt})… assets={assets}")
        try:
            async with websockets.connect(CLOB_WS, ping_interval=20, ping_timeout=20) as ws:
                payload = {"assets_ids": assets, "type": "market"}
                print(f"[{time.strftime('%X')}] connected, sending subscribe: {payload}")
                await ws.send(json.dumps(payload))
                msg_count = 0
                async for raw in ws:
                    msg_count += 1
                    if raw == "[]":
                        print(f"[{time.strftime('%X')}] keepalive/empty message")
                        continue
                    try:
                        data = json.loads(raw)
                    except Exception as exc:
                        print(f"[{time.strftime('%X')}] non-JSON message #{msg_count}: {raw!r} error={exc}")
                        continue
                    print(f"[{time.strftime('%X')}] msg#{msg_count} parsed type={type(data).__name__}")
                    if isinstance(data, list):
                        for idx, event in enumerate(data):
                            if isinstance(event, dict):
                                etype = event.get("event_type") or event.get("type")
                                market = event.get("market") or event.get("marketId") or event.get("id")
                                print(
                                    f"  #{msg_count}.{idx} event={etype} market={market} payload={event}"
                                )
                            else:
                                print(f"  #{msg_count}.{idx} list item: {event!r}")
                    elif isinstance(data, dict):
                        etype = data.get("event_type") or data.get("type")
                        market = data.get("market") or data.get("marketId") or data.get("id")
                        print(f"  event={etype} market={market} payload={data}")
                    else:
                        print(f"  unknown payload shape: {data!r}")
        except Exception as exc:
            print(f"[{time.strftime('%X')}] websocket dropped: {exc}; retrying in 5s")
            await asyncio.sleep(5)


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
    asyncio.run(watch_ws(TOKENS))
