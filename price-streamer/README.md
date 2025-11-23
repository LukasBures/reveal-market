# Price Streamer

Lightweight service that ingests Polymarket prices via WebSocket (with REST fallback), applies platform economics (worsen/haircut/rake), and publishes lean per-market updates over SSE backed by Redis.

## How it works

- Connects to `STREAMER_POLYMARKET_WS_URL` and periodically polls `STREAMER_POLYMARKET_REST_URL` as a safety net.
- Normalizes outcome prices, applies worsen%, and tags each tick with FX (ZEN/USD) from the configured feed.
- Stores the latest tick per market/outcome in Redis (`STREAMER_REDIS_URL`) and publishes JSON deltas to per-market channels. Clients subscribe via `/stream?market_id=...` (SSE).
- Exposes `/health` (FX freshness) and `/metrics` (Prometheus).

## Configuration

Environment variables (prefixed `STREAMER_`):

- `REDIS_URL` – Redis connection string.
- `POLYMARKET_WS_URL` – WebSocket source for live prices.
- `POLYMARKET_REST_URL` – REST fallback for polling.
- `FX_FEED_URL` / `FX_TIMEOUT_SECONDS` / `FX_FALLBACK_PRICE` – FX oracle for ZEN/USD.
- `WORSEN_PERCENT`, `HAIRCUT_PERCENT`, `RAKE_PERCENT` – economics applied to displayed prices.
- `API_HOST` / `API_PORT` – listener settings.

See `pyproject.toml` for dependencies and `run_tests.sh` to execute the suite. In Docker, the service is built via `docker/price-streamer/Dockerfile` and wired in `docker-compose.yml` as `price_streamer`.
