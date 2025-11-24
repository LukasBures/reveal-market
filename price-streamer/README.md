# Reveal Market Price Streamer

FastAPI service that streams Polymarket prices via SSE with optional RTDS FX updates. It normalizes odds with worsen%, caches in Redis, and exposes lightweight endpoints for UI consumption.

## Features
- Polymarket CLOB websocket ingestion with per-market subscriptions.
- Binance ZEN/USDT websocket as primary FX (stale after 5s), with Coingecko REST fallback every 10s and jump-rejection/bounds (default 3–300 USD).
- Optional RTDS crypto stream for additional FX; REST fallback with staleness flags.
- SSE fanout (`/stream`) and per-outcome history (`/history`), cached in Redis.
- Worsen/haircut/rake applied server-side; payload signing optional.

## Requirements
- Python 3.12
- Redis 5+
- Environment variables (examples use `STREAMER_` prefix):
  - `STREAMER_REDIS_URL`
  - `STREAMER_POLYMARKET_WS_URL` / `STREAMER_POLYMARKET_REST_URL`
  - `STREAMER_WORSEN_PERCENT`, `STREAMER_HAIRCUT_PERCENT`, `STREAMER_RAKE_PERCENT`
  - `STREAMER_FX_WS_URL` (default Binance ZEN/USDT), `STREAMER_FX_REST_INTERVAL_SECONDS` (default 10), `STREAMER_FX_WS_STALE_TTL_SECONDS` (default 5), `STREAMER_FX_MAX_AGE_SECONDS` (default 60)
  - `STREAMER_API_HOST`, `STREAMER_API_PORT`
  - `STREAMER_CORS_ALLOW_ORIGINS`, `STREAMER_CORS_ALLOW_METHODS`, `STREAMER_CORS_ALLOW_HEADERS`, `STREAMER_CORS_ALLOW_CREDENTIALS` (align with your frontend origin, e.g., `http://localhost:3000` in dev)
  - Optional: `STREAMER_RTDS_WS_URL`, `STREAMER_RTDS_CRYPTO_SYMBOLS`, `STREAMER_SIGNING_SECRET`

## Local setup
```bash
uv sync --project price-streamer --extra dev --no-install-project
export STREAMER_REDIS_URL=redis://localhost:6379/0
uv run --project price-streamer uvicorn app.main:app --reload --port 8100
```

## Endpoints
- `GET /healthz` – service + feed status (stale flags, FX age).
- `GET /history?market_id=...&outcome=0&limit=100` – recent ticks.
- `GET /stream?market_id=...&assets_ids=a1,a2&symbols=zenusdt` – SSE stream; subscribes to provided asset IDs and optional RTDS symbols.
- `GET /fx/zen-usd` (and `zen-usdc`, `zen-usdt`) – latest FX snapshot (worsen% applied; raw price also returned).
- `WS /stream/ws?market_id=...` – websocket stream for market ticks (mirrors SSE); auto-subscribes to `market_id` when `assets_ids` is omitted.
- `WS /fx/zen-usd` (aliases: `/fx/zen-usdc`, `/fx/zen-usdt`) – websocket stream of ZEN/USD quotes (pushes on change, worsen% applied; raw price included).

> For TLS/WSS, front the service with Caddy/Nginx (see docker/caddy/Caddyfile for the `stream.revealmarket.xyz` setup). Locally use `ws://localhost:8100/...`; in prod use `wss://stream.revealmarket.xyz/...`.

## Tests
```bash
./run_tests.sh           # uses .venv and pytest -n 4 when xdist is present
```

## Docker
```bash
docker compose build price-streamer
docker compose up price-streamer
```

## Notes
- Keep subscriptions scoped (assets_ids/symbols) to limit bandwidth.
- If the backend API is offline, SSE still serves cached/streamed prices but flags FX as stale when applicable.
 - Container healthcheck uses `python -m app.healthcheck` to hit `/healthz`.
