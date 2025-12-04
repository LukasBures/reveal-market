# Prover TODO (post-simplification)

- **Regenerate artifacts** after the settlement circuit change (liability cap removed; still 10 public signals) and publish the new verifying key hash for on-chain verifier updates.
- **Request schema**: confirm all callers have dropped ticket/payoutMultiplier fields; keep docs/examples aligned.
- **Metrics**: current expvar is minimal—add Prometheus histograms/gauges (latency, in-flight jobs, errors) on `/metrics` if ops needs more visibility.
- **Artifact guardrails**: `check_artifacts.sh`/startup checks exist; optionally add hash verification to prevent stale/poisoned zkeys.
- **Production hardening**: document allowed origins/ingress for `/healthz` vs `/api/v1/proofs/settlement`, and pin `PROVER_RAPIDSNARK_BINARY`/Node versions in deployment manifests.
- **Optional**: CLI to fetch/report circuit hash and artifact presence (`go run ./cmd/verify-artifacts`) for CI/CD gates.
