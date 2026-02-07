# Relayer

FastAPI service for submitting on-chain transactions (commit/claim/lock) and optionally queueing them.

**Entrypoint**
- `relayer/src/relayer/main.py`

**Key responsibilities**
- Validate and submit commit, claim, and lock-batches transactions.
- Optional Redis-backed job queue with dead-letter support.
- Internal ingestion hooks back to API (commit/settlement) using `X-Internal-Secret`.
- Reuse shared HTTP client for API ingest and cache health checks to reduce overhead.

**Endpoints**
- `POST /commit`, `POST /claim`, `POST /lock-batches`.
- `POST /status` for queued job status.
- `GET /healthz`, `GET /healthz/deep`, `GET /metrics`.
- `GET /admin/queue/deadletter` and replay/purge endpoints.

**Config**
- `relayer/src/relayer/config.py`.
- Important: `RELAYER_BEARER_TOKEN` or `RELAYER_ALLOW_INSECURE_AUTH`, `RELAYER_API_BASE_URL`, `RELAYER_API_INTERNAL_SECRET`.
- New: `RELAYER_API_CLIENT_MAX_AGE_SECONDS`, `RELAYER_API_HEALTH_COOLDOWN_SECONDS`.

**Tests**
- `relayer/run_tests.sh`
