# Reveal Market Worker Service

Long-running service that keeps Postgres, Redis, and on-chain state synchronized with Polymarket. The worker is responsible for fetching markets, persisting updates, generating resolution snapshots, priming caches, emitting heartbeats, and optionally backfilling on-chain addresses/snapshots.

---

## 1. Responsibilities

| Domain | Duties |
| --- | --- |
| Data ingestion | Poll Polymarket Gamma APIs, normalize payloads (`MarketPayload`), and upsert rows using shared SQLAlchemy models. Normalized tables (`market_outcomes`, `market_tags`, `market_clob_tokens`, `market_gamma_metadata/events`, `gamma_raw`) replace legacy JSON columns. |
| Resolution tracking | Use Goldsky subgraph data to persist payout vectors in Postgres + Redis and update market status (`settled`). |
| Cache governance | Invalidate per-market cache entries, publish schema revisions, prime `/markets`, `/categories/{slug}`, `/markets/suggest`. |
| Operational signals | Publish Redis heartbeats, batch stats, Prometheus counters (`worker.*`), plus proof queue depth gauge and DLQ counter. |
| Retention | Track retention candidates and emit metrics; deletion is currently disabled (dry-run forced). |
| Commitments & Merkle | Consume commitments/settlements recorded by the API/relayer (no direct ingestion), rebuild Poseidon Merkle roots/paths for 256-ticket batches (depth 8), submit `lockBatches` when RPC + signer/relayer are configured, and keep prover payloads aligned with on-chain batch roots. |
| On-chain backfills | Backfill missing `market_address` via MarketFactory and hydrate settlement snapshots from chain when RPC/factory settings are present. |
| Proof receipts | When configured, call the `prover` microservice to mint Groth16-compatible proof receipts and cache them in Redis for downstream APIs. |

> The `prover` container emits real Groth16 receipts (`rapidsnark` + the Circom artifacts under `prover/circuits/build`) and fails hard if the artifacts are missing. Mount fresh proving/verifying keys generated via `prover/circuits/generate_keys.sh` before sharing proofs with downstream systems.

---

## Current implementation snapshot

- **Startup** – Configures logging, builds clients (Polymarket, optional CLOB, Goldsky, prover), connects to Redis, optionally runs Alembic migrations, and broadcasts schema revision to Redis.
- **Ingestion loop** – `process_once` fetches Gamma `/events` (active/non-archived defaults) with retries/backoff and rate limiting, normalizes payloads, upserts markets/outcomes/tags/clob tokens/Gamma metadata, and applies resolutions via Goldsky.
- **Cache governance** – Invalidates Redis tags for market list/detail/resolution, primes homepage/categories/suggest caches, writes schema tags, and publishes batch stats + heartbeats to Redis.
- **Resolution + proofs** – Persists payout vectors in Postgres + Redis; proof generation runs when the prover is configured (`RM_PROVER_BASE_URL`) and commitments/settlements are present; resolved markets expire from cache 12 hours after `resolved_at`.
- **Retention** – Reports metrics on resolved markets beyond `RM_RESOLVED_RETENTION_SECONDS` (deletion disabled); retention runner executes each loop.
- **On-chain backfills** – When `RM_FACTORY_ADDRESS` + `RM_RPC_URL` are configured, backfills missing `market_address` values via MarketFactory.
- **Resilience** – Redis optional for background work (bypass on outage); Polymarket sync retries with exponential backoff; runtime is async-first (asyncpg + async HTTP) with tests covering mocked external deps.

---

## Operational Notes

- Startup validates required env vars in prod-like environments (DB/Redis URLs always, Polymarket base URL, and feature-specific secrets for prover/settlement/relayer). Ensure the corresponding `RM_` envs are set before booting containers; defaults are for local only.
- The runtime is async-first end to end: asyncpg + greenlet back SQLAlchemy, CLOB/Gamma fetchers are async with configurable retries, and unit tests rely on `aiosqlite` for in-memory DBs when patching `SessionLocal`.
- Polymarket ingestion now retries with exponential backoff (`RM_POLYMARKET_SYNC_MAX_ATTEMPTS`/`RM_POLYMARKET_SYNC_RETRY_*`) so transient errors do not drop a tick; tests often override backoffs to keep runs fast.
- Resolution sync stays lean: unused change flags were removed while keeping the persisted payload + cache content identical, so heartbeats and invalidations still reflect real state changes without extra bookkeeping.
- Redis remains optional for background work; when it is unavailable the worker keeps writing to Postgres and simply skips cache writes/invalidations instead of failing the sync loop.
- Pricing quotes and signatures are handled by the API; the worker does not touch quote issuance or verification—keep API + streamer healthy for trading flows. On-chain commits are relayed via `commitOnBehalf` → `commitWithAuthorization`.

---

## 2. Architecture Overview

1. **Startup** (`app.service.run_worker`):
   - Configure logging via `app.logging_config`.
   - Build runtime clients (Polymarket, optional CLOB, Goldsky, prover) in `app.runtime`.
   - Connect to Redis (heartbeat + cache invalidation).
   - Optionally run Alembic migrations (`app.schema.ensure_schema`) and broadcast the latest revision key.
2. **Main loop**:
   - `process_once()` in `app.service`:
     - Fetch Polymarket markets (with retry) directly via the async Gamma client (`app.polymarket.AsyncPolymarketClient`).
     - For each market, `app.market_sync.sync_market()` upserts rows and calls `app.resolution.apply_resolution`.
     - Optionally backfill missing `market_address` values via MarketFactory when RPC/factory settings are present.
     - Run `cleanup_resolved_markets` to report retention candidates (deletion currently disabled).
     - Publish heartbeats, resolution cache updates, and targeted invalidations.
   - `prime_markets_cache()` warms the homepage payload.
   - `prime_featured_views()` hits `/categories` and `/markets/suggest` for “featured” cohorts.
   - `record_batch_stats()` writes batch stats JSON to Redis for dashboards.
   - Sleep for `RM_POLL_INTERVAL_SECONDS` minus loop runtime.
3. **Health**: Docker/compose call `python -m app.healthcheck` (simple DB ping) so orchestrators only start the loop when Postgres is reachable.

---

## 3. Source Layout

```
backend/worker/
├── app/
│   ├── service.py         # Async worker loop, heartbeats, orchestration
│   ├── runtime.py         # Settings + client builders (Polymarket, CLOB, Goldsky, prover)
│   ├── (fetcher removed; ingestion calls AsyncPolymarketClient directly)
│   ├── market_sync.py     # Market persistence, retention, resolution backfill
│   ├── resolution.py      # Resolution fetch/refresh and ledger upserts
│   ├── proofs.py          # Settlement proof orchestration + persistence
│   ├── proof_builder.py   # Build per-batch prover payloads from commitments/settlements
│   ├── settlement.py      # Settlement snapshots, claim payloads, tx submission
│   ├── merkle.py          # Poseidon Merkle root/path helpers (depth 8, batch size 256)
│   ├── cache_ops.py       # Cache invalidation + resolution cache writes
│   ├── prime.py           # Cache priming for homepage/categories/suggestions
│   ├── metrics.py         # Prometheus counters + cache invalidation reporting
│   ├── main.py            # Thin re-export/CLI wrapper around `run_worker`
│   ├── polymarket.py      # Gamma client + MarketPayload normalizer
│   ├── onchain.py         # Manual on-chain helpers (not wired into loop)
│   ├── backfill.py        # Market address backfill via MarketFactory
│   ├── config.py          # Pydantic settings (RM_* vars)
│   ├── healthcheck.py     # Container health entrypoint
│   └── logging_config.py  # Shared log formatter
├── tests/                 # Pytests (mocks for HTTP, Redis, on-chain)
├── pyproject.toml
├── uv.lock
├── poetry.lock
└── run.py                 # Local bootstrap (calls main.run_worker)
```

---

## 4. Configuration Cheat Sheet

All environment variables begin with `RM_`. Notable groups:

### Core runtime

| Variable | Description |
| --- | --- |
| `RM_DATABASE_URL` | Postgres DSN (same DB as the API). |
| `RM_DATABASE_POOL_SIZE`, `RM_DATABASE_MAX_OVERFLOW`, `RM_DATABASE_POOL_TIMEOUT` | SQLAlchemy pool sizing/tuning for the worker. |
| `RM_REDIS_URL` | Redis URI used for cache invalidation, schema tags, heartbeat storage. |
| `RM_POLL_INTERVAL_SECONDS` | How often to pull Polymarket (default 300s). |
| `RM_POLL_INTERVAL_JITTER_SECONDS` | Random jitter added to the sleep interval so multiple workers don’t align (default 3s). |
| `RM_RUN_MIGRATIONS_ON_STARTUP` | If true, apply Alembic migrations before syncing. |
| `RM_SCHEMA_VERSION_KEY` | Redis key where `propagate_schema_revision` stores the current Alembic revision. |
| `RM_HEARTBEAT_KEY`, `RM_HEARTBEAT_TTL_SECONDS`, `RM_HEARTBEAT_MAX_RETRIES`, `RM_HEARTBEAT_RETRY_BACKOFF_SECONDS` | Heartbeat publishing behavior. |
| `RM_BATCH_STATS_KEY`, `RM_BATCH_STATS_TTL_SECONDS` | Where batch stats live in Redis. |

### Polymarket ingestion

| Variable | Description |
| --- | --- |
| `RM_POLYMARKET_API_BASE` | Base URL for Gamma API. |
| `RM_POLYMARKET_TIMEOUT_SECONDS` | HTTP timeout per request. |
| `RM_POLYMARKET_PAGE_SIZE`, `RM_POLYMARKET_MAX_PAGES` | Pagination controls. |
| `RM_POLYMARKET_ORDER`, `RM_POLYMARKET_SORT_ASCENDING`, `RM_POLYMARKET_ONLY_OPEN_MARKETS` | Sorting/filtering toggles. |
| `RM_POLYMARKET_ACTIVE_FILTER`, `RM_POLYMARKET_ARCHIVED_FILTER` | Additional Gamma filters recommended by Polymarket; defaults to active-only, non-archived markets. |
| `RM_POLYMARKET_MAX_RETRIES`, `RM_POLYMARKET_RETRY_BACKOFF_SECONDS`, `RM_POLYMARKET_RETRY_BACKOFF_MAX_SECONDS` | Retry behavior for API calls. |
| `RM_POLYMARKET_SYNC_MAX_ATTEMPTS`, `RM_POLYMARKET_SYNC_RETRY_BACKOFF_SECONDS`, `RM_POLYMARKET_SYNC_RETRY_BACKOFF_MAX_SECONDS` | Exponential backoff applied when the entire fetch loop fails before a sync cycle completes. |
| `RM_POLYMARKET_SYNC_LEASE_KEY`, `RM_POLYMARKET_SYNC_LEASE_TTL_SECONDS`, `RM_POLYMARKET_SYNC_LEASE_JITTER_SECONDS` | Redis lease used to ensure only one worker paginates Gamma at a time; TTL + jitter reduce stampedes when multiple workers run. |
| `RM_POLYMARKET_RATE_LIMIT_REQUESTS`, `RM_POLYMARKET_RATE_LIMIT_WINDOW_SECONDS` | Sliding-window rate limiter applied before each Gamma request. |

### Cache priming

| Variable | Description |
| --- | --- |
| `RM_API_BASE_URL` | Base HTTP URL used when the worker calls the API to warm caches. |
| `RM_PRIME_MARKETS_CACHE_ENABLED` | Toggle for priming `/markets`. |
| `RM_MARKETS_CACHE_LIMIT`, `RM_MARKETS_CACHE_OFFSET`, `RM_MARKETS_CACHE_TTL_SECONDS`, `RM_CACHE_PRIME_TIMEOUT_SECONDS` | Control the warmed payload + TTL. |
| `RM_CATEGORY_CACHE_LIMIT`, `RM_SUGGEST_CACHE_LIMIT` | Limits for featured priming. |
| `RM_FEATURED_CATEGORIES`, `RM_FEATURED_SUGGEST_QUERIES` | CSV lists used for featured cache priming. |

### Retention & summarization

| Variable | Description |
| --- | --- |
| `RM_RESOLVED_RETENTION_SECONDS` | Age threshold used for retention reporting (deletion currently disabled). |
| `RM_RESOLVED_RETENTION_DRY_RUN` | Dry-run guard; retention deletions are currently forced to dry-run. |
| `RM_RESOLUTION_FETCH_MAX_ATTEMPTS`, `RM_RESOLUTION_FETCH_BACKOFF_SECONDS`, `RM_RESOLUTION_FETCH_BACKOFF_MAX_SECONDS` | Retry controls for Goldsky resolution fetches. |

### On-chain reads & backfills

| Variable | Description |
| --- | --- |
| `RM_RPC_URL` | RPC endpoint used for MarketFactory address backfills and settlement snapshot hydration. |
| `RM_FACTORY_ADDRESS` | MarketFactory address used to backfill `market_address` when missing. |

### Lock-batches automation (optional)

| Variable | Description |
| --- | --- |
| `RM_LOCK_BATCHES_USE_RELAYER` | Route lock submissions through the relayer API instead of direct RPC. |
| `RM_LOCK_BATCHES_MAX_PER_TICK` | Maximum markets to attempt locking per sync tick. |
| `RM_LOCK_BATCHES_RELAYER_POLL_SECONDS`, `RM_LOCK_BATCHES_RELAYER_MAX_ATTEMPTS` | Polling settings when the relayer queue returns a job id. |
| `RM_LOCK_BATCHES_GAS_LIMIT`, `RM_LOCK_BATCHES_GAS_PRICE_GWEI`, `RM_LOCK_BATCHES_MAX_PRIORITY_FEE_GWEI` | Gas overrides for lock-batches transactions (direct RPC mode). |

### Settlement automation (optional)

| Variable | Description |
| --- | --- |
| `RM_SETTLEMENT_SIGNER_PRIVATE_KEY` | Signer key for settlement transactions. |
| `RM_SETTLEMENT_RPC_URL` | Optional RPC override for settlement submission (defaults to `RM_RPC_URL`). |
| `RM_SETTLEMENT_GAS_PRICE_GWEI`, `RM_SETTLEMENT_MAX_PRIORITY_FEE_GWEI` | Gas overrides for settlement submission. |
| `RM_SETTLEMENT_QUEUE_KEY`, `RM_SETTLEMENT_QUEUE_POLL_SECONDS`, `RM_SETTLEMENT_QUEUE_MAX_CONCURRENCY`, `RM_SETTLEMENT_QUEUE_DEAD_LETTER_KEY` | Redis-backed queue tuning for settlement jobs. |

### Relayer claim queue (optional)

| Variable | Description |
| --- | --- |
| `RM_RELAYER_BASE_URL` | Relayer base URL used to build `/claim` payload targets. |
| `RM_RELAYER_HTTP_TIMEOUT_SECONDS` | HTTP timeout for relayer requests. |
| `RM_RELAYER_QUEUE_ENABLED` | Enable Redis-backed claim queue for relayer handoff. |
| `RM_RELAYER_QUEUE_KEY` | Redis key for relayer claim jobs. |

### Goldsky subgraph

| Variable | Description |
| --- | --- |
| `RM_GOLDSKY_SUBGRAPH_URL` | Goldsky GraphQL endpoint that indexes Horizen events. |
| `RM_GOLDSKY_API_KEY` | API key required for private Goldsky projects (leave blank for public endpoints). |
| `RM_GOLDSKY_TIMEOUT_SECONDS` | HTTP timeout for Goldsky GraphQL requests. |

### Prover integration

| Variable | Description |
| --- | --- |
| `RM_PROVER_BASE_URL` | Base URL for the `prover` container (defaults to `http://prover:8085` in docker-compose). |
| `RM_PROVER_TIMEOUT_SECONDS` | HTTP timeout when calling the prover service. |
| `RM_PROVER_SHARED_SECRET` | Optional shared secret; when set, the worker sends `X-Prover-Secret` to the prover. |
| `RM_PROOF_CACHE_PREFIX` / `RM_PROOF_CACHE_TTL_SECONDS` | Redis key namespace + TTL for cached proof receipts. |
| `RM_PROOF_QUEUE_KEY` / `RM_PROOF_QUEUE_DEDUPE_KEY` | Redis list/set used for background proof jobs so ingestion doesn’t block. |
| `RM_PROOF_QUEUE_POLL_SECONDS` | Sleep between queue polls; defaults to 1s. |
| `RM_PROOF_QUEUE_MAX_DEPTH` | Backpressure cap for proof queue length. |
| `RM_PROOF_QUEUE_MAX_CONCURRENCY` | Max concurrent proof jobs the background worker processes. |
| `RM_PROOF_QUEUE_DEAD_LETTER_KEY` | Redis list where malformed/failed proof jobs are stored for inspection. |

---

## 5. Local Development

```bash
cd backend/worker
uv sync --extra dev --no-install-project

# Copy settings and edit (Postgres/Redis typically come from `docker compose up postgres redis`)
cp ../.env.example .env.worker
export SETTINGS_FILE=.env.worker

# Run once-off sync (Ctrl+C to stop)
LOG_LEVEL=DEBUG uv run --project . python run.py

# Optional: start the prover locally (required for proof generation)
docker compose up prover
```

Tips:
- Use `docker compose up worker` when testing the full stack with the API + frontend.
- Set `RM_POLYMARKET_MAX_PAGES=1` to reduce blast radius during local iterations.
- For deterministic tests, mock HTTP with `respx` or `httpx.MockTransport`.

---

## 6. Testing & Tooling

```bash
cd backend
./run_tests.sh              # worker + api suites via uv

# Worker only
cd backend/worker
uv run --project . --extra dev pytest -q
```

The shared `./backend/run_tests.sh` wrapper enables four pytest workers per suite by default; override via `PYTEST_WORKER_COUNT=<n>` when you need more (or fewer) concurrent jobs.

Coverage highlights:
- `tests/test_polymarket_client.py`: payload normalization, pagination filters, retry/backoff behaviour.
- `tests/test_worker_process.py`: cache priming, retention metrics, heartbeats, schema propagation.
- `tests/test_merkle_and_payload.py`: Poseidon Merkle root/path construction + per-batch prover payload validation.

Pre-commit helpers:

```bash
uv run --project . --extra dev ruff check backend/worker
```

---

## 7. Observability

| Signal | Implementation |
| --- | --- |
| Logging | `logging_config.setup_logging("reveal_market.worker")` emits `timestamp | LEVEL | logger | file:line | event | request_id`. Key events: `worker.fetch.*`, `worker.persist.*`, `worker.heartbeat.*`, `worker.cache.*`, `worker.schema.*`. Use `LOG_LEVEL`, `LOG_TO_FILE`, `LOG_DIR`, `LOG_MAX_BYTES` to tune output. |
| Metrics | `RETENTION_*`, `CACHE_INVALIDATION_COUNTER`, `worker_polymarket_fetch_total`, `worker_polymarket_retry_total`, plus Prometheus counters exported by the API (worker updates hit those indirectly). If you need direct worker metrics, wrap the loop with `prometheus_client` exposition. |
| Heartbeat | Redis key `RM_HEARTBEAT_KEY` contains the timestamp, markets processed/changed, resolutions changed, latency, market_errors, and a `polymarket_ok` flag. API `/health` uses this to flag worker outages. Alert when the key is stale past `RM_HEARTBEAT_TTL_SECONDS`. |
| Batch stats | Stored at `RM_BATCH_STATS_KEY` with TTL; use `redis-cli GET reveal_market_worker:batch_stats | jq` for quick diagnostics. |

---

## 8. Deployment & Ops Checklist

1. Build image via `docker/worker/Dockerfile` or `make worker`. The Dockerfile copies migrations so `_ensure_schema` succeeds.
2. Provide runtime dependencies:
   - Same Postgres as the API.
   - Redis reachable via `RM_REDIS_URL`.
   - Optional: access to RPC endpoints when on-chain backfills or settlement automation are enabled.
3. Configure Kubernetes/Docker health check: `CMD ["python", "-m", "app.healthcheck"]`.
4. Mount secrets (RPC URLs, private keys) via secret manager or encrypted env vars—never bake them into images.
5. Scale: multiple workers are supported with the Gamma sync lease, but confirm idempotency for proof/settlement queues and cache invalidations before running more than one writer.
6. Alert on:
   - Heartbeat staleness (`timestamp` older than TTL)
   - `worker.fetch.error` spikes
   - Retention errors (`worker.retention.cleanup` missing for >N minutes)
   - Cache priming failures (`worker.cache.prime_failed`, `worker.cache.featured_failed`)
7. Keep batch stats (`RM_BATCH_STATS_KEY`) available for dashboards and alerting.

---

## 9. Runbooks (Prod)

- **Required env vars (prod)**: `RM_DATABASE_URL`, `RM_REDIS_URL`, `RM_POLYMARKET_API_BASE`, `RM_HEARTBEAT_KEY`, `RM_SCHEMA_VERSION_KEY`, `RM_PROVER_BASE_URL`, `RM_RPC_URL`, `RM_SETTLEMENT_SIGNER_PRIVATE_KEY` (plus `RM_SETTLEMENT_RPC_URL` when `RM_RPC_URL` is unset). Optional wiring: lock-batches via `RM_LOCK_BATCHES_USE_RELAYER` + `RM_RELAYER_BASE_URL`, relayer claims via `RM_RELAYER_QUEUE_ENABLED` + `RM_RELAYER_BASE_URL`. Tuning: `RM_POLYMARKET_*` (fetch/retry/rate limit), `RM_RESOLUTION_FETCH_*`, `RM_MARKETS_CACHE_*`, `RM_HEARTBEAT_*`, relayer timeouts (`RM_RELAYER_HTTP_TIMEOUT_SECONDS`), DB pool knobs `RM_DATABASE_POOL_SIZE`/`RM_DATABASE_MAX_OVERFLOW`/`RM_DATABASE_POOL_TIMEOUT`.
- **Startup (local)**: `cd backend/worker && uv sync --extra dev --no-install-project`; set `SETTINGS_FILE=.env.worker`; `LOG_LEVEL=DEBUG uv run --project . python run.py`. In Docker: `docker compose up worker` (or full stack via `./run_local.sh`).
- **Operational toggles**: relayer claims (`RM_RELAYER_QUEUE_ENABLED=true` + `RM_RELAYER_BASE_URL`), cache priming (`RM_PRIME_MARKETS_CACHE_ENABLED=true`, featured categories/queries lists).
- **Release strategy**: Prefer canary/blue-green. Ensure migrations are backward-compatible; keep `RM_RUN_MIGRATIONS_ON_STARTUP=true` so the worker applies them once then publishes schema tags. Rollback by redeploying prior image; migrations should have downgrade paths if reversal is needed.
- **Rollback**: Redeploy previous image/config; clear schema tag cache if needed (`DEL RM_SCHEMA_VERSION_KEY`); invalidate schema-tagged caches (`schema:*`) if you reverted a migration.
- **Health/alerts**: Alert on heartbeat staleness (`RM_HEARTBEAT_KEY` TTL), `worker.fetch.error`, `worker.cache.prime_failed/featured_failed`, `worker.resolution.gaps`, `worker.proof.failed`. Heartbeat payload contains `polymarket_ok`, `redis_available`, `markets_changed`, `resolutions_changed`, `latency_ms`, `market_errors`.

---

## 10. Troubleshooting

| Issue | Diagnosis steps | Resolution |
| --- | --- | --- |
| Worker loops but markets never change | Inspect logs for `worker.market.skip_update`; likely Polymarket payloads have unchanged `source_updated_at`. Force refresh by clearing `content_hash` or verifying upstream data. |
| `/health` reports missing heartbeat | Check Redis for `RM_HEARTBEAT_KEY`. If absent, ensure worker can connect to Redis and that `_run_with_retries` isn’t repeatedly failing. |
| Cache never warms | Confirm `RM_API_BASE_URL` points to the reachable API and that `RM_PRIME_MARKETS_CACHE_ENABLED=true`. Review `worker.cache.prime_failed` logs for HTTP errors. |
| Retention never deletes | Expected today: deletion is disabled and only metrics are emitted. Re-enable deletions in `cleanup_resolved_markets` (or implement archival) if you need data pruning. |
| Market address backfill missing | Look for `worker.resolution.backfill_addresses`; ensure `RM_FACTORY_ADDRESS` + `RM_RPC_URL` are set and reachable. |
---

## 11. Handy Commands

```bash
# Run a single sync then exit (useful for debugging)
python - <<'PY'
import asyncio
from app.service import process_once

asyncio.run(process_once())
PY

# Inspect heartbeat payload
redis-cli GET reveal_market_worker:heartbeat | jq

# Tail worker logs inside Docker
docker logs -f reveal-worker
```

Keep the worker lean: reuse shared helpers, avoid blocking calls inside the DB transaction, and emit structured events for every meaningful branch so operations can react quickly.
