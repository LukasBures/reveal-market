# Prover TODO

## MVP
- Expose circuit metadata (name/version) from `settlement_hashes.json` in `/healthz` and proof responses for easier audit trails.
- Add alerting hooks for artifact verification failures, readiness flaps, and proof latency spikes (metrics exist; wire alerts).

## Post-MVP
- Signed artifact manifest/checksum to guard against stale/poisoned zkeys and WASM; surface hash/mtime metrics.
- Harden subprocess timeouts/backoff for witness + rapidsnark and include command output in structured logs when failures occur.
- Integration test path for `PROVER_WITNESS_BINARY` (C++ witness) to ensure parity with the Node witness generator.
- Benchmark harness for different `PROVER_MAX_CONCURRENCY`/temp dir/binary settings; document recommended knobs for constrained CPU/memory.
