# Reveal Market Worker Service

The worker ingests Polymarket + on-chain data, manages heartbeats, refreshes caches, and can optionally originate on-chain markets via MarketFactory. It shares models/utilities with the API but runs as an independent async loop.

## Highlights

- **End-to-end migrations** – When `RM_RUN_MIGRATIONS_ON_STARTUP=true` the worker runs Alembic migrations through the shared `shared.migrations` helper before processing.
- **Structured logging** – Same formatter as the API, plus heartbeat/invalidation events (`worker.fetch.*`, `worker.persist.*`, `worker.heartbeat.*`).
- **On-chain automation** – Optional `RM_AUTO_CREATE_ONCHAIN_MARKETS` flow calls the Foundry-deployed factory with retries. Secrets can come from env or external secret managers.
- **Health checks** – Docker uses `python -m app.healthcheck` to ensure Postgres connectivity before marking the container healthy.
- **Cache priming** – After every batch the worker rehydrates `/markets` (limit configurable) and records batch stats in Redis so health checks and dashboards stay warm.
- **Source-aware deduplication** – Gamma `updated_at`/hash metadata is stored per market so unchanged rows skip database writes and only invalidate the affected cache tags.
- **Featured slices** – Configure `RM_FEATURED_CATEGORIES` / `RM_FEATURED_TAGS` to precompute `/categories/<slug>` and `/tags/<slug>` responses in Redis. Category/tag caches reuse the same TTL as `/markets`.
- **Retention guardrails** – With `RM_RESOLVED_RETENTION_SECONDS` the worker trims resolved markets a day after settlement so Postgres stays lean while detail pages remain viewable.

## Configuration

| Variable | Purpose |
| --- | --- |
| `RM_DATABASE_URL` | Postgres DSN used for persistence. |
| `RM_REDIS_URL` | Redis instance for cache invalidation + heartbeats. |
| `RM_SCHEMA_VERSION_KEY` | Redis key that advertises the current Alembic revision for API cache tagging. |
| `RM_POLYMARKET_API_BASE` / `RM_POLYMARKET_TIMEOUT_SECONDS` | Upstream ingest endpoint + timeout. |
| `RM_POLYMARKET_PAGE_SIZE` | Pagination size when crawling markets. |
| `RM_RUN_MIGRATIONS_ON_STARTUP` | Apply Alembic migrations from the worker. |
| `RM_AUTO_CREATE_ONCHAIN_MARKETS` | Enable on-chain market creation path (requires RPC + keys). |
| `RM_API_BASE_URL` | Base URL the worker uses to call the API when priming `/markets`. |
| `RM_PRIME_MARKETS_CACHE_ENABLED` | Toggle cache priming (set `false` to disable the internal API call). |
| `RM_MARKETS_CACHE_LIMIT` / `RM_MARKETS_CACHE_OFFSET` | Pagination parameters used for the primed `/markets` payload. |
| `RM_MARKETS_CACHE_TTL_SECONDS` | TTL assigned to the primed cache entry so it matches API behavior. |
| `RM_BATCH_STATS_KEY` / `RM_BATCH_STATS_TTL_SECONDS` | Redis key + TTL used to persist the latest batch metrics for observability. |
| `RM_CATEGORY_CACHE_LIMIT` / `RM_TAG_CACHE_LIMIT` | Limits for the category + tag slices that get prefetched after each sync. |
| `RM_SUGGEST_CACHE_LIMIT` | Result size used when priming `/markets/suggest`. |
| `RM_FEATURED_CATEGORIES` / `RM_FEATURED_TAGS` / `RM_FEATURED_SUGGEST_QUERIES` | Comma-separated slugs/queries the worker should warm in Redis (e.g., `politics,sports` or `btc halving`). |
| `RM_RESOLVED_RETENTION_SECONDS` | How long to keep settled markets in Postgres before cleanup (default 24h). |
| `RM_RESOLVED_RETENTION_DRY_RUN` | When `true`, log markets eligible for cleanup without deleting them (useful for audits). |

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
