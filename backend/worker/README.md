# Backend Worker

Async worker that syncs markets from Polymarket/Gamma, updates the database, primes caches, and drives proof/settlement queues.

**Entrypoint**
- `backend/worker/app/service.py` is the main loop.

**Key responsibilities**
- Pull and normalize Polymarket/Gamma data into DB.
- Persist normalized tables (outcomes, tags, CLOB tokens, gamma metadata).
- Maintain cache tags and prime key views.
- Enqueue proof jobs and settlement jobs.
- Publish Redis heartbeats and batch stats.
- Enforce lease-based sync and cursor checkpoints to prevent stampedes and gaps.
- Track proof queue depth and oldest age for backlog visibility.
- Circuit-break chain hydration calls and enable maintenance mode for backfills.
- Validate prover artifacts + circuit hash alignment at startup.
- Support local mock mode for Gamma/chain in tests.

**Config**
- `backend/worker/app/config.py` for settings.
- Important: `RM_DATABASE_URL`, `RM_REDIS_URL`, `RM_POLYMARKET_API_BASE`, `RM_PROVER_BASE_URL`.
- New: `RM_POLYMARKET_SYNC_CURSOR_KEY` and proof queue age/lease settings (see config).

**Tests**
- `backend/worker/run_tests.sh`
