# Reveal Market Streamer

FastAPI service that streams Polymarket market data plus ZEN/USD FX over SSE/WS. It keeps odds up to date via CLOB WS + RTDS, pulls FX from Binance (WS first, REST fallbacks), applies worsen%/haircut/rake, caches in Redis, and republishes to frontend clients.

## Features
- Polymarket CLOB websocket ingestion with per-market subscriptions and asset refcounts; unsubscribes upstream when the last client disconnects.
- FX failover order (no RTDS for FX): Binance WS → Binance REST → CryptoCompare REST with jump/bounds guards and automatic WS reattempts.
- RTDS only for market data (Polymarket `clob_market` topic); subscriptions mirror current asset IDs and keep a 5s ping cadence.
- SSE/WS fanout (`/stream`) and per-outcome history (`/history`), cached in Redis and signed optionally.
- Worsen/haircut/rake applied server-side; structured logs at INFO clearly state which data source is used (ws/rest) and why a fallback was chosen.
- Connection pooling: one WS per path is shared across subscribers, with periodic HTTP refresh to rehydrate stale data and automatic reconnect to WS.
- Network defaults: frontend consumers target Horizen Testnet by default (chain id `2651420`). Align CORS origins and streamer host with your frontend origin (e.g., `https://revealmarket.xyz`), and keep pricing chain/env vars in sync across services. The API now assumes the streamer is reachable at `/fx/zen-usd`; update host/port in `backend/api/app/pricing.py` if you change it.
  - Presets: `MODE=local` uses `http://localhost:8100` + localhost CORS; `MODE=prod` pins `https://stream.revealmarket.xyz` + prod CORS union into middleware so both local + prod origins are allowed without extra overrides. Wildcard CORS is disallowed in prod.

## Requirements
- Python 3.12
- Redis 5+
- Environment variables (examples use `STREAMER_` prefix; see `.env.example`):
  - Core: `STREAMER_REDIS_URL`, `STREAMER_API_HOST`, `STREAMER_API_PORT`
  - Polymarket: `STREAMER_POLYMARKET_WS_URL`, `STREAMER_POLYMARKET_REST_URL`, `STREAMER_RTDS_WS_URL`
  - FX: `STREAMER_FX_PRIMARY_WS_URL`, `STREAMER_FX_PRIMARY_REST_URL`, `STREAMER_FX_SECONDARY_REST_URL`, `STREAMER_FX_REST_INTERVAL_SECONDS`, `STREAMER_FX_WS_STALE_TTL_SECONDS`, `STREAMER_FX_MAX_AGE_SECONDS`
  - Pricing: `STREAMER_WORSEN_PERCENT`, `STREAMER_HAIRCUT_PERCENT`, `STREAMER_RAKE_PERCENT`
- Hosts/CORS: `STREAMER_PUBLIC_BASE_URL`, `STREAMER_INTERNAL_BASE_URL`, `STREAMER_CORS_ALLOW_ORIGINS`, `STREAMER_CORS_ALLOW_METHODS`, `STREAMER_CORS_ALLOW_HEADERS`, `STREAMER_CORS_ALLOW_CREDENTIALS`
- Stream limits: `STREAMER_PUBLISH_THROTTLE_MS`, `STREAMER_HISTORY_LIMIT`, `STREAMER_HISTORY_TTL_SECONDS`, `STREAMER_HISTORY_DEBOUNCE_SECONDS`, `STREAMER_MAX_SUBSCRIPTIONS`, `STREAMER_MAX_ACTIVE_CONNECTIONS`, `STREAMER_RATE_LIMIT_PER_MINUTE`
- Access/ops: `STREAMER_ACCESS_TOKEN`, `STREAMER_CONTROL_TOKEN`, `STREAMER_SIGNING_SECRET`

## Local setup
```bash
uv sync --project streamer --extra dev --no-install-project
export STREAMER_REDIS_URL=redis://localhost:6379/0
uv run --project streamer uvicorn app.main:app --reload --port 8100
```

## Endpoints
- `GET /healthz` – service + feed status (stale flags, FX age).
- `GET /dashboard` – subscriptions, last-seen/published timestamps, FX status, and stale market list for quick ops checks.
- `GET /history?market_id=...&outcome=0&limit=100` – recent ticks.
- `GET /stream?market_id=...&assets_ids=a1,a2&symbols=zenusdt` – SSE stream; subscribes to provided asset IDs and optional RTDS symbols.
- `GET /fx/zen-usd` (and `zen-usdc`, `zen-usdt`) – latest FX snapshot (worsen% applied; raw price also returned).
- `WS /stream/ws?market_id=...` – websocket stream for market ticks (mirrors SSE); auto-subscribes to `market_id` when `assets_ids` is omitted.
- `WS /fx/zen-usd` (aliases: `/fx/zen-usdc`, `/fx/zen-usdt`) – websocket stream of ZEN/USD quotes (pushes on change, worsen% applied; raw price included).

> For TLS/WSS, front the service with Caddy/Nginx (see docker/caddy/Caddyfile for the `stream.revealmarket.xyz` setup). Use `wss://stream.revealmarket.xyz/...` everywhere (map the host locally so WSS works in dev).

### Client expectations
- Prefer WS/WSS first (`/fx/zen-usdc`), let the client fall back to HTTP if WS is stale, and auto-attempt WS again after a few HTTP fallbacks.
- Dev/Prod: `wss://stream.revealmarket.xyz/fx/zen-usdc` (via your local TLS proxy/hosts entry).
- For market streams, fetch `clobTokenIds` from your market-detail API and pass them in `assets_ids` when opening `/stream` or `/stream/ws` (e.g., `assets_ids=<yes_id>,<no_id>`). This is the fastest path to live CLOB ticks/books. Only omit `assets_ids` as a fallback; the streamer will temporarily use the `market_id` placeholder until REST polling reveals the real token ids, which is slower.
- If you set `STREAMER_SIGNING_SECRET`, every payload cached/published will include `sig` (HMAC-SHA256 over sorted key/value pairs). Example client verification (Python):

```python
import hmac
import hashlib

def verify(payload: dict, secret: str) -> bool:
    message = "|".join(f"{k}:{payload[k]}" for k in sorted(payload.keys()) if k != "sig")
    expected = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, payload.get("sig", ""))
```

### Minimal client examples

SSE (Python):
```python
import requests

def stream_sse(market_id: str, assets_ids: list[str] | None = None, token: str | None = None):
    params = {"market_id": market_id}
    if assets_ids:
        params["assets_ids"] = ",".join(assets_ids)
    headers = {"x-access-token": token} if token else {}
    with requests.get("http://localhost:8100/stream", params=params, headers=headers, stream=True) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            if line.startswith(b"event: ping"):
                continue  # heartbeat
            if line.startswith(b"data: "):
                payload = line.replace(b"data: ", b"").decode()
                print(payload)
```

WebSocket (Python, with reconnect + fallback to HTTP on failure):
```python
import asyncio, json, websockets, requests

async def stream_ws(market_id: str, assets_ids=None, token=None):
    params = {"market_id": market_id}
    if assets_ids:
        params["assets_ids"] = ",".join(assets_ids)
    qs = "&".join([f"{k}={v}" for k,v in params.items()])
    headers = {"x-access-token": token} if token else {}
    url = f"ws://localhost:8100/stream/ws?{qs}"
    try:
        async with websockets.connect(url, extra_headers=headers, ping_interval=15) as ws:
            async for msg in ws:
                if "ping" in msg:
                    continue
                print(msg)
    except Exception as exc:
        # WS failed; fall back to one-shot HTTP for resilience, then retry WS later.
        print(f"WS failed ({exc}), falling back to HTTP")
        http = requests.get("http://localhost:8100/stream", params={**params, "max_events": 1}, headers=headers, stream=True)
        for line in http.iter_lines():
            if line.startswith(b"data: "):
                print(line.replace(b"data: ", b"").decode())
        await asyncio.sleep(5)
        await stream_ws(market_id, assets_ids, token)

asyncio.run(stream_ws("m1", assets_ids=["yes_id","no_id"]))
```

## Tests
```bash
./run_tests.sh           # uses .venv and pytest -n 4 when xdist is present
```

## Docker
```bash
docker compose build streamer
docker compose up streamer
```

The bundled `docker-compose.yml` includes Redis and exposes `8100`; healthcheck uses `python -m app.healthcheck`. Resource limits (CPU/memory) are set on the streamer container; adjust as needed.

## Notes
- Keep subscriptions scoped (assets_ids/symbols) to limit bandwidth.
- If the backend API is offline, SSE still serves cached/streamed prices but flags FX as stale when applicable.
- Container healthcheck uses `python -m app.healthcheck` to hit `/healthz`.
- Frontend consumers default to Horizen Testnet (chain id `2651420`); align CORS origins/hosts and pricing chain envs when pointing at a different network.
- Prometheus: gauges/counters expose FX source/staleness plus stream deliveries/dropped events and per-market staleness (`/metrics`). Watch for `streamer.host.mismatch`/`cors.origins.missing` logs when hosts or CORS config diverge from frontend/API origins.
- History is bounded by `STREAMER_HISTORY_LIMIT` (entries) and `STREAMER_HISTORY_TTL_SECONDS` (expiration). Set `STREAMER_HISTORY_DEBOUNCE_SECONDS` to avoid storing duplicate history entries too frequently; cache/publish still occurs even when history is debounced.
- Subscriptions respect `STREAMER_MAX_SUBSCRIPTIONS`; when the cap is hit, new assets are rejected with a `stream.assets.cap` warning so upstream WS connections stay bounded.
- Control API: set `STREAMER_CONTROL_TOKEN` to enable `/control/subscriptions` (GET to inspect assets/symbols/staleness; POST to add assets/symbols; DELETE to force-remove). Provide `x-control-token` header with the configured token; calls are rejected otherwise.
- Access gating: set `STREAMER_ACCESS_TOKEN` to require `x-access-token` on `/stream` and `/stream/ws`; set `STREAMER_MAX_ACTIVE_CONNECTIONS` to cap concurrent SSE/WS connections (HTTP 429 on overflow).
- Optional per-client rate limiting: set `STREAMER_RATE_LIMIT_PER_MINUTE` to cap requests/connections per IP; `0` disables.
