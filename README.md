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

## Observability & Operations

- `/health` – checks PostgreSQL, Redis, and Polymarket reachability.
- `/metrics` – Prometheus metrics via `prometheus-fastapi-instrumentator`.
- Worker heartbeats are published to Redis (`RM_HEARTBEAT_KEY`) with latency and last-seen timestamp.

## Deploying

1. Run `make test` locally.
2. `docker compose build` (or your orchestrator of choice).
3. Ensure the destination environment supplies the env vars above.
4. Start the services: `MODE=prod docker compose up -d`.
