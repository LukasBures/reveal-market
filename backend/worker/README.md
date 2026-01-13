# Reveal Market Worker

Async service that keeps Postgres/Redis in sync with Polymarket and primes the API caches. It runs as a single loop with Redis leases to avoid duplicate ingestion when multiple replicas are deployed.

```
Polymarket Gamma (+optional CLOB/Goldsky) --> Worker --> Postgres
                                                |          |
                                                +--> Redis (caches/heartbeats/batch stats)
                                                +--> Prover (optional)
```

## Responsibilities

- **Ingestion**: Poll Gamma `/events` with retry/backoff + rate limiting, normalize to `MarketPayload`, and upsert markets/outcomes/tags/clob tokens/Gamma metadata via shared SQLAlchemy models. Defaults to active, non-archived markets; optional CLOB enrichment hooks remain.
- **Resolutions**: Optional Goldsky client fetches payout vectors; `apply_resolution` persists to Postgres and writes resolution cache entries when configured. Resolved markets age out of cache after 12h.
- **Cache governance**: Invalidates Redis tags for list/detail/resolution keys, primes homepage/category/suggest caches through the API, writes schema revision tags, and publishes heartbeats + batch stats to Redis.
- **Proofs/settlement (optional)**: Builds Poseidon Merkle roots/paths for commitments (BATCH_SIZE=256, MERKLE_DEPTH=8), queues prover jobs to `RM_PROVER_BASE_URL`, caches receipts, and contains helpers to submit `lockBatches`/settlements when RPC + signer config exist.
- **Maintenance**: Retention reporting (deletes disabled), backfill of missing `market_address` via MarketFactory when RPC/factory are set, closed-market reconcile under a Redis lease.
- **Resilience**: Async HTTP + asyncpg; Redis is optional for background work—when down, ingestion still writes to Postgres and skips cache writes/invalidations. Sync lease prevents concurrent pagination across replicas.

## Lifecycle

1. Startup (`app.service.run_worker`): load settings, configure logging, build clients (Gamma, optional CLOB, Goldsky, prover), connect Redis, optionally run Alembic migrations, record schema revision tag, and publish initial heartbeat.
2. Main loop (`process_once`): acquire Redis lease, fetch Gamma pages, upsert markets/resolutions, backfill addresses, enqueue proof jobs, invalidate caches, prime featured caches, write batch stats, and publish heartbeat. Sleep for `RM_POLL_INTERVAL_SECONDS` minus loop runtime (with jitter).
3. Background loops: proof queue worker, settlement queue/lock-batches loop (when enabled), maintenance loop (retention/backfill), plus memory logging and batch stats emission.
4. Health: Docker uses `python -m app.healthcheck` (DB ping). Heartbeats/batch stats in Redis include latest sync timestamp for dashboards.

## Configuration (not exhaustive)

- **Core**: `RM_DATABASE_URL`, `RM_REDIS_URL`, `RM_POLL_INTERVAL_SECONDS`, `RM_POLL_INTERVAL_JITTER_SECONDS`, `RM_RUN_MIGRATIONS_ON_STARTUP`, `RM_HEARTBEAT_KEY/TTL`, `RM_BATCH_STATS_KEY/TTL`.
- **Gamma ingest**: `RM_POLYMARKET_API_BASE`, `RM_POLYMARKET_TIMEOUT_SECONDS`, `RM_POLYMARKET_PAGE_SIZE`, `RM_POLYMARKET_USE_EVENTS_ENDPOINT`, `RM_POLYMARKET_ACTIVE_FILTER`, `RM_POLYMARKET_ARCHIVED_FILTER`, `RM_POLYMARKET_ONLY_OPEN_MARKETS`, order/sort flags, retry/backoff settings, `RM_POLYMARKET_SYNC_LEASE_*`, `RM_POLYMARKET_RATE_LIMIT_*`.
- **Cache priming**: `RM_API_BASE_URL`, `RM_PRIME_MARKETS_CACHE_ENABLED`, `RM_MARKETS_CACHE_LIMIT/OFFSET/TTL`, `RM_CACHE_PRIME_TIMEOUT_SECONDS`, `RM_FEATURED_CATEGORIES`, `RM_FEATURED_SUGGEST_QUERIES`.
- **Resolutions**: `RM_GOLDSKY_SUBGRAPH_URL`, `RM_GOLDSKY_API_KEY`, `RM_RESOLUTION_FETCH_MAX_ATTEMPTS/BACKOFF_*`.
- **Proofs/settlement** (optional): `RM_PROVER_BASE_URL`, `RM_RPC_URL`, `RM_FACTORY_ADDRESS`, `RM_VERIFIER_ADDRESS`, `RM_CIRCUIT_HASH`, `RM_LOCK_BATCHES_USE_RELAYER`, `RM_SETTLEMENT_*`.
- **Retention/backfill**: `RM_RESOLVED_RETENTION_SECONDS`, `RM_RESOLVED_RETENTION_DRY_RUN` (deletes forced to dry-run), maintenance poll/lease settings, closed-market reconcile toggles.

Full defaults live in `app/config.py`.

## Running & Testing

```bash
cd backend/worker
uv sync --extra dev --no-install-project
uv run python -m app.main          # or: uv run python -m app.service

# Tests (pytest -n 4)
uv run pytest
# repo root: ./backend/run_tests.sh
```

Docker/compose: `./run_local.sh worker` (or `./run_local.sh` for the full stack).

## File Map

- `app/service.py` – main loop, heartbeats, orchestration
- `app/polymarket.py` – Gamma client + payload normalizer (tenacity retries, rate limiting)
- `app/market_sync.py` / `app/resolution.py` – persistence + resolution handling
- `app/cache_ops.py` / `app/prime.py` – cache invalidation + priming
- `app/proofs.py` / `app/proof_builder.py` – proof queue + payload assembly
- `app/settlement.py` / `app/merkle.py` – settlement snapshots, lock-batches helpers, Poseidon trees
- `app/backfill.py` – MarketFactory address backfills
- `app/runtime.py` – settings + client singletons
- `app/schema.py` – migration helpers + schema tagging
- `app/healthcheck.py` – Docker health entrypoint (DB ping)
