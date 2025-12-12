# Worker TODO

## Findings
- backend/worker/app/market_sync.py: proof generation remains effectively unreachable; proof jobs only enqueue when a settlements row exists, but the worker never ingests commitments/settlement snapshots. Default runs skip proofs and never hit `_persist_settlement_snapshot`.
- backend/shared/repository.py:157-171 & backend/worker/app/summary_jobs.py:74: Summaries are overwritten in-place (no history/prompt hash/model provenance) and prompt inputs omit tags because `market_record` lacks `tags`; only `tags_rel` exists. This misses the AI-summary provenance requirement and weakens prompts.
- backend/worker/app/market_sync.py: cleanup retention is hard-disabled; even with `RM_RESOLVED_RETENTION_SECONDS` and `dry_run=False`, the code always returns `dry_run=True`, so resolved/closed markets accumulate and stale cache tags linger.
- backend/worker/app/schema.py: `_propagate_schema_revision` lacks a dedicated success metric/log; cache writes are best-effort and can be hard to observe.
- backend/worker/app/summary_worker.py: Summary worker assumes Redis is reachable; `Redis.from_url` failures crash the worker. Needs guard/retry/backoff like the main worker.
- backend/worker/app/market_sync.py: Factory/rake mirroring is a stub (“sync” events with no chain data); no listener for MarketFactory events or rake config updates, so on-chain drift isn’t prevented, blocking the “on-chain mirroring & automation” item.

## Recommended MVP-ready fixes
1. Add an ingestion path for commitments/settlements (from on-chain or hedger outputs) so `settlements`/`commitments` tables are populated and proof jobs can run; wire retries + metrics.
2. Implement summary audit trail: store each generation with prompt hash/model/context/timestamps, and fix tag collection to use `tags_rel`.
3. Re-enable configurable retention or document the intentional disable; if keeping data, add backpressure/archival.
4. Fix `_propagate_schema_revision` indentation and add a success metric/log.
5. Harden summary worker startup against Redis outages.
6. Build a MarketFactory event consumer (or Goldsky subgraph fallback) to mirror address/rake/guardian updates and support optional settlement automation.
