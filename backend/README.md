# Backend

The `backend/` directory contains three Python packages: `api`, `worker`, and `shared`.

## Directory Layout

```
backend/
  api/            FastAPI REST service
  worker/         Async market sync and settlement worker
  shared/         Shared models, cache, and on-chain utilities
  migrations/     Alembic migration scripts
  run_tests.sh    Full backend test suite (API + shared + worker + mypy)
  run_local.sh    Local dev bootstrap
  conftest.py     Root pytest fixtures shared across services
```

## Packages

### `backend/shared`

Shared library used by both `api` and `worker`. Not a standalone service.

| Module | Purpose |
|--------|---------|
| `models.py` | Central SQLAlchemy ORM models (Market, Commitment, Settlement, etc.) |
| `repository_async.py` | Async DB accessors used by both services |
| `repository.py` | Sync DB accessors (Alembic migrations, scripts) |
| `cache_async.py` | Redis tagged cache helpers (get/set/invalidate by tag) |
| `cache_keys.py` | Canonical Redis key factories |
| `cache_stats.py` | Cache hit/miss counter helpers |
| `poseidon.py` | BN254 Poseidon hash implementation (`BATCH_SIZE=256`) |
| `merkle.py` | Merkle root and path builder (`MERKLE_DEPTH=8`) |
| `circuit_breaker.py` | Generic async circuit breaker |
| `categories.py` | Category slug normalization |
| `logging.py` | Structured JSON logger factory (`timestamp\|LEVEL\|logger\|file:line\|event\|request_id`) |
| `metrics.py` | Shared Prometheus counter helpers |
| `migrations.py` | Alembic head/current revision utilities |
| `env_presets.py` | Environment preset loader (local/dev/prod defaults) |
| `error_decoder.py` | ABI error decoding helpers |
| `async_utils.py` | Async utilities (resolve awaitable, etc.) |
| `db_metrics.py` | Per-request DB query count and timing snapshots |
| `polymarket.py` | Polymarket URL builder utilities |
| `onchain/client.py` | Web3 async client factory, account loader |
| `onchain/abi.py` | Contract ABI definitions |
| `onchain/logs.py` | On-chain event log parsing |
| `onchain/conditional_tokens.py` | Polymarket conditional token helpers |
| `indexers/goldsky.py` | Async Goldsky GraphQL client |

### `backend/api`

See [api/README.md](api/README.md).

### `backend/worker`

See [worker/README.md](worker/README.md).

## Running

```bash
make api        # postgres + redis + API service
make worker     # postgres + redis + worker service
make stack      # postgres + redis + api + worker + frontend
```

## Testing

```bash
# Full backend suite (runs from repo root via make)
make test-backend

# Directly
backend/run_tests.sh

# Individual services
make test-api
make test-worker
```

## Database Migrations

Migrations live in `backend/migrations/` and use Alembic with the psycopg2 driver (`RM_DATABASE_URL`).

```bash
cd backend/migrations && alembic upgrade head
cd backend/migrations && alembic revision --autogenerate -m "description"
```

The API and worker both run `alembic upgrade head` on startup when `RM_RUN_MIGRATIONS_ON_STARTUP=true`.

## Key Environment Variables

| Variable | Description |
|----------|-------------|
| `RM_DATABASE_URL` | PostgreSQL URL (psycopg2 driver, used by Alembic) |
| `RM_DATABASE_ASYNC_URL` | PostgreSQL URL (asyncpg driver, used at runtime; derived from `RM_DATABASE_URL` if omitted) |
| `RM_REDIS_URL` | Redis URL |
| `RM_INTERNAL_API_SECRET` | Shared secret for `/internal/*` routes |
| `RM_ENVIRONMENT` | `development` / `staging` / `production` |
