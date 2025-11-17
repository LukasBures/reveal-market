# Reveal Market Worker Service

Long-running service that keeps Postgres, Redis, and on-chain state synchronized with Polymarket. The worker is responsible for fetching markets, persisting updates, generating resolution snapshots, priming caches, emitting heartbeats, and optionally originating on-chain markets.

---

## 1. Responsibilities

| Domain | Duties |
| --- | --- |
| Data ingestion | Poll Polymarket Gamma APIs, normalize payloads (`MarketPayload`), and upsert rows using shared SQLAlchemy models. |
| Resolution tracking | Prefer Goldsky subgraph data (fallback to Conditional Tokens RPC) to persist payout vectors in Postgres + Redis and update market status (`settled`). |
| Cache governance | Invalidate per-market tags, publish schema revisions, prime `/markets`, `/categories/{slug}`, `/tags/{slug}`, `/markets/suggest`. |
| Operational signals | Publish Redis heartbeats, batch stats, and Prometheus counters (`worker.*`). |
| Retention | Delete resolved markets older than `RM_RESOLVED_RETENTION_SECONDS` (dry-run supported). |
| Optional on-chain writes | When `RM_AUTO_CREATE_ONCHAIN_MARKETS=true`, call `MarketFactory.createMarket` with retry/backoff. |
| AI enrichment | Queue summary jobs whenever a market lacks a narrative and process them via `app.summary_worker`. |
| Proof receipts | When enabled, call the `proover` microservice to mint Groth16-compatible proof receipts and cache them in Redis for downstream APIs. |

> The `proover` container emits real Groth16 receipts (`rapidsnark` + the Circom artifacts under `proover/circuits/build`) and fails hard if the artifacts are missing. Mount fresh proving/verifying keys generated via `proover/circuits/generate_keys.sh` before sharing proofs with downstream systems.

---

## 2. Architecture Overview

1. **Startup** (`run_worker`):
   - Configure logging via `app.logging_config`.
   - Connect to Redis (heartbeat + cache invalidation).
   - Optionally run Alembic migrations (`_ensure_schema`) and broadcast the latest revision key.
2. **Main loop**:
   - `process_once()`:
     - Fetch Polymarket markets (with retry).
     - For each market, `sync_market()` upserts rows and calls `_apply_resolution`.
     - Optionally trigger `maybe_create_onchain_market`.
     - Run `cleanup_resolved_markets` to enforce retention.
     - Publish heartbeats, resolution cache updates, and targeted invalidations.
   - `prime_markets_cache()` warms the homepage payload.
   - `prime_featured_views()` hits `/categories`, `/tags`, `/markets/suggest` for “featured” cohorts.
   - `record_batch_stats()` writes summary JSON to Redis for dashboards.
   - Sleep for `RM_POLL_INTERVAL_SECONDS` minus loop runtime.
3. **Health**: Docker/compose call `python -m app.healthcheck` (simple DB ping) so orchestrators only start the loop when Postgres is reachable.

---

## 3. Source Layout

```
backend/worker/
├── app/
│   ├── main.py            # Core loop, cache priming, retention
│   ├── polymarket.py      # Gamma client + MarketPayload normalizer
│   ├── onchain.py         # Optional MarketFactory automation
│   ├── config.py          # Pydantic settings (RM_* vars)
│   ├── healthcheck.py     # Container health entrypoint
│   └── logging_config.py  # Shared log formatter
├── tests/                 # Pytests (mocks for HTTP, Redis, on-chain)
├── requirements*.txt
├── pyproject.toml
└── run.py                 # Local bootstrap (calls main.run_worker)
```

---

## 4. Configuration Cheat Sheet

All environment variables begin with `RM_`. Notable groups:

### Core runtime

| Variable | Description |
| --- | --- |
| `RM_DATABASE_URL` | Postgres DSN (same DB as the API). |
| `RM_REDIS_URL` | Redis URI used for cache invalidation, schema tags, heartbeat storage. |
| `RM_POLL_INTERVAL_SECONDS` | How often to pull Polymarket (default 60s). |
| `RM_RUN_MIGRATIONS_ON_STARTUP` | If true, apply Alembic migrations before syncing. |
| `RM_SCHEMA_VERSION_KEY` | Redis key where `_propagate_schema_revision` stores the current Alembic revision. |
| `RM_HEARTBEAT_KEY`, `RM_HEARTBEAT_TTL_SECONDS`, `RM_HEARTBEAT_MAX_RETRIES`, `RM_HEARTBEAT_RETRY_BACKOFF_SECONDS` | Heartbeat publishing behavior. |
| `RM_BATCH_STATS_KEY`, `RM_BATCH_STATS_TTL_SECONDS` | Where batch stats live in Redis. |

### Polymarket ingestion

| Variable | Description |
| --- | --- |
| `RM_POLYMARKET_API_BASE` | Base URL for Gamma API. |
| `RM_POLYMARKET_TIMEOUT_SECONDS` | HTTP timeout per request. |
| `RM_POLYMARKET_PAGE_SIZE`, `RM_POLYMARKET_MAX_PAGES` | Pagination controls. |
| `RM_POLYMARKET_ORDER`, `RM_POLYMARKET_SORT_ASCENDING`, `RM_POLYMARKET_CLOSED_FILTER` | Sorting/filtering toggles. |
| `RM_POLYMARKET_MAX_RETRIES`, `RM_POLYMARKET_RETRY_BACKOFF_SECONDS`, `RM_POLYMARKET_RETRY_BACKOFF_MAX_SECONDS` | Retry behavior for API calls. |

### Cache priming

| Variable | Description |
| --- | --- |
| `RM_API_BASE_URL` | Base HTTP URL used when the worker calls the API to warm caches. |
| `RM_PRIME_MARKETS_CACHE_ENABLED` | Toggle for priming `/markets`. |
| `RM_MARKETS_CACHE_LIMIT`, `RM_MARKETS_CACHE_OFFSET`, `RM_MARKETS_CACHE_TTL_SECONDS`, `RM_CACHE_PRIME_TIMEOUT_SECONDS` | Control the warmed payload + TTL. |
| `RM_CATEGORY_CACHE_LIMIT`, `RM_TAG_CACHE_LIMIT`, `RM_SUGGEST_CACHE_LIMIT` | Limits for featured priming. |
| `RM_FEATURED_CATEGORIES`, `RM_FEATURED_TAGS`, `RM_FEATURED_SUGGEST_QUERIES` | Comma-separated lists to warm after each batch. |

### Retention & summarization

| Variable | Description |
| --- | --- |
| `RM_RESOLVED_RETENTION_SECONDS` | Age threshold before deleting settled markets. |
| `RM_RESOLVED_RETENTION_DRY_RUN` | If true, log eligible rows but do not delete. |

### On-chain automation

| Variable | Description |
| --- | --- |
| `RM_AUTO_CREATE_ONCHAIN_MARKETS` | Enable `maybe_create_onchain_market`. |
| `RM_RPC_URL` / `RM_POLYGON_RPC_URL` | RPC endpoint used by web3 clients. |
| `RM_FACTORY_ADDRESS`, `RM_CONDITIONAL_TOKENS_ADDRESS`, `RM_RAKE_MANAGER_ADDRESS`, `RM_VERIFIER_ADDRESS` | Contract addresses. |
| `RM_WALLET_ADDRESS`, `RM_WALLET_PRIVATE_KEY` | Signer used for factory transactions. Source secrets from Vault/KMS whenever possible. |
| `RM_GAS_PRICE_GWEI`, `RM_MAX_PRIORITY_FEE_GWEI`, `RM_MAX_WEB3_RETRIES`, `RM_DEFAULT_COMMIT_LEAD_SECONDS`, `RM_DEFAULT_REVEAL_LEAD_SECONDS` | Gas + deadline tuning. |

### Summary enrichment

| Variable | Description |
| --- | --- |
| `RM_SUMMARY_ENABLED` | Master toggle for summary queueing + processing. |
| `RM_SUMMARY_QUEUE_KEY` / `RM_SUMMARY_DEAD_LETTER_KEY` | Redis keys for the work queue + DLQ. |
| `RM_SUMMARY_REQUESTED_TTL_SECONDS` | Debounce window before a market can be re-enqueued. |
| `RM_SUMMARY_REFRESH_INTERVAL_SECONDS` | Regenerate summaries older than this many seconds. |
| `RM_SUMMARY_MIN_WORDS` / `RM_SUMMARY_MAX_WORDS` | Boundaries enforced in prompts/fallbacks. |
| `RM_SUMMARY_MODEL` / `RM_SUMMARY_SOURCE_LABEL` | Metadata persisted with each summary. |
| `RM_SUMMARY_PROMPT_TEMPLATE` | Customizable template used to build the LLM prompt. |
| `RM_SUMMARY_API_BASE_URL` / `RM_SUMMARY_API_KEY` | Endpoint + credential for OpenAI (or API-compatible provider). |
| `RM_SUMMARY_HTTP_TIMEOUT_SECONDS` | Timeout for provider calls. |
| `RM_SUMMARY_QUEUE_POLL_SECONDS` | Blocking pop timeout for `app.summary_worker`. |
| `RM_SUMMARY_RETRY_MAX_ATTEMPTS` / `RM_SUMMARY_RETRY_BACKOFF_SECONDS` | Requeue/backoff behaviour before DLQing a job. |
| `RM_SUMMARY_FALLBACK_ENABLED` | Allow deterministic fallback summaries when the provider is unavailable. |

### Goldsky subgraph

| Variable | Description |
| --- | --- |
| `RM_GOLDSKY_SUBGRAPH_URL` | Goldsky GraphQL endpoint that indexes Horizen Conditional Tokens events. |
| `RM_GOLDSKY_API_KEY` | API key required for private Goldsky projects (leave blank for public endpoints). |
| `RM_GOLDSKY_TIMEOUT_SECONDS` | HTTP timeout for Goldsky GraphQL requests. |

### Prover integration

| Variable | Description |
| --- | --- |
| `RM_PROVER_ENABLED` | Toggle settlement-proof requests. When false, the worker skips prover calls entirely. |
| `RM_PROVER_BASE_URL` | Base URL for the `proover` container (defaults to `http://proover:8085` in docker-compose). |
| `RM_PROVER_TIMEOUT_SECONDS` | HTTP timeout when calling the prover service. |
| `RM_PROOF_CACHE_PREFIX` / `RM_PROOF_CACHE_TTL_SECONDS` | Redis key namespace + TTL for cached proof receipts. |

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

# Start the summary worker (in another terminal)
uv run --project . python -m app.summary_worker

# Optional: start the prover locally (needed when `RM_PROVER_ENABLED=true`)
docker compose up proover
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

Coverage highlights:
- `tests/test_polymarket.py`: payload normalization, hash computation, dedupe logic.
- `tests/test_main.py`: cache priming, retention, heartbeat/tags, schema propagation.
- `tests/test_onchain.py`: ensures factory actions are guarded and retry semantics work (mocks Tenacity/web3).

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
| Heartbeat | Redis key `RM_HEARTBEAT_KEY` contains the timestamp, markets processed/changed, resolutions changed, latency. API `/health` uses this to flag worker outages. |
| Batch stats | Stored at `RM_BATCH_STATS_KEY` with TTL; use `redis-cli GET reveal_market_worker:batch_stats | jq` for quick diagnostics. |
| Summary queue | `worker.summary.*` logs trace queue depth, requeue/dead-letter activity, and successful enrichments. |

---

## 8. Deployment & Ops Checklist

1. Build image via `docker/worker/Dockerfile` or `make worker`. The Dockerfile copies migrations so `_ensure_schema` succeeds.
2. Provide runtime dependencies:
   - Same Postgres as the API.
   - Redis reachable via `RM_REDIS_URL`.
   - Optional: access to RPC endpoints when on-chain mode is enabled.
3. Configure Kubernetes/Docker health check: `CMD ["python", "-m", "app.healthcheck"]`.
4. Mount secrets (RPC URLs, private keys) via secret manager or encrypted env vars—never bake them into images.
5. Scale: run multiple workers only if you coordinate cache invalidations and ensure idempotency. For now the service assumes a single writer to avoid double creation of on-chain markets.
6. Alert on:
   - Heartbeat staleness (`timestamp` older than TTL)
   - `worker.fetch.error` spikes
   - Retention errors (`worker.retention.cleanup` missing for >N minutes)
   - Cache priming failures (`worker.cache.prime_failed`, `worker.cache.featured_failed`)
7. Deploy `python -m app.summary_worker` alongside the main worker if you want AI summaries published automatically. Monitor the summary queue key to ensure it stays near zero.

---

## 9. Troubleshooting

| Issue | Diagnosis steps | Resolution |
| --- | --- | --- |
| Worker loops but markets never change | Inspect logs for `worker.market.skip_update`; likely Polymarket payloads have unchanged `source_updated_at`. Force refresh by clearing `content_hash` or verifying upstream data. |
| `/health` reports missing heartbeat | Check Redis for `RM_HEARTBEAT_KEY`. If absent, ensure worker can connect to Redis and that `_run_with_retries` isn’t repeatedly failing. |
| Cache never warms | Confirm `RM_API_BASE_URL` points to the reachable API and that `RM_PRIME_MARKETS_CACHE_ENABLED=true`. Review `worker.cache.prime_failed` logs for HTTP errors. |
| Retention deletes too aggressively | Validate `RM_RESOLVED_RETENTION_SECONDS` and whether your clocks are in UTC. Consider `RM_RESOLVED_RETENTION_DRY_RUN=true` to preview counts before deleting. |
| On-chain creation stuck | Look for `worker.tx.failed` or `worker.onchain.config_error`. Ensure RPC URL, factory address, and private key are set. Consider disabling `RM_AUTO_CREATE_ONCHAIN_MARKETS` while debugging. |
| Summary queue grows without bound | Check `worker.summary.requeued`/`dead_letter` logs, verify `RM_SUMMARY_API_KEY` is valid, and ensure `python -m app.summary_worker` is running. Reduce `RM_SUMMARY_MIN_WORDS` temporarily if the provider rejects long responses. |

---

## 10. Handy Commands

```bash
# Run a single sync then exit (useful for debugging)
python - <<'PY'
from worker.app.main import process_once
process_once()
PY

# Inspect heartbeat payload
redis-cli GET reveal_market_worker:heartbeat | jq

# Peek at the summary queue
redis-cli LLEN reveal_market_worker:summary_queue

# Tail worker logs inside Docker
docker logs -f reveal-worker
```

Keep the worker lean: reuse shared helpers, avoid blocking calls inside the DB transaction, and emit structured events for every meaningful branch so operations can react quickly.
