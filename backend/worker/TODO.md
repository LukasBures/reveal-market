# Worker TODO (MVP)

## MVP blockers
- [ ] Proof pipeline monitoring: add explicit alerts for missing commitments/settlements so proof jobs do not silently skip markets. (backend/worker/app/proofs.py, backend/worker/app/settlement.py)
- [ ] MarketFactory mirroring: consider streaming factory events (Goldsky) instead of per-market backfills so rake/signer/oracle changes are captured immediately.

## MVP recommended
- [ ] Retention behavior: decide whether to re-enable deletes or document/implement archival/backpressure; keep cache tags consistent on delete. (backend/worker/app/market_sync.py)

## Notes
- Proof generation requires `RM_PROVER_BASE_URL` and existing commitments.
- Retention cleanup currently forces dry-run metrics regardless of `RM_RESOLVED_RETENTION_DRY_RUN`.
