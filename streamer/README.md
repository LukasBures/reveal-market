# Reveal Market Streamer

FastAPI service that streams Polymarket CLOB ticks/books and ZEN/USD FX over SSE/WS, with Redis-backed caching/history and Goldsky subgraph proxies. Two workers run in-process: `DataStreamer` (markets) and `PriceStreamer` (FX).

```
Polymarket WS/REST + RTDS -> DataStreamer -> Redis (cache/pubsub/history) -> SSE/WS (/stream)
Binance WS/REST (+CryptoCompare) -> PriceStreamer -> Redis -> SSE/WS (/fx/*)
Goldsky subgraphs -> HTTP/WS proxies under /subgraph/*
```

## Architecture

- **Preset resolution**: `RM_ENVIRONMENT=local|prod` picks preset hosts/CORS from `app/env_presets.py` and overrides `STREAMER_PUBLIC_BASE_URL`, `STREAMER_INTERNAL_BASE_URL`, and CORS allowlists. Prod mode disallows wildcard CORS.
- **State**: `StreamState` tracks Redis connections, cache/history handles, active connections/subscriptions, and FX/cache staleness. Asset refcounts ensure upstream WS subscriptions are dropped when no clients are listening.
- **DataStreamer**: CLOB WS ingest + periodic REST poll (optional RTDS topic) with throttled publish/dedupe. Caches latest ticks/books in Redis hashes, publishes to Redis pubsub, and maintains bounded history (`STREAMER_HISTORY_LIMIT`/`TTL`). Placeholders are swapped for concrete `clobTokenIds` once REST discovery resolves them.
- **PriceStreamer**: Single FX WS (Binance) with staleness guard; REST fallback to Binance then CryptoCompare with jump bounds. Gauges emit source/staleness; responses include `stale=true` when applicable.
- **Proxies**: Goldsky subgraph HTTP/WS proxies for markets/trades/activity/positions/open-interest/pnl; URLs configurable per domain or via `STREAMER_SUBGRAPH_DEFAULT_URL`.
- **Access/controls**: Optional bearer-style `STREAMER_ACCESS_TOKEN` for `/stream`/`/stream/ws`, `STREAMER_CONTROL_TOKEN` for subscription control routes, rate limiting (`STREAMER_RATE_LIMIT_PER_MINUTE`), max subscriptions (`STREAMER_MAX_SUBSCRIPTIONS`), and max active connections (`STREAMER_MAX_ACTIVE_CONNECTIONS`).

## Endpoints

- `GET /healthz` – FX/market staleness, source info, connection counts. Docker health uses `python -m app.healthcheck`.
- `GET /dashboard` – snapshot of subscriptions, last-seen timestamps, stale lists.
- `GET /subscriptions` – list current asset/symbol subscriptions.
- `GET/POST/DELETE /control/subscriptions` – inspect/add/remove subscriptions (requires `x-control-token` when enabled).
- **Streaming**: `GET /stream` (SSE) and `WS /stream/ws` for market ticks/books/trades/history. Params: `market_id`, optional `assets_ids` (preferred), `symbols` (RTDS), `max_events` (SSE only). Optional `x-access-token` when enabled.
- **History/cache**: `GET /history` (recent ticks), `GET /clob/latest`, `GET /clob/book` for cached payloads.
- **FX**: `GET /fx/zen-usd|zen-usdc|zen-usdt` (HTTP), `WS /fx/zen-usd` (+ aliases) for streaming FX (includes worsen% and raw price). `STREAMER_WORSEN_PERCENT` applied server-side; haircut/rake are config placeholders only.
- **Subgraph proxies**: HTTP under `/subgraph/{markets,trades,positions,open-interest,open-interest/global,pnl,activity,market-data}`; WS mirrors under `/subgraph/ws/*`. Aliased under `/data/subgraph/*`; CLOB cache/history under `/data/clob/*`; FX WS under `/data/fx/ws`; SSE stream under `/data/stream`.
- **Metrics**: `GET /metrics` – Prometheus (FX source/staleness, WS health, tick counts, deliveries/drops, ingest drops, staleness gauges).

## Configuration Highlights

Defaults live in `app/config.py`:

- **Core**: `STREAMER_REDIS_URL`, `STREAMER_API_HOST/PORT`.
- **Polymarket**: `STREAMER_CLOB_WS_URL`, `STREAMER_CLOB_REST_URL`, `STREAMER_CLOB_HOST`, `STREAMER_RTDS_ENABLED`, `STREAMER_RTDS_WS_URL`, `STREAMER_RTDS_PING_SECONDS`, `STREAMER_REST_POLL_SECONDS`, `STREAMER_WS_RECONNECT_SECONDS`, `STREAMER_MARKET_STALE_SECONDS`, `STREAMER_MARKET_STALE_EVICT_SECONDS`, `STREAMER_PUBLISH_THROTTLE_MS`.
- **FX**: `STREAMER_FX_PRIMARY_WS_URL`, `STREAMER_FX_PRIMARY_REST_URL`, `STREAMER_FX_SECONDARY_REST_URL`, `STREAMER_FX_REST_INTERVAL_SECONDS`, `STREAMER_FX_WS_STALE_TTL_SECONDS`, `STREAMER_FX_MAX_AGE_SECONDS`, `STREAMER_FX_MAX_JUMP_PERCENT`, `STREAMER_FX_JUMP_WINDOW_SECONDS`, `STREAMER_FX_MIN_PRICE/MAX_PRICE`, `STREAMER_FX_MAX_CONSECUTIVE_REJECTIONS`, `STREAMER_PUBLISH_WHEN_FX_STALE`.
- **History/cache**: `STREAMER_HISTORY_LIMIT`, `STREAMER_HISTORY_TTL_SECONDS`, `STREAMER_HISTORY_DEBOUNCE_SECONDS`.
- **Access/ops**: `STREAMER_ACCESS_TOKEN`, `STREAMER_CONTROL_TOKEN`, `STREAMER_SIGNING_SECRET` (HMAC over payloads), `STREAMER_MAX_SUBSCRIPTIONS`, `STREAMER_MAX_ACTIVE_CONNECTIONS`, `STREAMER_RATE_LIMIT_PER_MINUTE`.
- **Subgraphs**: `STREAMER_SUBGRAPH_DEFAULT_URL` or specific URLs per domain (`STREAMER_SUBGRAPH_MARKETS_URL`, etc.).
- **Hosts/CORS**: `STREAMER_PUBLIC_BASE_URL`, `STREAMER_INTERNAL_BASE_URL`, `STREAMER_CORS_ALLOW_ORIGINS/METHODS/HEADERS/CREDENTIALS`. Presets union local + prod origins to avoid mismatches.

## Running & Testing

```bash
cd streamer
uv sync --extra dev --no-install-project
export STREAMER_REDIS_URL=redis://localhost:6379/0
uv run uvicorn app.main:app --reload --port 8100

./run_tests.sh    # pytest, mocks Redis/HTTP
```

Docker: `docker compose up streamer` (Redis included in compose). Healthcheck uses `python -m app.healthcheck`.

## Client Tips

- Prefer passing `assets_ids` (`clobTokenIds`) to `/stream`/`/stream/ws`; placeholder `market_id` subscriptions are slower and replaced once REST discovers token IDs.
- FX streams include `stale` flags; set `STREAMER_PUBLISH_WHEN_FX_STALE=false` to pause publishes until FX is fresh.
- When `STREAMER_SIGNING_SECRET` is set, payloads include `sig` (HMAC-SHA256 over sorted key/value pairs excluding `sig`). Verify client-side for tamper detection.

## File Map

- `app/main.py` – app factory, presets/CORS resolution, routes, rate limiting, access/connection caps.
- `app/state.py` – shared runtime state + Redis helpers.
- `app/data_streamer.py` – CLOB WS/REST/RTDS ingest, cache/history publishing, throttling.
- `app/price_streamer.py` – FX WS + REST failover, staleness guards.
- `app/subgraph.py` – HTTP/WS proxy to Goldsky subgraphs.
- `app/env_presets.py` – local/prod host + CORS presets.
- `app/healthcheck.py` – Docker health probe.
