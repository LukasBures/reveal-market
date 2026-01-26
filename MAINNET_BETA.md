# Mainnet Beta Readiness Report (Investor-Focused Deep Inspection)

This document is a production readiness report based on the current repo state (code, configs, TODOs, compose/prod scripts, and READMEs). It is organized by service and then by cross-service glue/communications, with an explicit investor lens. Each section lists:

- **What exists today** (capabilities and controls already implemented).
- **What is missing or must be verified** before a mainnet beta launch.
- **Why it matters** (risk/impact).
- **How to close** (specific next steps or configuration).

> Scope: `backend/api`, `backend/worker`, `frontend`, `streamer`, `relayer`, `hedger`, `prover`, `contracts/zen`, `contracts/polygon`, plus infra glue (Caddy, DB, Redis, artifacts, CI/CD, alerts).

---

# Investor-Ready MVP Goals

For fund-raising, the priority is a **polished, reliable demo** that is **fast** and **credible**, even with a minimal set of features. The lowest-risk path is to ship a beautiful frontend with a single end-to-end flow that never fails, then harden security and ops behind it.

## MVP objectives (short list)
1) **Nice looking**: premium marketing UI + consistent visual system.
2) **Functional**: one demo flow (view market → preview price → quote → commit or simulated commit → confirmation).
3) **Quick**: fast first load (LCP), no jank, predictable demo response times.
4) **Minimal features**: avoid proving/settlement/hedger in the demo unless fully wired and reliable.

## MVP must-haves (for the investor demo)
- **Frontend polish**: strong landing page + narrative section + “how it works” + demo flow.
- **Demo reliability**: frontend must display a friendly fallback if API/FX/streamer is down.
- **Auth on mutation routes**: API and relayer must not be open in production.
- **CORS + origin alignment**: streamer + API + frontend must align and be validated at startup.
- **Basic monitoring**: a small dashboard or alert for API error rate and streamer FX staleness.

## MVP can be deferred (if not reliable)
- Hedger and on-chain settlement submission.
- Prover proof generation in the live demo (may be shown as roadmap).
- Full contracts upgrade flows beyond a single target network.

---

## 1) Backend API (FastAPI)

### What exists today
- App factory wires **structured logging**, **Prometheus**, **CORS/trusted hosts**, **rate limiting**, and **security headers** (CSP/HSTS/COOP). See `backend/api/app/server.py`, `backend/api/app/http_middleware.py`, `backend/api/app/security.py`.
- **Lifespan tasks** include migrations, cache hydration, quote sweeps, and optional circuit hash validation.
- **Caching**: Redis cache with tag invalidation; clean bypass if Redis down.
- **Pricing**: `/pricing/quote` uses streamer FX, ignores client FX, enforces caps, signs QUOTE_V1, stores quote ledger.
- **Trade**: `/trade/commit` consumes quote, builds commit auth signature, forwards to relayer (queue fallback); `/trade/status` polls queued results.
- **Health**: `/healthz` checks DB, Redis, worker heartbeat, Polymarket reachability, signer presence, schema revision, CORS/Fx CORS. Liveness at `/live` and readiness at `/ready`.
- **Metrics**: `/metrics` for HTTP/cache/rate-limit/quote issuance.

### Missing / must verify before mainnet beta
1) **Auth hardening for mutation/admin routes**
   - Missing: enforced bearer/JWT or IP allowlist for mutation and admin endpoints.
   - Affected: `/pricing/quote`, `/trade/commit`, relayer ingest hooks, any admin/cache endpoints, `/metrics`, `/healthz/heartbeats`.
   - Repo TODO: `backend/TODO.md`.

2) **Relayer webhook/bearer secret enforcement**
   - `RM_RELAYER_WEBHOOK_SECRET` exists but is optional. Need explicit enforcement in prod mode.

3) **Rate limiting in production**
   - Rate limiting defaults on outside dev unless disabled, but config must be set:
     - `RM_RATE_LIMIT_ENABLED`, `RM_RATE_LIMIT_REQUESTS_PER_WINDOW`, `RM_RATE_LIMIT_WINDOW_SECONDS`.
     - **Trusted proxy** config is required if running behind reverse proxy.

4) **Circuit hash alignment check**
   - Settings require `PROVER_CIRCUIT_HASH`, but there is no automated production-time check against the on-chain verifier and prover artifacts.

5) **FX/Origin alignment monitoring**
   - API validates CORS and FX origin; still needs alerting when FX origin diverges from frontend origin or streamer URL.

6) **Audit endpoints for quotes/commits**
   - Suggested in TODO: admin endpoints for quote ledger (searchable, expiry/consumed) behind auth.

7) **Operational runbooks**
   - No documented procedure for:
     - cache flush, migration rollback, quote ledger cleanup, emergency shutdown.

### Why it matters
- Without auth/rate limits, pricing/commit endpoints are abuse targets.
- Misaligned circuit hash or verifier breaks settlement.
- FX or CORS mismatches can silently break trading in production.

### How to close
- Enforce auth on protected routes; fail startup if `RM_RELAYER_WEBHOOK_SECRET` missing in prod.
- Configure rate limits + trusted proxies; add load test.
- Add CI/health check to validate circuit hash vs on-chain verifier and prover artifacts.
- Add alerts for FX/streamer/CORS mismatch.
- Add admin audit endpoints behind auth (or move to internal ops service).

### Investor-focused gaps (nice-looking / functional / quick / minimal)
- **Demo-safe fallback**: When FX/streamer is down, the API should expose a safe “demo mode” or respond with a clear error that the frontend can present without breaking the UX.
- **Investor analytics**: a minimal metrics endpoint or dashboard card (volume, markets ingested, uptime) to reinforce traction.
- **Latency budget**: identify the slowest endpoints (`/pricing/quote`, `/markets`, `/markets/{id}`) and set explicit response targets.

---

## 2) Backend Worker (ingestion / proofs / settlement helpers)

### What exists today
- Polymarket Gamma `/events` ingestion with retries, backoff, rate limiting; normalizes data and upserts into Postgres.
- Goldsky resolution snapshots, cache invalidation + priming via API.
- Redis leases to avoid concurrent ingests; clean bypass if Redis down.
- Optional proof queue + settlement helpers (Poseidon batch roots, BATCH_SIZE=256, MERKLE_DEPTH=8).
- Maintenance loop (retention metrics only, no deletes).

### Missing / must verify before mainnet beta
1) **Monitoring and alerts for ingestion stalls**
   - TODO: alerts for stalled Gamma sync, missing heartbeats, proof/settlement queue gaps.

2) **Factory event mirroring**
   - TODO: stream on-chain factory changes (rake/signer/oracle/caps) instead of relying on backfill.

3) **Proof queue observability**
   - TODO: queue depth + oldest job age metrics and health indicators.

4) **Retention policy decision**
   - Currently retention is metrics-only; actual deletion/archival policy must be decided.

5) **Prod-required envs**
   - Worker enforces prod-like required settings; verify all required envs are set:
     - `RM_DATABASE_URL`, `RM_REDIS_URL`, `RM_PROVER_BASE_URL`, `RM_RPC_URL`, `RM_SETTLEMENT_SIGNER_PRIVATE_KEY`.

### Why it matters
- Ingestion stalls or proof queue backlogs can silently stop market updates or settlement.
- Lack of factory mirroring risks stale signer/cap/rake configuration.

### How to close
- Implement queue depth metrics and staleness alarms.
- Mirror on-chain factory events into ledger.
- Decide retention (delete/archival) and implement safe cleanup steps.

---

## 3) Streamer (SSE/WS price/FX)

### What exists today
- DataStreamer (CLOB WS + REST hydrate + RTDS optional) and PriceStreamer (Binance WS + REST fallback + CryptoCompare fallback).
- Redis cache/history, staleness detection, throttled publish.
- Optional access/control tokens, rate limiting, and max connection/subscription caps.
- CORS presets via `RM_ENVIRONMENT`.

### Missing / must verify before mainnet beta
1) **Alerting for FX staleness and CLOB stalls**
   - TODO: FX staleness, stream stalls, history backlog growth.

2) **Performance optimizations**
   - TODO: batch Redis writes, reuse HTTP clients to reduce per-tick CPU.

3) **Worker count guidance**
   - TODO: recommended UVicorn workers vs CPU limits.

4) **Access token configuration**
   - If public, ensure `STREAMER_ACCESS_TOKEN`/`STREAMER_CONTROL_TOKEN` are set.

### Why it matters
- Stale FX and stream stalls directly impact trading and pricing.

### How to close
- Add alerts/dashboards for staleness, backlog, publish delays.
- Set access tokens in prod; test subscription caps.

### Investor-focused gaps (nice-looking / functional / quick / minimal)
- **Graceful degradation**: the UI must work even if streamer WS is unavailable (SSE/HTTP fallback is present but needs explicit UX states).
- **Stable demo data**: if using live Polymarket data is risky, consider pinning a curated subset for demo mode.

---

## 4) Relayer

### What exists today
- FastAPI + Web3, durable queue (SQLite or Postgres), fee bumps, retries, health/metrics, bearer/IP auth.
- `/commit`, `/claim`, `/lock-batches`, `/status`, `/metrics`, admin DLQ endpoints.

### Missing / must verify before mainnet beta
1) **Prod .env example + deployment docs**
   - TODO: relayer `.env.example` + compose/K8s snippet.

2) **Expanded tests**
   - TODO: fee-bump retry coverage, DLQ replay on SQLite and Postgres.
   - TODO: `/lock-batches` validation tests.

3) **Default prod security presets**
   - Auth exists but not enforced by default unless env is set. Must enforce in prod.

4) **Queue backlog metrics**
   - TODO: queue depth/oldest job age metrics.

### Why it matters
- Relayer queue/backlog or auth misconfig can cause stuck or abused transactions.

### How to close
- Add missing tests and queue backlog metrics.
- Enforce required bearer token in prod; use IP allowlist.

### Investor-focused gaps (nice-looking / functional / quick / minimal)
- **Demo flow reliability**: if relayer is down, allow a simulated commit path in the UI to avoid demo failure.

---

## 5) Hedger

### What exists today
- Admin FastAPI service with exposure ledger, risk checks, FX validation, Polymarket hedging client, LP vault client, prover requests.
- Redis locks/idempotency + DB storage.
- `/admin/commits`, `/admin/risk`, `/admin/positions`, `/admin/settlements/{market_id}`, `/admin/bridge`, `/metrics`.

### Missing / must verify before mainnet beta
1) **Auth + rate limits for `/admin/*`**
   - All routes are open by default; must be gated in prod.

2) **Durable commit/settlement ingestion**
   - TODO: commit/settlement feed with stored offsets (replay/backfill).

3) **On-chain settlement submission**
   - Hedger only requests proofs, no on-chain submission flow.

4) **Risk alignment with API caps**
   - TODO: align per-user/per-market caps with API.

5) **Metrics and alerting**
   - TODO: offsets/lag, FX staleness, utilization thresholds, float thresholds.

### Why it matters
- Hedger is the risk-control layer. If unauthenticated or missing ingestion durability, it can’t be trusted in prod.

### How to close
- Add auth middleware and rate limits.
- Implement durable ingestion with offset persistence.
- Add on-chain settlement/unwind workflows.

### Investor-focused gaps (nice-looking / functional / quick / minimal)
- **Can be deferred for the demo** if not fully wired and safe. If included, expose only read-only risk stats.

---

## 6) Prover (Groth16 service)

### What exists today
- Strict artifact check; service refuses to start if required artifacts missing.
- Proof generation pipeline (witness + rapidsnark), metrics, /healthz, /heartbeat.
- Artifact download script with SHA verification; run_local/run_prod check artifacts.

### Missing / must verify before mainnet beta
1) **Expose circuit metadata in /healthz + proof responses**
   - TODO: include metadata from `settlement_hashes.json`.

2) **Alerting on readiness and latency**
   - TODO: alerting for artifact verification failures, readiness flaps, proof latency spikes.

3) **Signed artifact manifest**
   - TODO: signed manifest/checksum for zkeys/WASM.

4) **Witness + rapidsnark failures diagnostics**
   - TODO: include command output in structured logs.

5) **Integration tests for C++ witness mode**
   - TODO: parity tests for `PROVER_WITNESS_BINARY`.

### Why it matters
- Proof generation is critical for settlement. Artifact mismatch or missing logs make outages hard to diagnose.

### How to close
- Add circuit metadata in health responses.
- Add alerting and signed artifact manifest.
- Expand tests for C++ witness path.

### Investor-focused gaps (nice-looking / functional / quick / minimal)
- **Avoid live proof generation in the demo** unless it is extremely stable. Use roadmap callouts instead.

---

## 7) Frontend (Next.js)

### What exists today
- Next.js App Router with streaming prices/FX, RSC fetchers, server actions, and security headers.
- CSP/HSTS/COOP/Permissions-Policy via `next.config.mjs`.
- Vitest + Testing Library coverage.
- SEO metadata centralized in `lib/seo.ts`.

### Missing / must verify before mainnet beta
1) **Performance budgets and audits**
   - TODO: LCP/TTI budgets, bundle audits.

2) **SLOs and frontend alerting**
   - TODO: SLOs + alerting for API/streamer reachability and UI error rates.

3) **Accessibility sweep**
   - TODO: keyboard/focus/contrast checks.

4) **Incident playbooks/status messaging**
   - TODO: UI/ops messaging for streamer/API/FX outages.

5) **Investor-grade marketing layout**
   - Missing: a dedicated investor narrative section (traction, moat, roadmap, proof of tech).

6) **Visual system coherence**
   - Missing: a single cohesive typographic and color system that reads “premium financial product.”

### Why it matters
- Frontend is customer-facing; performance and stability determine conversion and trust.
 - Investors judge product credibility in seconds; visuals must signal quality.

### How to close
- Add Lighthouse CI / Web Vitals budgets.
- Add alerting on error rates and API/streamer failures.
- Add an investor landing section with metrics and a crisp story.
- Add UX states for FX/streamer failure (demo-safe fallback).

---

## 8) Contracts (Zen / Horizen)

### What exists today
- Commit/reveal market suite with Poseidon batch settlement, Groth16 verifier, and circuit hash enforcement.
- `MarketFactory` sets oracle, authorization signer, rake, relayer escrow, caps, deadlines.
- `RelayerEscrow` and `ProtocolPool` interactions.

### Missing / must verify before mainnet beta
1) **Circuit hash alignment**
   - TODO: CI check ensuring on-chain verifier hash aligns with prover artifacts and backend `RM_CIRCUIT_HASH`.

2) **Test coverage expansions**
   - TODO: pause/rotation sequencing, cap updates mid-market, multi-claim ordering, protocol cap edges.

3) **Ownership transfer scripts**
   - For production: ensure Ownable2Step transfer scripts exist and are tested.

### Why it matters
- Circuit hash mismatch breaks settlement; admin flow errors are catastrophic in mainnet.

### How to close
- Add CI checks, expand tests, script ownership/pauser flows.

---

## 9) Contracts (Polygon / Hedging Vault)

### What exists today
- LP vault and hedge executor contracts, with tests, gas snapshots, and utilization caps.

### Missing / must verify before mainnet beta
1) **Ownership/guardian pause transfer scripts**
   - README calls out manual steps; must be scripted/tested.

2) **Pre-launch config**
   - Must set `maxUtilizationBps`, hedger role, signer, receiver whitelist.

### Why it matters
- Vault misconfiguration can lock funds or allow unauthorized hedging.

### How to close
- Add deployment scripts and tests for ownership transfer and role configuration.

---

## 10) Caddy / Edge / TLS

### What exists today
- Caddy container with TLS profiles and Cloudflare DNS-01 support.
- Static artifacts served from `/srv/artifacts` for prover artifacts.

### Missing / must verify before mainnet beta
1) **Immutable artifact hosting**
   - Must host prover artifacts with checksum verification (already supported by scripts, not enforced operationally).

2) **Edge runbooks**
   - No documented failover procedure for TLS renewal failures, DNS or proxy issues.

### Investor-focused gaps (nice-looking / functional / quick / minimal)
- **Domain polish**: ensure canonical domain and redirects are flawless; avoid mixed content or subdomain confusion.

---

## 11) Database / Redis / Persistence

### What exists today
- Postgres 15 with tuned settings in compose.
- Redis for caching, heartbeats, queues.
- Alembic migrations in `backend/migrations`.

### Missing / must verify before mainnet beta
1) **Backup and retention strategy**
   - TODO: backup strategy for Postgres/Redis, runbooks for restore.

2) **Redis persistence and eviction policy**
   - Need explicit production config and alerts for eviction or memory pressure.

3) **Schema migration runbooks**
   - No rollback/forward plan in documentation.

---

## 12) CI/CD / Deployment Hardening

### What exists today
- `run_prod.sh` validates artifacts, builds with BuildKit, runs compose stack.
- CI workflow runs tests in order; `run_tests.sh` mirrors CI.

### Missing / must verify before mainnet beta
1) **Image build/pin strategy**
   - TODO: build in CI, push to GHCR with digests, deploy pinned digests.

2) **Deploy concurrency lock**
   - TODO: deploys should be atomic with a lock to avoid partial state.

3) **Artifact hosting best practices**
   - TODO: versioned immutable storage for prover artifacts, fallback to last-known-good.

### Investor-focused gaps (nice-looking / functional / quick / minimal)
- **Demo build pipeline**: a repeatable “demo build” path that is stable and fast, even if production deploy is not yet hardened.

---

# Cross-Service Glue / Communications

## A) Pricing / FX / Streamer alignment

**What exists**
- API hard-pins FX to streamer `/fx/zen-usd`.
- Frontend uses `NEXT_PUBLIC_PRICE_STREAMER_URL` and streamer WS.
- Streamer has CORS presets.

**Missing / must verify**
- End-to-end validation that `NEXT_PUBLIC_PRICE_STREAMER_URL`, `STREAMER_PUBLIC_BASE_URL`, `RM_FX_FEED_URL`, and API CORS origins all align.
- Alerting if FX feed is stale or blocked (API, frontend, streamer).

**Why it matters**
- FX mismatch or CORS misconfig breaks pricing/trading.

**How to close**
- Add a config validation job in CI/prod and add health checks that ensure base URLs match.

---

## B) Quote / Commit / Relayer chain

**What exists**
- API signs quote with `RM_PRICING_SIGNER_PRIVATE_KEY` and uses relayer for commit.
- Relayer supports commit/claim/lock-batches and can ingest to backend.

**Missing / must verify**
- Strong auth for the relayer ingest hooks (API) and relayer endpoints.
- Rate limiting for commit path.
- Monitoring on relayer queue backlog and error rates.

---

## C) Circuit hash / Verifier alignment

**What exists**
- Prover artifacts contain circuit hash.
- API requires `PROVER_CIRCUIT_HASH` to start.
- Contracts enforce circuit hash on settlement.

**Missing / must verify**
- Automated check that on-chain verifier/circuit hash matches prover artifacts and API config.

**Why it matters**
- If any one component mismatches, settlement fails.

---

## D) Proofs / Settlement flow

**What exists**
- Worker can build proof payloads and store receipts.
- Hedger can request proofs.

**Missing / must verify**
- Hedger does not submit settlements on-chain.
- Worker/relayer lock-batches path lacks strong validation tests.

**Investor MVP note**
- This can be omitted for the demo if the UI clearly labels proofs/settlement as “roadmap” or “beta.”

---

## E) Auth & Security posture across services

**What exists**
- Each service has optional bearer tokens / secrets / allowlists.

**Missing / must verify**
- A unified production auth policy (e.g., JWT/bearer everywhere), required by default.
- Enforcement that critical secrets must be set in production.

---

## F) Observability and alerts

**What exists**
- Prometheus metrics across services and structured logs.

**Missing / must verify**
- Dashboards, alerting, runbooks for:
  - FX staleness
  - Stream stalls
  - Queue backlogs
  - Proof latency
  - API error spikes

---

## G) Data retention / cache TTL

**What exists**
- TTLs across caches; retention currently metrics-only.

**Missing / must verify**
- Production policy for retention, archive, cleanup.

---

# Required Configuration Inventory (Mainnet Beta)

This is a non-exhaustive list of envs that must be set and aligned. Confirm these are in the production secrets store and checked in a startup validator.

## Core
- `RM_ENVIRONMENT=prod`
- `RM_DATABASE_URL` / `RM_DATABASE_ASYNC_URL`
- `RM_REDIS_URL`

## API
- `RM_ALLOWED_HOSTS`
- `RM_CORS_ALLOW_ORIGINS`
- `RM_PRICING_SIGNER_PRIVATE_KEY`
- `RM_PRICING_CHAIN_ID`
- `RM_RELAYER_BASE_URL`
- `RM_RELAYER_BEARER_TOKEN`
- `RM_RELAYER_WEBHOOK_SECRET`
- `RM_RATE_LIMIT_ENABLED=true` + `RM_RATE_LIMIT_*`
- `PROVER_CIRCUIT_HASH`

## Worker
- `RM_PROVER_BASE_URL`
- `RM_RPC_URL`
- `RM_SETTLEMENT_SIGNER_PRIVATE_KEY`
- `RM_RELAYER_BASE_URL` (if using relayer for lock-batches)

## Relayer
- `RELAYER_PRIVATE_KEY`
- `RELAYER_ESCROW_ADDRESS`
- `RELAYER_BEARER_TOKEN`
- `RELAYER_API_BASE_URL` + `RELAYER_API_BEARER_TOKEN`

## Hedger
- `HEDGER_LP_VAULT_ADDRESS`
- `HEDGER_VAULT_RPC_URL`
- `HEDGER_VAULT_PRIVATE_KEY`
- `HEDGER_VAULT_SENDER_ADDRESS`
- `HEDGER_PROVER_BASE_URL`
- `HEDGER_PROVER_SHARED_SECRET`

## Streamer
- `STREAMER_PUBLIC_BASE_URL`
- `STREAMER_INTERNAL_BASE_URL`
- `STREAMER_CORS_ALLOW_ORIGINS`
- `STREAMER_ACCESS_TOKEN`
- `STREAMER_CONTROL_TOKEN`

## Frontend
- `NEXT_PUBLIC_API_BASE_URL`
- `NEXT_PUBLIC_PRICE_STREAMER_URL`
- `NEXT_PUBLIC_SITE_URL`
- `NEXT_PUBLIC_CHAIN_ID`
- `NEXT_PUBLIC_RPC_URL`
- `NEXT_PUBLIC_RELAYER_ESCROW_ADDRESS`

## Prover
- `PROVER_SHARED_SECRET`
- `PROVER_ARTIFACTS_URL` + `PROVER_ARTIFACTS_SHA256`

---

# Final Mainnet Beta Exit Criteria

Use this as a “go/no‑go” checklist.

1) **Security**
   - All mutation/admin endpoints are authenticated and rate limited.
   - All inter-service secrets enforced in prod.

2) **Circuit and Chain Alignment**
   - Prover artifacts, API `PROVER_CIRCUIT_HASH`, and on-chain verifier hash are proven aligned.

3) **Operational Observability**
   - Dashboards and alerts for FX staleness, ingestion stalls, queue backlog, prover latency, and API error rates.

4) **Proof + Settlement Flow**
   - Proof generation works end-to-end against real artifacts.
   - Settlement flow (lock-batches + verifyAndSettleBatched) works on mainnet/testnet with real data.

5) **Deployment Safety**
   - CI builds pinned images; deploys are atomic with concurrency locks.
   - Prover artifacts are stored immutably and checksum-verified.

6) **Data & Retention**
   - Retention policy decided and implemented.
   - DB/Redis backup and restore runbook tested.

7) **Frontend Readiness**
   - Performance budget passed; accessibility checks done.
   - UX fallback for streamer/FX outages implemented or documented.

8) **Investor Demo Quality**
   - Landing page looks premium and cohesive.
   - Demo flow always succeeds (real or simulated commit).
   - Investor story and traction are visible and credible.

---

# References

- `TODO.md`
- `backend/TODO.md`
- `backend/worker/TODO.md`
- `frontend/TODO.md`
- `streamer/TODO.md`
- `relayer/TODO.md`
- `hedger/TODO.md`
- `prover/TODO.md`
- `contracts/zen/TODO.md`
- `README.md` and per-service `README.md` files.
