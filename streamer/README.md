# Streamer

Python/FastAPI SSE and WebSocket service for real-time market prices, FX rates, and Polymarket subgraph data.

## Responsibilities

- Connect to Polymarket CLOB WebSocket (`STREAMER_CLOB_WS_URL`) and optional RTDS feeds.
- Maintain Redis-backed price history and latest ticks per outcome.
- Serve market price streams over SSE (`/stream`) and WebSocket (`/stream/ws`).
- Serve FX (ZEN/USD) quotes and websockets at `/fx/*` and `/data/fx`.
- Expose subgraph proxy endpoints at `/subgraph/*` (aliased as `/data/subgraph/*`).
- Provide health endpoints (`/healthz`, `/healthz/deep`) and Prometheus `/metrics`.
- Provide ops and control endpoints (`/subscriptions`, `/dashboard`, `/control/subscriptions`).

## Running

```bash
# via Docker Compose (from repo root)
make streamer

# local dev
cd streamer && uv run uvicorn app.main:app --reload --port 8100
```

## Testing

```bash
cd streamer && ./run_tests.sh
```

## Endpoints

### Health

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/healthz` | `X-Ops-Secret` (if configured) | Health snapshot: FX, CLOB WS/REST, RTDS, stale markets, cache status |
| GET | `/healthz/deep` | none | Full health payload; cached for `STREAMER_HEALTH_DEEP_CACHE_TTL_SECONDS` seconds |

`/healthz` returns `status: ok | stale | degraded`.

### Metrics

| Method | Path | Description |
|--------|------|-------------|
| GET | `/metrics` | Prometheus metrics (text/plain) |

### FX

All FX endpoints return the same payload: `{ pair, zen_usd, raw_zen_usd, source, received_at, stale, age_seconds }`.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/fx/zen-usd` | ZEN/USD spot quote |
| GET | `/fx/zen-usdc` | ZEN/USDC spot quote (alias) |
| GET | `/fx/zen-usdt` | ZEN/USDT spot quote (alias) |
| GET | `/data/fx` | ZEN/USD quote (data-prefix alias) |
| WS | `/fx/zen-usd` | WebSocket ZEN/USD push feed |
| WS | `/fx/zen-usdc` | WebSocket ZEN/USDC push feed |
| WS | `/fx/zen-usdt` | WebSocket ZEN/USDT push feed |
| WS | `/data/fx/ws` | WebSocket ZEN/USD push feed (data-prefix alias) |

FX sources in priority order:
1. Primary WebSocket: `STREAMER_FX_PRIMARY_WS_URL` (default: Binance `wss://stream.binance.com:9443/ws/zenusdt@ticker`)
2. Failover WebSocket list: `STREAMER_FX_WS_URLS` (CSV)
3. REST fallback (primary): `STREAMER_FX_PRIMARY_REST_URL` (default: Binance HTTP)
4. REST fallback (secondary): `STREAMER_FX_SECONDARY_REST_URL` (default: CryptoCompare)
5. Hard fallback price: `STREAMER_FX_FALLBACK_PRICE`

The WS feed is disabled after `STREAMER_FX_MAX_CONSECUTIVE_REJECTIONS` consecutive price-rejection events. REST polling resumes automatically via `STREAMER_FX_REST_INTERVAL_SECONDS`.

### Market Streams

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/stream` | `x-access-token` | SSE market price stream for a `market_id` |
| GET | `/data/stream` | `x-access-token` | SSE stream (data-prefix alias) |
| WS | `/stream/ws` | `x-access-token` | WebSocket market price stream |
| WS | `/data/stream/ws` | `x-access-token` | WebSocket stream (data-prefix alias) |

Query params for `/stream` and `/stream/ws`:
- `market_id` (required): market to subscribe to
- `assets_ids`: comma-separated CLOB asset IDs (optional; falls back to market CLOB tokens)
- `symbols`: comma-separated RTDS symbols (optional)
- `heartbeat`: SSE/WS ping interval in seconds (default 15, max `STREAMER_MAX_CLIENT_HEARTBEAT_SECONDS`)
- `max_events` (SSE only): cap on emitted events (for testing)

Bootstrap payloads (latest cached ticks) are pushed immediately on connect before the live stream begins.

### CLOB Cache

| Method | Path | Description |
|--------|------|-------------|
| GET | `/clob/latest` | Latest cached tick for `market_id` and `outcome` |
| GET | `/data/clob/latest` | Alias |
| GET | `/clob/book` | Latest order book snapshot (`meta` channel) for `market_id` |
| GET | `/data/clob/book` | Alias |
| GET | `/history` | Price history for `market_id` and `outcome` |
| GET | `/data/clob/history` | Alias |

### Subgraph Proxy

Each endpoint has a `/subgraph/*` and a `/data/subgraph/*` alias. WebSocket variants return a single payload immediately and close.

| Method | Path | Key params |
|--------|------|------------|
| GET/WS | `/subgraph/markets` | `first`, `skip`, `ids` |
| GET/WS | `/subgraph/trades` | `asset_ids` (required), `first`, `skip`, `user` |
| GET/WS | `/subgraph/positions` | `user` (required), `asset_ids`, `first`, `skip` |
| GET/WS | `/subgraph/open-interest` | `market_id` (required), `first`, `skip` |
| GET/WS | `/subgraph/open-interest/global` | `first`, `skip` |
| GET/WS | `/subgraph/pnl` | `user` (required), `token_ids`, `first`, `skip` |
| GET/WS | `/subgraph/activity` | `user`, `condition`, `first`, `skip` |
| GET/WS | `/subgraph/market-data` | `condition`, `outcome_index`, `first`, `skip` |

Concurrent subgraph queries are limited by `STREAMER_SUBGRAPH_MAX_CONCURRENT_QUERIES` (default 25).

### Ops / Admin

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/subscriptions` | `X-Ops-Secret` | List active CLOB asset and RTDS symbol subscriptions |
| GET | `/dashboard` | `X-Ops-Secret` | FX status, subscriptions, stale markets, last published |
| GET | `/control/subscriptions` | `x-control-token` | Same as `/subscriptions` plus stale market info |
| POST | `/control/subscriptions` | `x-control-token` | Add asset/symbol subscriptions |
| DELETE | `/control/subscriptions` | `x-control-token` | Remove asset/symbol subscriptions |

`X-Ops-Secret` is required when `STREAMER_OPS_SECRET` is set (recommended in prod). `x-control-token` requires `STREAMER_CONTROL_TOKEN`.

## Access Control

| Mechanism | Header | Config var | Scope |
|-----------|--------|------------|-------|
| SSE/WS access | `x-access-token` | `STREAMER_ACCESS_TOKEN` | `/stream`, `/stream/ws`, subgraph WS, FX WS |
| Control mutations | `x-control-token` | `STREAMER_CONTROL_TOKEN` | `/control/subscriptions` |
| Ops read | `X-Ops-Secret` | `STREAMER_OPS_SECRET` | `/healthz`, `/subscriptions`, `/dashboard` |

## Rate Limiting and Connection Limits

- `STREAMER_MAX_ACTIVE_CONNECTIONS` (default 1000): process-local cap on concurrent SSE/WS connections.
- `STREAMER_MAX_CONNECTIONS_PER_CLIENT` (default 5): per-IP connection cap (0 disables).
- `STREAMER_RATE_LIMIT_PER_MINUTE` (default 0 = disabled): per-client request cap per minute.
- `STREAMER_WS_MAX_MESSAGES_PER_SECOND` (default 100): inbound WS message rate cap.

## CORS

Set `STREAMER_CORS_ALLOW_ORIGINS` to a comma-separated list of allowed origins. Wildcard `*` is rejected in production (`STREAMER_ENVIRONMENT=prod`). `STREAMER_PUBLIC_BASE_URL` must be present in the CORS list.

## Directory Structure

```
streamer/
  app/
    main.py            # FastAPI app, all route definitions, lifespan
    config.py          # Pydantic Settings (all STREAMER_* env vars)
    env_presets.py     # Environment preset resolution (local/prod)
    state.py           # StreamState: Redis cache, FX, subscriptions, history
    data_streamer.py   # CLOB WS/REST ingestion loop
    price_streamer.py  # FX WS/REST ingestion loop
    rtds_client.py     # RTDS WebSocket client
    subgraph.py        # SubgraphClient (GraphQL queries)
    subscriptions.py   # Subscription tracking helpers
    metrics.py         # Prometheus metrics definitions
    logging_utils.py   # Structured logging setup + heartbeat
    healthcheck.py     # Standalone healthcheck script
  run_tests.sh
  .env.example
```

## Environment Variables

All variables are prefixed `STREAMER_` and loaded via Pydantic Settings.

| Variable | Default | Description |
|----------|---------|-------------|
| `STREAMER_ENVIRONMENT` | `prod` | Deployment label; `prod` enforces strict CORS and ops-secret |
| `STREAMER_LOG_LEVEL` | `INFO` | Python logging level |
| `STREAMER_REDIS_URL` | `redis://redis:6379/0` | Redis connection string |
| `STREAMER_CLOB_WS_URL` | `wss://ws-subscriptions-clob.polymarket.com/ws/market` | Polymarket CLOB WebSocket |
| `STREAMER_CLOB_HOST` | `https://clob.polymarket.com` | CLOB REST host for midpoint fetches |
| `STREAMER_CLOB_REST_URL` | `https://clob.polymarket.com/markets` | CLOB REST markets URL |
| `STREAMER_RTDS_WS_URL` | `wss://ws-live-data.polymarket.com` | RTDS secondary feed URL |
| `STREAMER_RTDS_ENABLED` | `false` | Enable RTDS ingestion |
| `STREAMER_FX_PRIMARY_WS_URL` | `wss://stream.binance.com:9443/ws/zenusdt@ticker` | Primary FX WebSocket |
| `STREAMER_FX_WS_URLS` | `` | CSV list of failover FX WebSocket URLs |
| `STREAMER_FX_PRIMARY_REST_URL` | Binance ticker HTTP | Primary REST FX fallback |
| `STREAMER_FX_SECONDARY_REST_URL` | CryptoCompare | Secondary REST FX fallback |
| `STREAMER_FX_FALLBACK_PRICE` | `3.0` | Hard fallback ZEN/USD price |
| `STREAMER_FX_WS_STALE_TTL_SECONDS` | `60` | Seconds before FX WS is considered stale |
| `STREAMER_FX_MAX_AGE_SECONDS` | `60` | Max acceptable FX quote age before refresh |
| `STREAMER_FX_MAX_JUMP_PERCENT` | `20.0` | Max allowed single-tick FX price change |
| `STREAMER_FX_MAX_CONSECUTIVE_REJECTIONS` | `3` | Disable WS after this many consecutive rejections |
| `STREAMER_FX_REST_ENABLED` | `true` | Enable REST fallback when WS is stale |
| `STREAMER_FX_REST_INTERVAL_SECONDS` | `10` | Interval between REST FX refresh attempts |
| `STREAMER_PUBLIC_BASE_URL` | `https://stream.revealmarket.xyz` | Public HTTPS streamer host used by browsers |
| `STREAMER_INTERNAL_BASE_URL` | `http://streamer:8100` | Internal streamer host for server components |
| `STREAMER_PUBLIC_FAILOVER_URLS` | `` | CSV list of failover streamer URLs for multi-region |
| `STREAMER_CORS_ALLOW_ORIGINS` | (preset) | Comma-separated CORS allowed origins |
| `STREAMER_ACCESS_TOKEN` | `` | Optional token required for SSE/WS client access |
| `STREAMER_CONTROL_TOKEN` | `` | Optional token for `/control/subscriptions` mutations |
| `STREAMER_OPS_SECRET` | `` | Optional secret for `/healthz`, `/subscriptions`, `/dashboard` |
| `STREAMER_SIGNING_SECRET` | `` | Optional HMAC secret to sign payloads |
| `STREAMER_MAX_ACTIVE_CONNECTIONS` | `1000` | Process-local SSE/WS connection cap |
| `STREAMER_MAX_CONNECTIONS_PER_CLIENT` | `5` | Per-IP connection cap (0 disables) |
| `STREAMER_RATE_LIMIT_PER_MINUTE` | `0` | Per-client request cap per minute (0 disables) |
| `STREAMER_PUBLISH_THROTTLE_MS` | `300` | Throttle for Redis tick publishes (ms) |
| `STREAMER_CACHE_PREFIX` | `streamer:latest` | Redis key prefix for latest ticks |
| `STREAMER_CACHE_TTL_SECONDS` | `600` | TTL for latest tick hashes (0 disables) |
| `STREAMER_PUBSUB_PREFIX` | `streamer:stream` | Redis pubsub channel prefix |
| `STREAMER_HISTORY_PREFIX` | `streamer:history` | Redis key prefix for tick history |
| `STREAMER_HISTORY_LIMIT` | `500` | Max history entries per outcome |
| `STREAMER_HISTORY_TTL_SECONDS` | `86400` | TTL for history keys (0 disables) |
| `STREAMER_MAX_SUBSCRIPTIONS` | `200` | Maximum tracked upstream subscriptions |
| `STREAMER_MARKET_STALE_SECONDS` | `60` | Threshold to consider market data stale |
| `STREAMER_MARKET_STALE_EVICT_SECONDS` | `300` | Evict stale market tracking after this many seconds |
| `STREAMER_CACHE_SNAPSHOT_PATH` | `` | Optional JSON snapshot path for cache pre-warming on startup |
| `STREAMER_SSE_HEARTBEAT_SECONDS` | `15` | SSE heartbeat interval |
| `STREAMER_API_HOST` | `0.0.0.0` | FastAPI bind host |
| `STREAMER_API_PORT` | `8100` | FastAPI bind port |
| `STREAMER_SUBGRAPH_DEFAULT_URL` | `` | Default subgraph endpoint |
| `STREAMER_SUBGRAPH_MARKETS_URL` | Goldsky orderbook | Markets/metadata subgraph |
| `STREAMER_SUBGRAPH_TRADES_URL` | Goldsky orderbook | Trades/activity subgraph |
| `STREAMER_SUBGRAPH_ACTIVITY_URL` | Goldsky activity | Activity subgraph (splits/merges/redemptions) |
| `STREAMER_SUBGRAPH_POSITIONS_URL` | Goldsky positions | Positions/portfolio subgraph |
| `STREAMER_SUBGRAPH_OPEN_INTEREST_URL` | Goldsky OI | Open interest/TVL subgraph |
| `STREAMER_SUBGRAPH_PNL_URL` | Goldsky PnL | PnL subgraph |
| `STREAMER_SUBGRAPH_TIMEOUT_SECONDS` | `6.0` | HTTP timeout for subgraph queries |
| `STREAMER_SUBGRAPH_MAX_CONCURRENT_QUERIES` | `25` | Max concurrent subgraph queries |
