# Proover TODO

This backlog tracks the work still outstanding before the prover can be considered production grade. Keep it close to the code so every change to the prover acknowledges the remaining gaps.

### TL;DR priorities
1. **Profile + tune rapidsnark** – Benchmark the witness/proving pipeline and decide whether pooling or daemonization is required to hit latency targets.
2. **Expose real observability** – Promote expvar data to Prometheus, add percentile/concurrency metrics, and validate artifacts before boot so ops can trust SLAs.
3. **Harden operator ergonomics** – Ship env samples, validation, and documented upgrade paths (including future cgo embedding research) so non-Docker deployments stay secure.

1. **Performance tuning**
   - Benchmark rapidsnark invocation vs. witness generation to identify the current bottleneck.
   - Consider pooling rapidsnark subprocesses or switching to a long-lived daemon to eliminate process spawn overhead once profiling confirms it helps.

2. **Observability & metrics**
   - Export the current expvar counters to Prometheus (`promhttp.Handler`) so they can be scraped via kube sidecars instead of custom parsing.
   - Track rolling latency percentiles and concurrency saturation, not just the last duration.

3. **Artifact management**
   - Ship a helper command (e.g., `proover verify-artifacts`) that validates `settlement_final.zkey` and `settlement_js` consistency before boot.
   - Investigate packaging the default circuit artifacts as release assets so operators don’t need to run `generate_keys.sh` manually when cloning the repo for demos.

4. **Security hardening**
   - Run `codespell`, `gosec`, and other linters on the proover module as part of CI.
   - Introduce a non-root user when invoking rapidsnark locally (the Docker image already runs as `prover`, but bare-metal docs should highlight the same best practice).

5. **Configuration ergonomics**
   - Provide a sample `.env.proover` with the required env vars (`PROVER_RAPIDSNARK_BINARY`, `PROVER_CIRCUIT_DIR`, etc.) for operators who aren’t using Docker Compose.
   - Add validation for obviously wrong env inputs (e.g., warn when `PROVER_MAX_CONCURRENCY` exceeds `runtime.NumCPU()*2`).

6. **Roadmap**
   - Research embedding rapidsnark via cgo or replacing it with a pure-Go prover when the circuit size warrants it.
   - Track upstream rapidsnark releases and document the upgrade procedure (binary compatibility, CLI flags, changelog review).
