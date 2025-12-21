# Prover TODO (MVP)

## MVP blockers

- Surface circuit metadata (`circuitName`, `circuitVersion`) from `settlement_hashes.json` in `/healthz` and proof responses for auditing.

## Post-MVP hardening

- Add a signed artifact manifest to protect against stale/poisoned zkeys and witness assets.
- Emit artifact hash/mtime metrics and alert on verification failures or readiness flaps.
- Harden timeout/backoff defaults for rapidsnark/Node subprocesses and surface command output in structured logs for faster debugging.
- Add load/concurrency benchmarking harness with configurable temp dir and binary paths; document recommended `PROVER_MAX_CONCURRENCY` vs memory usage.
