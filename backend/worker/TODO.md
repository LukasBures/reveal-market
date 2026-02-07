# Worker TODO

**MVP - Critical**
- (done) Polymarket sync lease prevents multi-worker stampede during outages.
- (done) Proof queue depth enforcement is atomic under concurrency.

**MVP - High**
- (done) Cooldown on expensive memory scans and recovery loops.
- (done) Settlement recovery is paced for large datasets.

**MVP - Medium**
- (done) Metrics for queue age + cursor gap detection logging.

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
