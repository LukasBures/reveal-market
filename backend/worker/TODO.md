# Worker TODO

**MVP - Critical**
- Ensure Polymarket sync lease prevents multi-worker stampede during outages.
- Confirm proof queue depth enforcement is atomic under concurrency.

**MVP - High**
- Add cooldown on expensive memory scans and recovery loops.
- Ensure settlement recovery is paced for large datasets.

**MVP - Medium**
- Add metrics on Gamma empty page tolerance and gap detection.

**MVP - Low**
- Add batch-level timing metrics to logs.

**MVP - Nice to have**
- Add a local mock mode for Gamma and chain to speed tests.

**Production - Critical**
- Validate prover artifacts and circuit hash alignment at startup.

**Production - High**
- Add circuit breaker for chain hydration calls.

**Production - Medium**
- Add queue DLQ trimming and aging policies.

**Production - Low**
- Add a maintenance mode for backfills and cleanup tasks.

**Production - Nice to have**
- Add automatic pacing based on DB latency metrics.
