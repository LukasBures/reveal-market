# Reveal Market Price Streamer

FastAPI service that streams Polymarket prices via SSE with optional RTDS FX updates. It normalizes odds with worsen%, caches in Redis, and exposes lightweight endpoints for UI consumption.

## Features
- Polymarket CLOB websocket ingestion with per-market subscriptions.
- Optional RTDS crypto stream for ZEN/USD FX; REST fallback with staleness flags.
- SSE fanout (`/stream`) and per-outcome history (`/history`), cached in Redis.
- Worsen/haircut/rake applied server-side; payload signing optional.

## Requirements
- Python 3.12
- Redis 5+
- Environment variables (examples use `STREAMER_` prefix):
  - `STREAMER_REDIS_URL`
  - `STREAMER_POLYMARKET_WS_URL` / `STREAMER_POLYMARKET_REST_URL`
  - `STREAMER_WORSEN_PERCENT`, `STREAMER_HAIRCUT_PERCENT`, `STREAMER_RAKE_PERCENT`
  - `STREAMER_API_HOST`, `STREAMER_API_PORT`
  - Optional: `STREAMER_RTDS_WS_URL`, `STREAMER_RTDS_CRYPTO_SYMBOLS`, `STREAMER_SIGNING_SECRET`

## Local setup
```bash
uv sync --project price-streamer --extra dev --no-install-project
export STREAMER_REDIS_URL=redis://localhost:6379/0
uv run --project price-streamer uvicorn app.main:app --reload --port 8100
```

## Endpoints
- `GET /health` – service + feed status (stale flags, FX age).
- `GET /history?market_id=...&outcome=0&limit=100` – recent ticks.
- `GET /stream?market_id=...&assets_ids=a1,a2&symbols=zenusdt` – SSE stream; subscribes to provided asset IDs and optional RTDS symbols.

## Tests
```bash
./run_tests.sh           # uses .venv and pytest -n 4 when xdist is present
```

## Docker
```bash
docker compose build price_streamer
docker compose up price_streamer
```

## Notes
- Keep subscriptions scoped (assets_ids/symbols) to limit bandwidth.
- If the backend API is offline, SSE still serves cached/streamed prices but flags FX as stale when applicable.
