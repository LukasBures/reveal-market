# Proover MVP Checklist

Only two things block us from trusting the prover in MVP environments:

1. **Artifact validation helper**
   - Ship a CLI/env command (e.g., `proover verify-artifacts`) that confirms `settlement_final.zkey` + `settlement_js` exist and match the expected hash before the service boots outside Docker.
   - Fail fast (with actionable messaging) when artifacts are missing or stale.

2. **Prometheus metrics**
   - Export latency histograms and concurrency gauges via `/metrics` so ops can alert on slow proofs or stalled queues.
   - Include a build/version label so dashboards know exactly which prover binary is running.

Deliver these and the prover is MVP-ready.
