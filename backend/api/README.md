# Reveal Market API

Async FastAPI service that exposes market discovery, resolution summaries, signed pricing, commit/claim helpers, and Prometheus/health endpoints. It shares models and caching utilities with the worker and uses Redis JSON caches to keep common payloads hot.

```
Clients -> FastAPI -> Redis (caches/heartbeats) -> Postgres (source of truth)
                     \-> Streamer FX         \-> Relayer (commit/claim)
```

## How it’s built

- **App factory**: `app.server.create_app()` wires middleware (request-id/logging, Prometheus, CORS/trusted hosts, optional rate limiting, security headers), runs startup tasks (migrations, schema tag, cache hydrate, quote sweeper, relayer queue start, circuit-hash validation when configured), and registers routers.
- **Async stack**: async SQLAlchemy + asyncpg, redis.asyncio, httpx, and background loops (`cache_refresh_loop`, `quote_sweeper_loop`, `metrics_publisher_loop`) managed by the FastAPI lifespan.
- **Caching**: Redis JSON caches for market list/detail, categories, suggestions, and resolutions with schema + logical tags. Cold misses fall back to Postgres and write-through to Redis; Redis downtime bypasses cache without polluting tags. Startup + interval hydrators keep hot payloads warm.
- **Logging/metrics**: Structured logs (`timestamp | LEVEL | logger | file:line | event | request_id`) and Prometheus metrics for HTTP, cache hit/miss, rate limits, and quote issuance; API heartbeats stored in Redis for dashboards.
- **Security**: TrustedHost + CORS + CSP/HSTS/COOP middleware, optional rate limiting, and bearer token hooks for relayer ingestion. Liveness at `/live`, readiness at `/ready` and `/healthz`.

## Responsibilities

- **Markets/resolutions**: `/markets`, `/categories/{slug}`, `/markets/suggest`, `/markets/{event_id}`, `/resolution/{condition_id}` pull from normalized tables (outcomes, tags, clob tokens, Gamma metadata). Resolved markets drop from cache 12h after `resolved_at`.
- **Search**: Indexed Postgres queries for full-text search and pagination (intentionally not cached).
- **Pricing**: `/pricing/preview` (unsigned) and `/pricing/quote` (signed QUOTE_V1 digest) fetch FX from the streamer endpoint, ignore client-supplied FX, enforce per-quote/user/market caps, and persist quotes with expiry. `/pricing/submit` revalidates digest/expiry and optional FX drift.
- **Trade/relayer**: `/trade/commit` consumes a quote, builds CommitAuth signatures, and forwards to the relayer (Redis queue fallback). `/trade/status` polls queue results; `/trade/claim` + `/claim/bundles` surface settlement/claim state; `/positions` returns user positions and escrow balance when available.
- **Proofs/treasury/meta**: `/proofs` exposes prover receipts stored by the worker; treasury/meta routes provide version/config metadata.
- **Health**: `/healthz` checks Postgres, Redis, worker heartbeat, Polymarket reachability, pricing signer, schema revision tag, and CORS/FX CORS. `/metrics` exposes Prometheus counters/gauges/histograms.

## Configuration (common vars)

See `app/config.py` for defaults. Key groups:

- **Core**: `RM_DATABASE_URL`, `RM_REDIS_URL`, `RM_CACHE_TTL_SECONDS`, `RM_CACHE_HYDRATE_ON_STARTUP`, `RM_CACHE_REFRESH_ENABLED`, `RM_CACHE_REFRESH_INTERVAL_SECONDS`, `RM_CACHE_REFRESH_LIMIT`, `RM_CACHE_HYDRATE_LIMIT`, `RM_SCHEMA_VERSION_KEY`.
- **Security**: `RM_ALLOWED_HOSTS`, `RM_CORS_ALLOW_ORIGINS/METHODS/HEADERS/CREDENTIALS`, `RM_ENABLE_SECURITY_HEADERS`.
- **Pricing/FX**: `RM_PRICING_SIGNER_PRIVATE_KEY`, `PRICING_SIGNER_ADDRESS`, `RM_PRICING_CHAIN_ID`, `RM_MAX_STAKE_ZEN`, `RM_MAX_USER_STAKE_PER_MARKET_ZEN`, `RM_MAX_MARKET_STAKE_ZEN`. FX is fetched server-side from the streamer (endpoint hard-pinned in `app.pricing`).
- **Trade/relayer**: `RM_AUTHORIZATION_SIGNER_PRIVATE_KEY`, `RM_AUTHORIZATION_SIGNER`, `RM_RELAYER_BASE_URL`, `RM_RELAYER_BEARER_TOKEN`, `RM_RELAYER_QUEUE_ENABLED`, `RM_RELAYER_QUEUE_KEY`, `RM_RELAYER_QUEUE_MAX_ATTEMPTS`, `RM_RELAYER_QUEUE_RESULT_TTL_SECONDS`, `RM_RELAYER_WEBHOOK_SECRET`, `RM_TICKET_SIZE_WEI`, `RM_COMMIT_NONCE_TTL_SECONDS`, `RM_RELAYER_ESCROW_ADDRESS`.
- **Polymarket/on-chain**: `RM_POLYMARKET_API_BASE`, `RM_POLYMARKET_TIMEOUT_SECONDS`, order/sort/active/archive filters; optional `RM_RPC_URL`, `RM_FACTORY_ADDRESS`, `RM_MARKET_IMPLEMENTATION_ADDRESS`, `RM_RAKE_MANAGER_ADDRESS`, `RM_VERIFIER_ADDRESS`, `RM_CIRCUIT_HASH` for verifier validation and on-chain helpers.
- **Rate limit**: `RM_RATE_LIMIT_REQUESTS`, `RM_RATE_LIMIT_WINDOW_SECONDS`, `RM_TRUSTED_PROXIES` (disabled when requests==0).

## Running & Testing

```bash
cd backend/api
uv sync --extra dev --no-install-project
uv run uvicorn app.server:app --reload --port 8000

# Tests (pytest -n 4 by default)
uv run pytest
# or from repo root: ./backend/run_tests.sh
```

Docker/compose: `./run_local.sh api` builds and runs the container with Postgres/Redis.

## File Map

- `app/server.py` – app factory + lifespan + middleware wiring
- `app/routes/` – routers for markets, pricing, trade, proofs, treasury, meta
- `app/tasks.py` – cache refresh loop, quote sweeper, schema tagging, API heartbeat
- `app/pricing.py` – FX fetch + QUOTE_V1 digest/signing helpers
- `app/cache.py` / `app/services/cache_client.py` – Redis JSON helper + tag metadata
- `app/health.py` – dependency checks for `/healthz`
- `app/http_middleware.py` / `app/rate_limit.py` / `app/security.py` – logging, Prometheus, CORS/headers, rate limiting
- `app/repository_async.py` / `app/crud.py` – async Postgres queries
- `tests/` – async pytest suite (Redis/DB mocked or ephemeral)
