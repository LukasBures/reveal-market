# Streamer

FastAPI SSE/WS service for real-time market prices and FX.

**Entrypoint**
- `streamer/app/main.py` builds the app and registers endpoints.

**Key responsibilities**
- Connect to CLOB WS and RTDS feeds.
- Maintain Redis-backed price history.
- Serve SSE (`/stream`) and WS (`/stream/ws`).
- Serve FX quotes at `/fx/*` and `/data/fx`.
- Provide health endpoints (`/healthz`, `/healthz/deep`).

**Config**
- `streamer/app/config.py` and presets in `streamer/app/env_presets.py`.
- Important: `STREAMER_PUBLIC_BASE_URL`, `STREAMER_INTERNAL_BASE_URL`, `STREAMER_CORS_ALLOW_ORIGINS`.

**Tests**
- `streamer/run_tests.sh`
