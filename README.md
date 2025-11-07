# Reveal Market Services

This repository hosts the Reveal Market API and background worker. Both services share a common data model and can be run locally (with reloading) or in production-ready containers.

## Quick Start

```bash
cp .env.example .env
make api          # build & launch only the FastAPI service
make worker       # build & launch only the worker
make test         # run API + worker test suites with your current Python interpreter
```

During day-to-day development the local overrides enable hot reload automatically:

```bash
docker compose up
```

Need a clean rebuild of every image? Use the root helper:

```bash
./run_local.sh            # docker compose build --no-cache && docker compose up
```

For production deployments on a VPS, use the detached runner:

```bash
./run_prod.sh             # docker compose build && docker compose up -d
```

## Frontend App

The `frontend/` directory hosts a Next.js 14 application that powers:

- The main marketing surface (`https://revealmarket.xyz/`, `/about`)
- Host-aware documentation (`https://docs.revealmarket.xyz/*`)
- Future wallet-enabled trading flows (Wagmi + viem scaffold is already in place)

Local development:

```bash
cd frontend
npm install        # first run
npm run dev        # hot reload on http://localhost:3000
```

CI / smoke tests:

```bash
frontend/run_tests.sh   # runs lint + production build
```

The Docker Compose stack now exposes the frontend as the `frontend` service.

## Required Environment Variables

All runtime settings are prefixed with `RM_` and documented in `.env.example`. Key values:

| Variable | Purpose |
| --- | --- |
| `RM_DATABASE_URL` | SQLAlchemy connection string (PostgreSQL in production). |
| `RM_REDIS_URL` | Redis instance used for caching, health, and worker heartbeats. |
| `RM_POLYMARKET_API_BASE` | Base URL of the upstream Polymarket feed. |
| `RM_POLYMARKET_TIMEOUT_SECONDS` | HTTP timeout when calling Polymarket. |
| `RM_POLL_INTERVAL_SECONDS` | Worker refresh interval (seconds). |
| `RM_HEARTBEAT_KEY` / `RM_HEARTBEAT_TTL_SECONDS` | Redis key + TTL for worker liveness. |
| `RM_ENVIRONMENT` | Arbitrary label for metrics/logging (e.g., `development`, `prod`). |

Generic knobs:

| Variable | Purpose |
| --- | --- |
| `MODE` | `dev` enables auto reload + debug logging, `prod` enables multi-worker uvicorn. |
| `LOG_LEVEL` | Override default log level (`INFO`). |
| `APP_WORKERS` | Number of uvicorn workers in production mode. |
| `RM_API_BASE_URL` / `NEXT_PUBLIC_API_BASE_URL` | Base URL used by the frontend (serverside / clientside respectively) to reach the FastAPI service. |
| `DOCS_HOST` | Hostname that should render the documentation routes (default `docs.revealmarket.xyz`). |

## Observability & Operations

- `/health` – checks PostgreSQL, Redis, and Polymarket reachability.
- `/metrics` – Prometheus metrics via `prometheus-fastapi-instrumentator`.
- Worker heartbeats are published to Redis (`RM_HEARTBEAT_KEY`) with latency and last-seen timestamp.

## Deploying

1. Run `make test` locally.
2. `docker compose build` (or your orchestrator of choice).
3. Ensure the destination environment supplies the env vars above.
4. Start the services: `MODE=prod docker compose up -d`.
