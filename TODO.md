# Reveal Market TODO

## MVP
- None (MVP blockers cleared).

## Production/Mainnet Readiness
- **Secrets & configs**: lock real RPCs/API keys in secret managers; audit `.env` usage and ensure defaults reference testnet only. Align chain IDs across API/worker/frontend/contract envs.
- **Prover artifacts**: ensure `prover/circuits/build` contains the latest audited zkey/WASM, hash-verify them at startup, and pin `PROVER_RAPIDSNARK_BINARY`/Node versions in deployment manifests.
- **DB & migrations**: apply Alembic head to production Postgres, confirm `settlement_receipts`/resolution tables are indexed, and backfill any legacy market rows into normalized tables.
- **Caching/CORS**: confirm streamer CORS/hosts match frontend origin (HTTPS for WSS), and revisit cache TTLs for resolved markets if production needs longer/shorter retention.
- **Monitoring/alerts**: scrape `/metrics` (API, worker, prover, streamer), add alerts for proof failures/latency, cache miss spikes, and health endpoints; capture pprof profiles in staging under load.
