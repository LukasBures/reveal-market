# Backend MVP Checklist

This list tracks the remaining backend work needed to ship the MVP. Items are ordered by risk.

## Critical before MVP launch
- Lock down internal and mutation endpoints with auth (API key/JWT or network allowlist). Cover: `/markets` POST/PATCH, `/pricing/quotes/{id}`, `/proofs`, `/treasury/snapshots`, `/markets/onchain`, `/clob/orderbook`, `/commitments/sync`, `/settlements/ingest`, `/metrics`, `/healthz/heartbeats`.
- Quote issuance hardening: decide whether to keep API auto-create in prod; if disabled, require `market_id` exists in DB and block on-chain auto-create.
- Bind quotes and trade endpoints (`/trade/commit`, `/positions`, `/trade/claim`) to authenticated wallet identity (signed payload or session). Persist auth context in the quote ledger and use it for caps.
- Ensure `RM_RELAYER_WEBHOOK_SECRET` is set in prod and protect `/commitments/sync` + `/settlements/ingest` with internal auth or network allowlists.
- Rate limiting: enable Redis-backed limits for `/pricing/quote` and `/trade/commit` in prod, configure trusted proxies, and avoid in-memory fallback in production.
- FX configuration alignment: keep `RM_FX_FEED_URL` aligned to the streamer endpoint and ensure CORS/health checks reflect the configured host.

## Post-MVP / nice-to-have
- Quote audit endpoints (list/search) behind admin auth.
- Circuit hash/verifier alignment checks in proof receipts.
- On-chain mirroring/automation for factory events and settlement.
