# Proover MVP Checklist

Only two things block us from trusting the prover in MVP environments:

1. **Artifact validation helper**
   - Ship a CLI/env command (e.g., `prover verify-artifacts`) that confirms `settlement_final.zkey` + `settlement_js` exist and match the expected hash before the service boots outside Docker.
   - Fail fast (with actionable messaging) when artifacts are missing or stale.

2. **Prometheus metrics**
   - Export latency histograms and concurrency gauges via `/metrics` so ops can alert on slow proofs or stalled queues.
   - Include a build/version label so dashboards know exactly which prover binary is running.

3. **Ops hygiene**
   - Ensure prover debug endpoints stay reachable behind whatever CORS/ingress rules are applied in staging/prod; document expected origins in ops runbooks.

4. **Quote-aware proofs (if needed)**
   - If settlement proofs ever include priced quote fields, document required public inputs and ensure the pricing signer/chain bindings stay outside the proving payload; otherwise keep proofs independent to avoid coupling to quote flow.

Deliver these and the prover is MVP-ready.
