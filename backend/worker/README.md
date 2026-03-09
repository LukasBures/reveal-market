# Backend Worker

Async worker service that syncs markets from Polymarket/Gamma, maintains database state, primes caches, and drives the proof and settlement pipelines.

## Directory Layout

```
backend/worker/
  app/
    main.py             CLI entrypoint and public re-export surface
    service.py          Main orchestration loop (process_once, run_worker, publish_heartbeat)
    config.py           Settings (pydantic-settings, RM_ prefix)
    runtime.py          Global singletons (settings, polymarket_client, goldsky_client, prover client)
    database.py         Async SQLAlchemy engine and session_scope context manager
    market_sync.py      Market upserts, retention cleanup, resolution backfills
    polymarket.py       Polymarket Gamma API client and market payload normalization
    cache_ops.py        Cache tag invalidation and resolution cache write helpers
    prime.py            Cache priming for homepage, categories, and suggest endpoints
    proofs.py           Proof queue worker, settlement queue worker, proof job enqueueing
    proof_builder.py    Builds prover payload (Merkle root, commitments, public signals)
    prover_client.py    HTTP client for the prover service
    settlement.py       lockBatches, settlement job runner, chain hydration, recovery
    resolution.py       Resolution fetching (Goldsky) and persistence helpers
    backfill.py         On-chain address and parameter backfill from factory contract
    merkle.py           Re-export of shared Merkle root builder
    schema.py           Schema version sync and propagation helpers
    retry.py            Redis-backed retry state (backoff, failure counters, cooldown)
    metrics.py          Prometheus counters and gauge definitions
    healthcheck.py      Worker health probe
    logging_config.py   Structured logging setup
  tests/                pytest test suite
  pyproject.toml        uv project manifest
```

## Responsibilities

### Market Sync

- Paginates the Polymarket Gamma API (`/markets` or `/events`) with configurable filters (open-only, date window, active/archived).
- Upserts market records, outcomes, tags, CLOB token IDs, and Gamma metadata into PostgreSQL.
- Uses a distributed Redis lease (`RM_POLYMARKET_SYNC_LEASE_KEY`) to prevent multiple workers from running the same sync tick.
- Tracks an `updatedAt` cursor to avoid re-processing unchanged records.
- Enforces a database latency pacing mechanism to avoid starving the API under heavy sync load.
- Commits in configurable batches (`RM_POLYMARKET_COMMIT_BATCH_SIZE`, default 3000) with a short inter-commit sleep.

### Maintenance Loop

Runs on a separate interval (`RM_MAINTENANCE_POLL_SECONDS`, default 300s):

- **Closed-market reconcile**: Refreshes markets with commitments that are no longer in the active pagination window.
- **Factory backfill**: Fetches on-chain market addresses for records that are missing them.
- **On-chain parameter backfill**: Populates commitment parameters from chain for markets missing them.
- **Retention cleanup**: Purges resolved market records older than `RM_RESOLVED_RETENTION_SECONDS` (default 86400s).
- **Resolution gap checks**: Logs markets that have results on-chain but no resolution record in the DB.

### Proof Pipeline

`BATCH_SIZE=256`, `MERKLE_DEPTH=8` (aligned with contracts and prover).

1. `enqueue_proof_jobs`: Scans settled/locked markets and pushes pending proof jobs onto the Redis proof queue (`RM_PROOF_QUEUE_KEY`), with deduplication.
2. `run_proof_queue_worker`: Concurrent queue consumer (up to `RM_PROOF_QUEUE_MAX_CONCURRENCY`, default 2). Calls `build_prover_payload_async` to construct the Poseidon/Merkle payload, then submits to the prover service.
3. Dead-letter queue (`RM_PROOF_QUEUE_DEAD_LETTER_KEY`) for jobs that exceed `RM_PROOF_FAILURE_MAX_ATTEMPTS` or `RM_PROOF_FAILURE_MAX_AGE_SECONDS`.

### Settlement Pipeline

1. `run_settlement_jobs`: Checks markets with confirmed proofs, calls `verifyAndSettleBatched` (or `verifyAndSettle`) on-chain, and enqueues relayer claim jobs.
2. `run_settlement_queue_worker`: Concurrent queue consumer for settlement submissions.
3. `run_lock_batches_jobs`: Calls `lockBatches` for markets whose batches are ready to lock, using either direct RPC or the relayer API (`RM_LOCK_BATCHES_USE_RELAYER`).
4. Settlement recovery: Retries stale `PROCESSING` submissions after `RM_SETTLEMENT_SUBMISSION_PROCESSING_STALE_SECONDS` (default 900s).

### Cache Hydration

- After each sync tick, invalidates Redis cache tags for changed markets.
- Primes the homepage market list, category view, and suggest index via `prime_markets_cache` and `prime_featured_views`.
- Publishes a Redis heartbeat key (`RM_HEARTBEAT_KEY`) and batch stats (`RM_BATCH_STATS_KEY`) for API health checks to read.

### Startup Validation

- Validates that the prover circuit hash (`PROVER_CIRCUIT_HASH` env var) matches the hash reported by the prover service when `RM_PROVER_STARTUP_VALIDATION_ENABLED=true`.
- Runs `alembic upgrade head` when `RM_RUN_MIGRATIONS_ON_STARTUP=true`.

## Environment Variables

All settings use the `RM_` prefix (pydantic-settings, `backend/worker/app/config.py`).

### Required in production

| Variable | Description |
|----------|-------------|
| `RM_DATABASE_URL` | PostgreSQL URL (psycopg2) |
| `RM_DATABASE_ASYNC_URL` | PostgreSQL URL (asyncpg); derived from `RM_DATABASE_URL` if omitted |
| `RM_REDIS_URL` | Redis URL |
| `RM_POLYMARKET_API_BASE` | Gamma API base URL (default: `https://gamma-api.polymarket.com`) |
| `RM_PROVER_BASE_URL` | Prover service base URL |
| `RM_RPC_URL` | EVM RPC endpoint |
| `RM_SETTLEMENT_SIGNER_PRIVATE_KEY` | Oracle private key for settlement transactions |

### Important optional

| Variable | Default | Description |
|----------|---------|-------------|
| `RM_ENVIRONMENT` | `development` | Controls presets and fail-fast validation |
| `RM_POLL_INTERVAL_SECONDS` | `600` | Seconds between sync ticks |
| `RM_MAINTENANCE_POLL_SECONDS` | `300` | Seconds between maintenance ticks |
| `RM_POLYMARKET_PAGE_SIZE` | `200` | Markets per Gamma API page |
| `RM_POLYMARKET_COMMIT_BATCH_SIZE` | `3000` | Markets per DB commit batch |
| `RM_POLYMARKET_SYNC_LEASE_KEY` | `reveal_market_worker:polymarket_sync_lease` | Distributed sync lease Redis key |
| `RM_POLYMARKET_SYNC_CURSOR_KEY` | `reveal_market_worker:polymarket_sync_cursor` | Cursor checkpoint Redis key |
| `RM_PROOF_QUEUE_KEY` | `reveal_market_worker:proof_queue` | Redis list key for proof jobs |
| `RM_PROOF_QUEUE_MAX_CONCURRENCY` | `2` | Concurrent proof workers |
| `RM_PROOF_FAILURE_MAX_ATTEMPTS` | `6` | Max proof attempts before DLQ |
| `RM_SETTLEMENT_QUEUE_KEY` | `reveal_market_worker:settlement_queue` | Redis list key for settlement jobs |
| `RM_SETTLEMENT_QUEUE_MAX_CONCURRENCY` | `2` | Concurrent settlement workers |
| `RM_LOCK_BATCHES_USE_RELAYER` | `false` | Route lockBatches through relayer API |
| `RM_RELAYER_BASE_URL` | — | Relayer service base URL (required when `LOCK_BATCHES_USE_RELAYER=true`) |
| `RM_RELAYER_BEARER_TOKEN` | — | Bearer token for relayer auth |
| `RM_RELAYER_INTERNAL_SECRET` | — | Internal secret for relayer auth |
| `RM_RELAYER_PRIVATE_KEY` | — | RelayerEscrow owner key for lockBatches digest signing |
| `RM_SETTLEMENT_RPC_URL` | `RM_RPC_URL` | Optional RPC override for settlement submissions |
| `RM_PROVER_SHARED_SECRET` | — | Shared secret for prover requests |
| `PROVER_CIRCUIT_HASH` | — | 0x-prefixed circuit hash validated at startup |
| `RM_PROVER_STARTUP_VALIDATION_ENABLED` | `true` | Validate prover circuit hash on boot |
| `RM_MARKETS_CACHE_LIMIT` | `30` | Markets per cache prime page |
| `RM_MARKETS_CACHE_PRIME_PAGES` | `5` | Pages to prime on each tick |
| `RM_RESOLVED_RETENTION_SECONDS` | `86400` | Purge resolved markets older than this |
| `RM_RESOLVED_RETENTION_DRY_RUN` | `false` | Log-only retention run |
| `RM_WORKER_MOCK_MODE` | `false` | Use mock Gamma/chain for local testing |
| `RM_CLOSED_MARKETS_RECONCILE_ENABLED` | `true` | Refresh closed markets with commitments |
| `RM_FACTORY_BACKFILL_LIMIT` | `200` | Max markets to backfill per maintenance tick |
| `RM_GOLDSKY_SUBGRAPH_URL` | — | Goldsky GraphQL endpoint for resolution data |
| `RM_GOLDSKY_API_KEY` | — | Goldsky API key |
| `RM_HEARTBEAT_KEY` | `reveal_market_worker:heartbeat` | Redis heartbeat key read by API health |
| `RM_BATCH_STATS_KEY` | `reveal_market_worker:batch_stats` | Redis batch stats key |
| `RM_RUN_MIGRATIONS_ON_STARTUP` | `true` (non-dev) | Run Alembic migrations at boot |
| `RM_DB_LATENCY_PACE_ENABLED` | `true` | Slow sync when DB latency exceeds threshold |
| `RM_DB_LATENCY_PACE_MS` | `300.0` | DB latency threshold to trigger pacing |

## Tests

```bash
# From repo root
make test-worker

# Directly
cd backend/worker && uv run --project . --extra dev pytest

# Single file or pattern
cd backend/worker && uv run --project . --extra dev pytest tests/test_settlement.py -k "test_lock"
```

Pytest markers: `unit`, `integration`, `slow`, `live` (requires network). All test functions must begin with `test_`. Tests use `asyncio_mode = auto`.
