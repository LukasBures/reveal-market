# Prover TODO

**MVP - Critical**
- Ensure circuit artifacts in `prover/circuits/build` match the deployed contracts (hashes + version).
- Lock down internal endpoints (`/debug/pprof/*`, `/metrics/expvar`) to trusted networks or `PROVER_ENABLE_DEBUG`.
- Validate proof requests from the worker with `PROVER_SHARED_SECRET` set in prod.

**MVP - High**
- Decide on `PROVER_STRICT_VALIDATION` policy (on/off) and document the expected totals/rake invariants.
- Add a lightweight proof queue in front of the prover (if request volume is bursty) to avoid 429 spikes.
- Add alerting on proof failures and high latency (Prometheus rules).

**MVP - Medium**
- Add a per-request trace ID propagated from worker to prover (e.g., `X-Request-Id`).
- Add a circuit hash endpoint so worker can preflight without hitting `/healthz`.

**MVP - Low**
- Add a warmup endpoint that runs a sample proof on startup to verify full pipeline.

**MVP - Nice to have**
- Add structured logging to include proof input sizes and queue wait times.

**Production - Critical**
- Store proving keys in a secure store (KMS + sealed artifact distribution).
- Implement key rotation procedure with rollback safeguards.

**Production - High**
- Add autoscaling based on active proof concurrency and queue depth.
- Add a shared artifact cache for multi-instance deployments.

**Production - Medium**
- Add canary proofs on deploys; block traffic if canary fails.

**Production - Low**
- Add proof result caching keyed by circuit hash + batch root to skip duplicates.

**Production - Nice to have**
- Add separate long-running proof worker processes with a public API front-end.
