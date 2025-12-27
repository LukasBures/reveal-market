# Worker TODO (MVP)

## MVP blockers
- [ ] Proof pipeline prerequisites: ensure commitments + settlements (including `batch_roots`/`batch_counts`) are ingested and refreshed so proof jobs can enqueue; wire relayer/prover ingestion or periodic on-chain refresh and emit metrics for missing data. (backend/worker/app/market_sync.py, backend/worker/app/proofs.py, backend/worker/app/settlement.py)
- [ ] MarketFactory mirroring: consume on-chain events (MarketCreated, RakeConfigured, guardian updates) or a Goldsky fallback to keep DB/cache in sync. (new sync helper + shared cache/model updates)

## MVP recommended
- [ ] Summary provenance: store each summary generation with prompt hash/model/context/timestamps, and fix tag collection to use `tags_rel`. (backend/worker/app/summary_jobs.py, backend/shared/repository_async.py)
- [ ] Retention behavior: decide whether to re-enable deletes or document/implement archival/backpressure; keep cache tags consistent on delete. (backend/worker/app/market_sync.py)
- [ ] Summary worker resiliency: retry/backoff on Redis outages instead of crashing at startup. (backend/worker/app/summary_worker.py)

## Notes
- Proof generation is gated by `RM_PROVER_ENABLED` + `RM_AUTO_SETTLEMENT_ENABLED` and existing commitments.
- Retention cleanup currently forces dry-run metrics regardless of `RM_RESOLVED_RETENTION_DRY_RUN`.
