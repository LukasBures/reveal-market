# Reveal Market TODO (Current State)

Cross-service items that remain open after aligning docs with the live implementation.

## Security & Access Control
- Lock down mutation/admin surfaces across API, worker, relayer, hedger, and prover with bearer/JWT or network allowlists. Cover relayer ingest hooks, API trade/pricing, hedger admin routes, and prover proof generation when exposed publicly.
- Ship sanitized `.env.example` files per service with clear prod vs local defaults and required secrets.
- Ensure webhook/shared secrets are set and enforced (`RM_RELAYER_WEBHOOK_SECRET`, prover shared secret, streamer access/control tokens if exposed).

## Chain & Artifact Alignment
- Keep verifier/circuit hash aligned across contracts/prover/backend (`prover/circuits/build/settlement_hashes.json`, on-chain verifier, `RM_CIRCUIT_HASH`). Add automated checks in CI where RPC access is available.
- Document/verify network presets per env (Horizen testnet defaults) and ensure API/worker/frontend/relayer/hedger share chain IDs and collateral/escrow addresses.

## Observability & Reliability
- Add alerting for critical paths: cache hydration failures, Polymarket ingest stalls, FX staleness, quote issuance errors, prover readiness flaps, relayer deadletter growth, and hedger settlement/hedge failures. Wire dashboards to `/metrics` across services.
- Confirm Redis/Postgres backup/retention strategy for production and document runbooks for cache flush, schema migrations, and artifact rotations.

## Data & Cache Hygiene
- Enforce TTL/eviction strategy across caches (API, worker, streamer) and validate resolved-market retention windows against product expectations.
- Backfill and validate normalized market tables and quote/settlement ledgers before production cutover; keep schema revision tags consistent across services.

## Performance Follow-ups
- Streamer: batch Redis writes and reuse HTTP clients to reduce CPU per tick; align worker count with CPU limits.
- Worker/API: consider bulk upserts and DB-side ordering to cut cache-miss latency; tune DB pool sizes after observing prod load.

## Deployment & CI/CD Hardening
- Build images in CI and push to private GHCR with SHA tags/digests; deploy pulls only pinned digests and consumes a published manifest instead of rebuilding.
- Put deploy in a concurrency group (cancel-in-progress) and use an atomic promote/lock so mid-deploy cancels never leave half-applied state.
- Serve prover-required assets from versioned, immutable storage keyed by commit (not the live frontend); verify checksums and fall back to the last known-good version on missing artifacts.
