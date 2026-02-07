# Streamer

FastAPI SSE/WS service for real-time market prices and FX.

**Entrypoint**
- `streamer/app/main.py` builds the app and registers endpoints.

**Key responsibilities**
- Connect to CLOB WS and optional RTDS feeds.
- Maintain Redis-backed price history and latest ticks.
- Serve SSE (`/stream`) and WS (`/stream/ws`).
- Serve FX quotes at `/fx/*` and `/data/fx` plus FX websocket endpoints.
- Provide health endpoints (`/healthz`, `/healthz/deep`) and `/metrics`.
- Expose subgraph proxy APIs (`/subgraph/*`, `/data/subgraph/*`).
- Offer control endpoints for subscriptions (`/control/subscriptions`).

**Access control & limits**
- Optional access token for SSE/WS via `x-access-token` header (`STREAMER_ACCESS_TOKEN`).
- Optional control token for ops endpoints via `x-control-token` header (`STREAMER_CONTROL_TOKEN`).
- Process-local guards: `STREAMER_MAX_ACTIVE_CONNECTIONS` and `STREAMER_RATE_LIMIT_PER_MINUTE`.

**Config**
- `streamer/app/config.py` and presets in `streamer/app/env_presets.py`.
- Important: `STREAMER_PUBLIC_BASE_URL`, `STREAMER_INTERNAL_BASE_URL`, `STREAMER_CORS_ALLOW_ORIGINS`.
- In prod, wildcard CORS is rejected and `public_base_url` must be in the resolved CORS list.

**Tests**
- `streamer/run_tests.sh`
