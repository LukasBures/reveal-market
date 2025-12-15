# Prover TODO

- **Artifact guardrails**: `check_artifacts.sh`/startup checks exist; add hash verification + optional signed manifest to prevent stale/poisoned zkeys (production/mainnet readiness).
- Add structured alerting when artifacts fail verification or when `/healthz` flips to unready; expose hash/mtime in metrics for dashboards.
- Harden timeout/backoff defaults for rapidsnark/Node subprocesses and surface command output in structured logs for faster debugging.
- Add load/concurrency benchmarking harness with configurable temp dir and binary paths; document recommended `PROVER_MAX_CONCURRENCY` vs memory usage.
