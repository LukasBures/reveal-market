# Backend API

FastAPI service that exposes market data, pricing, trading, and internal ingestion endpoints.

## Directory Layout

```
backend/api/
  app/
    server.py           App factory (create_app), lifespan, middleware wiring
    config.py           Settings (pydantic-settings, RM_ prefix)
    routes/
      markets.py        /events, /categories, /resolution, /markets, /clob endpoints
      pricing.py        /pricing/* endpoints
      trade.py          /trade/commit, /trade/claim, /positions, /claim/*, /internal/commitments, /internal/settlements
      proofs.py         /proofs endpoint
      treasury.py       /treasury/snapshots endpoint
      meta.py           /, /healthz, /ready, /live, /metrics endpoints
      profiling.py      /internal/profile endpoint (optional)
    services/
      markets.py        Market enrichment, cache hydration, event response building
      heartbeat.py      Worker/API heartbeat dashboard builders
      cache_client.py   Redis and HTTP client dependency providers
      alerting.py       Background task alert webhook
      startup_validation.py  Required-secrets validation at startup
      proofs.py         Proof receipt query helpers
    tasks.py            Background loops (cache_refresh_loop, quote_sweeper_loop)
    health.py           Health response builders (deep/shallow)
    pricing.py          PricingEngine, FX quote fetcher, quote audit helpers
    cache.py            Redis client factory
    database.py         Async SQLAlchemy engine and session dependency
    crud.py             Market create/update helpers
    repository_async.py API-specific DB accessors
    schemas.py          Pydantic request/response models
    models.py           API-local SQLAlchemy models (TreasurySnapshot, etc.)
    onchain.py          Factory contract market address lookups
    security.py         SecurityHeadersMiddleware (CSP, HSTS, COOP, etc.)
    rate_limit.py       Redis-backed rate limiter and middleware
    load_shedding.py    Load shedding middleware under dependency failures
    metrics.py          Latency classification and cache context helpers
    metrics_registry.py Prometheus counter/histogram definitions
    http_middleware.py  Full middleware stack (logging, CORS, metrics, /metrics exposure)
    runtime.py          Global singletons (settings, cache_client, goldsky_client, etc.)
    logging_config.py   Structured logging setup
  tests/                pytest test suite
  pyproject.toml        uv project manifest
```

## Routes

### Public

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Service name, version, environment |
| GET | `/healthz` | Readiness probe (DB + Redis + worker + Polymarket checks) |
| GET | `/healthz/deep` | Deep health probe (cached) |
| GET | `/ready` | Kubernetes readiness probe alias for `/healthz` |
| GET | `/live` | Liveness probe (no dependency checks) |
| GET | `/healthz/heartbeats/summary` | Public redacted heartbeat summary |
| GET | `/metrics` | Prometheus metrics (exposed by prometheus-fastapi-instrumentator) |
| GET | `/events` | Paginated event/market list with status, category, and search filters |
| GET | `/events/{event_id}` | Event detail with grouped markets |
| GET | `/events/by-key/{event_key}` | Event lookup by event key |
| GET | `/events/stats` | Market status breakdown counts |
| GET | `/events/count` | Total event count (with optional status filter) |
| GET | `/events/suggest` | Typeahead search results |
| GET | `/categories/{category_slug}` | Markets filtered by category |
| GET | `/resolution/{condition_id_hex}` | Resolution summary for a condition |
| GET | `/markets/{market_id}/history` | CLOB price history for a market |
| POST | `/pricing/quote` | Generate a signed QUOTE_V1 pricing quote |
| POST | `/pricing/preview` | Unsigned pricing preview (rate-limited, 30/min per IP) |
| POST | `/pricing/submit` | Submit a signed quote for validation and recording |
| GET | `/pricing/quotes/{quote_id}` | Look up a previously issued quote by ID |
| GET | `/pricing/fx` | Current FX rate from streamer |
| POST | `/trade/commit` | Dispatch a commit transaction via the relayer |
| POST | `/trade/claim` | Initiate a claim via the relayer |
| GET | `/trade/status` | Poll relayer job status by tx hash or job ID |
| GET | `/positions` | Wallet positions (commitments and claim state) |
| GET | `/claim/bundles` | Claimable ticket bundles for a wallet |
| GET | `/claim/status` | Claim status for a wallet/market pair |
| GET | `/treasury/snapshots` | Treasury snapshots (read-only) |
| GET | `/proofs` | Proof receipts (hidden from OpenAPI schema) |

### Internal (require `X-Internal-Secret` header)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/healthz/heartbeats` | Full worker and API heartbeat dashboard |
| POST | `/internal/commitments/sync` | Ingest a mined commitment from the relayer |
| POST | `/internal/settlements/ingest` | Ingest a settlement receipt from the prover/worker |
| POST | `/internal/relayer/commitments` | Relayer webhook: commitment confirmed |
| POST | `/internal/relayer/settlements` | Relayer webhook: settlement confirmed |
| POST | `/events` | Create or upsert a market record |
| PATCH | `/events/{event_id}` | Partial update a market record |
| GET | `/internal/profile` | pstats profile dump (only when `RM_PROFILING_ENABLED=true`) |

Note: `/events/onchain` and `/clob/orderbook/{token_id}` are registered but excluded from the OpenAPI schema.

## Key Behaviors

- **Cache-aware list endpoints**: `/events` and `/categories` use Redis tagged caches. A background `cache_refresh_loop` re-hydrates every `RM_CACHE_REFRESH_INTERVAL_SECONDS` (default 120s) with a distributed lock to prevent stampede.
- **Pricing**: FX rate is pulled from `http://streamer:8100/fx/zen-usd`. Quotes are signed with an EIP-712 QUOTE_V1 digest using `RM_PRICING_SIGNER_PRIVATE_KEY`. Quote nonces are stored in Redis for replay protection.
- **Relayer circuit breaker**: Commit and claim calls use a circuit breaker (`RM_RELAYER_CIRCUIT_FAILURE_THRESHOLD=10`). When open, jobs are pushed to a Redis queue (`RM_RELAYER_QUEUE_KEY`).
- **Hedger retry queue**: Post-commit hedger calls that fail are pushed to `RM_HEDGER_QUEUE_KEY` and retried by `hedger_queue_loop`.
- **Load shedding**: In non-dev environments, `RM_LOAD_SHED_ENABLED=true` by default. Consecutive DB/cache failures shed traffic on `/events`, `/pricing/quote`, `/trade/commit`, and other listed paths.
- **Rate limiting**: Enabled by default in non-dev environments (`RM_RATE_LIMIT_ENABLED`). Default: 300 requests per 60-second window per IP.
- **Migrations on startup**: `RM_RUN_MIGRATIONS_ON_STARTUP=true` by default in non-dev presets.

## Environment Variables

All settings use the `RM_` prefix (pydantic-settings, `backend/api/app/config.py`).

### Required in production

| Variable | Description |
|----------|-------------|
| `RM_DATABASE_URL` | PostgreSQL URL (psycopg2) |
| `RM_DATABASE_ASYNC_URL` | PostgreSQL URL (asyncpg); derived from `RM_DATABASE_URL` if omitted |
| `RM_REDIS_URL` | Redis URL |
| `RM_INTERNAL_API_SECRET` | Shared secret for `/internal/*` endpoints |
| `RM_PRICING_SIGNER_PRIVATE_KEY` | Private key for QUOTE_V1 EIP-712 signing |
| `PROVER_CIRCUIT_HASH` | 0x-prefixed 32-byte circuit hash (validated at startup) |

### Important optional

| Variable | Default | Description |
|----------|---------|-------------|
| `RM_ENVIRONMENT` | `development` | Controls presets, rate limiting, load shedding defaults |
| `RM_RPC_URL` | Horizen Mainnet | EVM RPC endpoint |
| `RM_RELAYER_BASE_URL` | — | Relayer service base URL |
| `RM_RELAYER_BEARER_TOKEN` | — | Bearer token for relayer auth |
| `RM_HEDGER_BASE_URL` | — | Hedger service base URL |
| `RM_HEDGER_INTERNAL_SECRET` | — | Hedger admin endpoint secret |
| `RM_FX_FEED_URL` | `http://streamer:8100/fx/zen-usd` | FX rate source |
| `RM_CACHE_REFRESH_INTERVAL_SECONDS` | `120` | Background cache refresh interval |
| `RM_CACHE_HYDRATE_ON_STARTUP` | `true` | Hydrate markets cache on boot |
| `RM_RATE_LIMIT_ENABLED` | `true` (non-dev) | Enable Redis-backed rate limiting |
| `RM_RATE_LIMIT_REQUESTS_PER_WINDOW` | `300` | Requests allowed per window |
| `RM_RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate limit window duration |
| `RM_LOAD_SHED_ENABLED` | `true` (non-dev) | Enable load shedding |
| `RM_PROFILING_ENABLED` | `false` | Mount `/internal/profile` pstats endpoint |
| `RM_AUTHORIZATION_SIGNER_PRIVATE_KEY` | — | Private key for CommitAuth signatures |
| `RM_RELAYER_ESCROW_ADDRESS` | — | RelayerEscrow contract for balance lookups |
| `RM_TICKET_SIZE_WEI` | `100000000000000000` | Fixed ticket size for commitWithAuthorization |
| `RM_FACTORY_ADDRESS` | — | MarketFactory contract address |
| `RM_VERIFIER_ADDRESS` | — | Verifier contract address |
| `RM_GOLDSKY_SUBGRAPH_URL` | — | Goldsky GraphQL endpoint |
| `RM_GOLDSKY_API_KEY` | — | Goldsky API key |
| `RM_ALERT_WEBHOOK_URL` | — | Webhook URL for background task alerts |
| `RM_RUN_MIGRATIONS_ON_STARTUP` | `true` (non-dev) | Run Alembic migrations at boot |

## Tests

```bash
# From repo root
make test-api

# Directly
cd backend/api && uv run --project . --extra dev pytest

# Single file or pattern
cd backend/api && uv run --project . --extra dev pytest tests/test_markets.py -k "test_list"
```

The `tests/test_openapi_snapshot.py` fixture validates the OpenAPI schema hasn't changed unexpectedly. Update the snapshot file when intentionally changing route shapes.

Pytest markers: `unit`, `integration`, `slow`, `live` (requires network). All test functions must begin with `test_`.
