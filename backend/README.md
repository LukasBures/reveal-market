# Reveal Market Backend

This directory contains two Python services that power the Reveal Market MVP:

- **API (`backend/api`)** – a FastAPI application that exposes market data over HTTP, applies migrations on boot, provides Prometheus metrics, and caches read-heavy endpoints in Redis.
- **Worker (`backend/worker`)** – a background process that periodically ingests markets from the Polymarket feed, writes them into PostgreSQL, invalidates relevant cache keys, and can optionally create markets on-chain via the deployed factory contract.

Both services share SQLAlchemy models, repository helpers, and logging utilities located in `backend/shared/`.

---

## Features

### API
- FastAPI with async lifespan hooks and JSON logging (`event`, `request_id`, `duration_ms`).
- Endpoints:
- `GET /` metadata
- `GET /health` checks Postgres, Redis, and Polymarket reachability
- `GET /metrics` Prometheus instrumentation (`prometheus-fastapi-instrumentator`)
- `GET /markets`, `GET /markets/stats`, `GET /markets/{id}`, `POST/PATCH /markets`
- `GET /markets/onchain` lists market addresses returned by the configured factory contract
- Responses expose `rake_bps` (basis points) so front-ends can surface protocol fees.
- Redis-backed cache for markets list, stats, and detail responses with configurable TTL (`RM_CACHE_TTL_SECONDS`).
- Alembic migrations executed on startup.

### Worker
- Periodically fetches Polymarket data (`RM_POLL_INTERVAL_SECONDS`, `RM_POLYMARKET_PAGE_SIZE`).
- Idempotent upserts into Postgres using the shared repository.
- Emits heartbeats to Redis (`RM_HEARTBEAT_KEY`, `RM_HEARTBEAT_TTL_SECONDS`) and invalidates cache namespaces.
- Optional on-chain integration (async web3.py client + retries) can create markets through `MarketFactory` when `RM_AUTO_CREATE_ONCHAIN_MARKETS` is enabled.
- Persists per-market rake overrides (`rake_bps`) so API consumers see the effective protocol fee.
- Structured logging for fetch latency, persistence batches, cache invalidation, and heartbeat status.

---

## Getting Started

### 1. Dependencies
- Python 3.13
- Poetry (1.8.x) if you want to use the local virtual environments
- Docker & Docker Compose for containerized workflows

### 2. Environment Variables

Copy `.env.example` to `.env` and adjust as needed:

```bash
cp .env.example .env
```

Key variables:

| Variable | Description |
| --- | --- |
| `MODE` | `dev` enables autoreload + debug logging; `prod` uses multi-worker uvicorn |
| `RM_DATABASE_URL` | SQLAlchemy DSN for Postgres |
| `RM_REDIS_URL` | Redis connection string |
| `RM_POLYMARKET_API_BASE` | Upstream Polymarket feed |
| `RM_POLYMARKET_TIMEOUT_SECONDS` | HTTP timeout for Polymarket requests |
| `RM_POLL_INTERVAL_SECONDS` | Worker polling interval |
| `RM_CACHE_TTL_SECONDS` | TTL for Redis-cached API responses |
| `RM_HEARTBEAT_KEY` / `RM_HEARTBEAT_TTL_SECONDS` | Worker heartbeat settings |
| `RM_RPC_URL` | RPC endpoint for Horizen/EVM interactions |
| `RM_FACTORY_ADDRESS` / `RM_VERIFIER_ADDRESS` / `RM_RAKE_MANAGER_ADDRESS` | Deployed contract addresses |
| `RM_WALLET_ADDRESS` / `RM_WALLET_PRIVATE_KEY` | Signer used for `MarketFactory.createMarket` (keep private key secret) |
| `RM_AUTO_CREATE_ONCHAIN_MARKETS` | Enable worker to push markets on-chain (default `false`) |
| `RM_DEFAULT_COMMIT_LEAD_SECONDS` / `RM_DEFAULT_REVEAL_LEAD_SECONDS` | Deadlines used when creating markets if Polymarket data is missing |
| `RM_GAS_PRICE_GWEI` / `RM_MAX_PRIORITY_FEE_GWEI` | Optional gas configuration for transactions |

All configuration classes live in `backend/api/app/config.py` and `backend/worker/app/config.py`.

---

## Running Locally

### Using Docker Compose (recommended)

```bash
docker compose up --build
```

- The base `docker-compose.yml` spins up Postgres, Redis, the API, and the worker.
- `docker-compose.override.yml` (applied automatically) mounts source code for live reload in development and sets `MODE=dev`.

Once running:
- API available at http://localhost:8000
- Prometheus metrics at http://localhost:8000/metrics
- Health endpoint at http://localhost:8000/health

### Using Make targets

```bash
make api      # only API service (compose up)
make worker   # only worker service
make test     # run unit/integration tests (requires local Python env)
make fmt      # run pre-commit hooks (black/isort/flake8)
```

### Running via Poetry (optional)

Install dependencies:

```bash
cd backend/api && poetry install --with dev
cd backend/worker && poetry install --with dev
```

Then:

```bash
# API (dev mode with reload)
cd backend/api
MODE=dev poetry run python run.py

# Worker (foreground)
cd backend/worker
MODE=dev poetry run python run.py
```

---

## Observability & Logging

- Structured JSON logs via `python-json-logger` include `timestamp`, `logger`, `level`, `event`, `request_id`, and optional fields like `cache_hit` or `duration_ms`.
- API instrumentation adds:
  - `http.request.start` / `http.request.completed`
  - `markets.list|stats|detail.cache_{hit,miss}`
  - `markets.cache.invalidate`
- Worker instrumentation adds:
  - `worker.fetch.*`, `worker.persist.batch`, `worker.heartbeat.*`, `worker.cache.invalidate`
- On-chain operations emit `worker.tx.*` events (submitted/mined/failed) and configuration issues surface as `worker.onchain.*` logs.
- Cache helpers emit `cache.*` events if Redis operations fail.
- Prometheus metrics exposed on `/metrics`.

---

## Testing

```bash
make test
```

or manually:

```bash
cd backend/api
PYTHONPATH=.. poetry run pytest

cd ../worker
PYTHONPATH=.. poetry run pytest
```

Tests use SQLite + in-memory Redis stubs so nothing external is required. They cover:
- API endpoint caching semantics and logging events.
- Worker processing loop (DB upsert, heartbeat, cache invalidation).
- Smoke test for `/health` and `/metrics`.

---

## Deployment Notes

- Both Dockerfiles use multi-stage builds to export Poetry dependencies and install via `pip --no-cache-dir`. Runtime images run as non-root users.
- Configuration is driven entirely via environment variables.
- Ensure migrations run (automatically triggered by the API lifespan) before serving live traffic.
- For production, set `MODE=prod`, tighten TTLs/environment configuration, and consider long-term metrics storage and log aggregation.
