# Reveal Market Worker Service

The worker ingests Polymarket + on-chain data, manages heartbeats, refreshes caches, and can optionally originate on-chain markets via MarketFactory. It shares models/utilities with the API but runs as an independent async loop.

## Highlights

- **End-to-end migrations** – When `RM_RUN_MIGRATIONS_ON_STARTUP=true` the worker runs Alembic migrations through the shared `shared.migrations` helper before processing.
- **Structured logging** – Same formatter as the API, plus heartbeat/invalidation events (`worker.fetch.*`, `worker.persist.*`, `worker.heartbeat.*`).
- **On-chain automation** – Optional `RM_AUTO_CREATE_ONCHAIN_MARKETS` flow calls the Foundry-deployed factory with retries. Secrets can come from env or external secret managers.
- **Health checks** – Docker uses `python -m app.healthcheck` to ensure Postgres connectivity before marking the container healthy.

## Configuration

| Variable | Purpose |
| --- | --- |
| `RM_DATABASE_URL` | Postgres DSN used for persistence. |
| `RM_REDIS_URL` | Redis instance for cache invalidation + heartbeats. |
| `RM_POLYMARKET_API_BASE` / `RM_POLYMARKET_TIMEOUT_SECONDS` | Upstream ingest endpoint + timeout. |
| `RM_POLYMARKET_PAGE_SIZE` | Pagination size when crawling markets. |
| `RM_RUN_MIGRATIONS_ON_STARTUP` | Apply Alembic migrations from the worker. |
| `RM_AUTO_CREATE_ONCHAIN_MARKETS` | Enable on-chain market creation path (requires RPC + keys). |

## Local Usage

```bash
cd backend/worker
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
MODE=dev LOG_LEVEL=DEBUG python run.py
```

The worker expects Postgres/Redis to be available; easiest path is `./run_local.sh` from the repo root.

## Testing

Worker tests are co-located under `backend/worker/tests` and run via `./backend/run_tests.sh`. They cover:

- Polymarket pagination + persistence flow
- Heartbeat/cache invalidation
- Optional on-chain creation (with mocks)

## Deployment Tips

- Container image (`docker/worker/Dockerfile`) bundles Poetry build stage, copies migrations, and runs as `workeruser`.
- Leverage `RM_LOG_TO_FILE`, `RM_LOG_LEVEL`, and `LOG_DIR` to direct logs based on your infra.
- Use Kubernetes/Docker health checks (already wired) to ensure the worker does not start before Postgres is ready.
