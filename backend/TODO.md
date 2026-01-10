# Backend TODO (API + shared)

Remaining work specific to the FastAPI service and shared backend modules.

## Critical
- **Auth hardening**: Protect mutation/admin routes with auth or network allowlists (pricing/quote, trade/commit, relayer ingest hooks, cache/markets admin paths, `/metrics`, `/healthz/heartbeats`). Ensure `RM_RELAYER_WEBHOOK_SECRET` and any bearer tokens are enforced in production.
- **Rate limiting**: Enable Redis-backed rate limits for `/pricing/quote` and `/trade/commit` in prod with trusted proxy configuration; avoid in-memory fallback outside local.
- **Market auto-deploy controls**: Decide policy for auto-creating markets during commit; add env guard for production and ensure deploy lock errors surface clearly in observability.
- **FX + CORS alignment**: Add smoke checks/alerts when FX host/CORS/allowed hosts diverge from frontend origin; include FX freshness in health probes.

## Nice to have
- Quote/commit audit endpoints behind admin auth (searchable quote ledger with expiry/status).
- Circuit hash/verifier alignment check exposed in proof receipts/health when RPC/verifier config is present.
- Refine cache hydration during Redis outages (optional background requeue once Redis recovers).
