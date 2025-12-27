# Backend MVP Checklist

This list tracks the remaining backend work needed to ship the MVP. Items are ordered by risk.

## Critical before MVP launch
- Lock down internal and mutation endpoints with auth (API key/JWT or network allowlist). Cover: `/markets` POST/PATCH, `/pricing/quotes/{id}`, `/proofs`, `/treasury/snapshots`, `/markets/onchain`, `/clob/orderbook`, `/commitments/sync`, `/settlements/ingest`, `/metrics`, `/healthz/heartbeats`.
- Quote issuance hardening: require `market_id` exists, validate `outcome_id` against stored outcomes, reject mismatched `market_address`, and disable auto market creation from the API (keep it worker-only/admin).
- Bind quotes and trade endpoints (`/trade/commit`, `/positions`, `/trade/claim`) to authenticated wallet identity (signed payload or session). Persist auth context in the quote ledger and use it for caps.
- Require `X-Relayer-Secret` (or equivalent auth) on all ingest hooks and remove or disable the unauthenticated variants.
- Rate limiting: enable Redis-backed limits for `/pricing/quote` and `/trade/commit` in prod, configure trusted proxies, and avoid in-memory fallback in production.
- FX configuration alignment: make pricing use `RM_FX_FEED_URL` or remove the setting; keep health/CORS checks and docs consistent with the actual FX source.

## Post-MVP / nice-to-have
- Quote audit endpoints (list/search) behind admin auth.
- Summary provenance history and DLQ metrics for the enrichment worker.
- Circuit hash/verifier alignment checks in proof receipts.
- Surface `batch_roots`/`batch_counts` and per-batch receipts in `/proofs` responses for multi-batch markets.
- On-chain mirroring/automation for factory events and settlement.
