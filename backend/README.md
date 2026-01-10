# Backend Services

FastAPI API + async worker that share SQLAlchemy models, caching helpers, and logging utilities under `backend/shared`. Alembic migrations live in `backend/migrations` and are used by both services. The API serves read/write traffic; the worker ingests Polymarket data, refreshes caches, and drives proofs/settlement helpers.

```
Postgres <----> API <----> Frontend/Relayer
     ^          ^
     |          |
  Worker  <----> Redis
      \         |
       \-> Polymarket + Goldsky + Prover + Streamer FX
```

## Services at a Glance

- **API (`backend/api`)** – Async FastAPI app with Redis-backed caches for markets, categories, suggestions, and resolutions; signed pricing (`/pricing/quote`), trade/commit + relayer queue fallback, claim/positions/proofs views, and Prometheus metrics/health. Lifespan runs migrations, wires security headers/CORS/trusted hosts, validates circuit hash (when configured), and starts cache refreshers + quote sweeps.
- **Worker (`backend/worker`)** – Async ingestion loop for Polymarket Gamma `/events` with retries/rate limits, optional Goldsky resolution snapshots, cache invalidation + priming, Redis heartbeats/batch stats, proof queue + settlement helpers (optional), and Redis leases around background tasks. Docker healthcheck is a Postgres ping.
- **Shared (`backend/shared`)** – Models, migrations helpers, cache utilities, logging format (`timestamp | LEVEL | logger | file:line | event | request_id`), and Poseidon batch helpers used by API and worker.

## Data Flow

1. **Ingest**: Worker paginates Gamma (active, non-archived by default), normalizes into `MarketPayload`, and upserts markets/outcomes/tags/clob tokens/Gamma metadata in Postgres. Optional: backfill `market_address` via MarketFactory and hydrate resolutions from Goldsky.
2. **Cache governance**: Worker invalidates Redis tags for list/detail/resolution and primes homepage/categories/suggest via API calls. Redis bypass is clean when unavailable.
3. **Serve**: API reads Redis first, falls back to Postgres on cache miss, and re-tags responses. Resolution caches expire 12h after `resolved_at`. Search/pagination hit Postgres directly.
4. **Pricing & trade**: `/pricing/quote` fetches FX from the streamer endpoint (ignores client FX), enforces caps, signs QUOTE_V1 digest with `RM_PRICING_SIGNER_PRIVATE_KEY`, and stores quotes. `/pricing/submit` revalidates; `/trade/commit` builds CommitAuth signatures and forwards to the relayer (Redis queue fallback). Commit cutoffs and pending/disputed flags block trading.
5. **Proofs/settlement**: Worker can enqueue proof jobs to the prover (`RM_PROVER_BASE_URL`) and persist receipts; settlement helpers assemble Poseidon batch roots (BATCH_SIZE=256, MERKLE_DEPTH=8) and optionally submit `lockBatches`/settlements when RPC + signer config are present.

## Operational Notes

- **Health**: API `/healthz` checks Postgres, Redis, worker heartbeat, Polymarket reachability, pricing signer, schema revision, and CORS/FX CORS. Worker Docker health uses `python -m app.healthcheck` (DB ping).
- **Logging/metrics**: Structured logs everywhere; Prometheus metrics at `/metrics` (HTTP/cache/rate-limit for API; ingest/cache/pricing/proof for worker). Heartbeats + batch stats stored in Redis for dashboards.
- **Migrations**: Lifespan runs Alembic by default. You can also call `python -m app.database` (API) or `app.schema.ensure_schema` (worker). Containers exit on migration failure.
- **Caching**: JSON payloads in Redis with schema + logical tags (`markets:list`, `market:{id}`, `resolution:{condition_id}`). Hydration on startup + interval; clean bypass when Redis is down to avoid tag pollution.
- **Network defaults**: Horizen Testnet (`chain id 2651420`, RPC `https://horizen-testnet.rpc.caldera.xyz/http`). Keep `RM_PRICING_CHAIN_ID`, circuit hash, and verifier addresses aligned across backend/relayer/contracts.

## Local Development

```bash
# Sync virtualenvs (uv uses pyproject + uv.lock)
uv sync --project backend/api --extra dev --no-install-project
uv sync --project backend/worker --extra dev --no-install-project

# Run tests (API + worker + shared, pytest -n 4 by default)
./backend/run_tests.sh    # or: make test
```

Run via Docker compose:

```bash
./run_local.sh api        # API only
./run_local.sh worker     # worker only
./run_local.sh            # full stack (postgres/redis/api/worker/streamer/etc.)
```

Key environment variables (see `backend/api/app/config.py` and `backend/worker/app/config.py` for full lists):

- **Core**: `RM_DATABASE_URL`, `RM_REDIS_URL`, `RM_CACHE_TTL_SECONDS`, `RM_CACHE_REFRESH_INTERVAL_SECONDS`, `RM_POLL_INTERVAL_SECONDS`.
- **Polymarket**: `RM_POLYMARKET_API_BASE`, `RM_POLYMARKET_TIMEOUT_SECONDS`, filters/order/sort toggles, retry/backoff settings.
- **Pricing/trade**: `RM_PRICING_SIGNER_PRIVATE_KEY`, `RM_PRICING_CHAIN_ID`, `RM_MAX_STAKE_ZEN`, `RM_MAX_USER_STAKE_PER_MARKET_ZEN`, `RM_MAX_MARKET_STAKE_ZEN`, `RM_RELAYER_BASE_URL`, `RM_RELAYER_QUEUE_*`, `RM_AUTHORIZATION_SIGNER_PRIVATE_KEY`.
- **Proofs/settlement**: `RM_PROVER_BASE_URL`, `RM_RPC_URL`, `RM_FACTORY_ADDRESS`, `RM_VERIFIER_ADDRESS`, `RM_CIRCUIT_HASH`, `RM_SETTLEMENT_SIGNER_PRIVATE_KEY`, `RM_LOCK_BATCHES_USE_RELAYER` (optional).
- **Cache priming**: `RM_API_BASE_URL`, `RM_PRIME_MARKETS_CACHE_ENABLED`, `RM_FEATURED_CATEGORIES`, `RM_FEATURED_SUGGEST_QUERIES`.

## Files to Know

- API: `backend/api/app/server.py` (app factory), `routes/*` (markets/pricing/trade/proofs/treasury/meta), `tasks.py` (cache refresh + quote sweeps), `health.py`, `pricing.py`, `cache.py`, `rate_limit.py`.
- Worker: `backend/worker/app/service.py` (main loop), `polymarket.py` (Gamma client), `market_sync.py` + `resolution.py`, `cache_ops.py` + `prime.py`, `proofs.py` + `proof_builder.py`, `settlement.py` + `merkle.py`, `schema.py`, `healthcheck.py`.

These READMEs stay close to the code—check the modules above when making changes so docs and behavior remain in sync.
