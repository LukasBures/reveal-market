# Reveal Market Platform

Reveal Market delivers a zero-knowledge prediction stack that regulated venues can actually ship: a FastAPI surface with security hardening, an ingestion/automation worker, investor-grade Next.js experiences, and Groth16-ready Foundry contracts. This mono-repo houses every layer so due diligence, security reviews, and automation live in one place.

Follow progress on X: [@RevealMarket](https://x.com/RevealMarket).

Horizen chain support docs: https://docs.goldsky.com/chains/horizen

---

## Repository Map

| Directory | Purpose | Highlights |
| --- | --- | --- |
| `backend/api` | FastAPI service for markets, settlements, and partner endpoints. | Trusted-host & CORS controls, CSP/HSTS middleware, Redis caching, pytest suite, docker health probe. |
| `backend/worker` | Async ingestion + optional on-chain automation. | Alembic migrations at boot, structured logging, Polymarket + on-chain sync, pytest suite. |
| `frontend/` | Investor-facing Next.js property. | SEO metadata helpers, CSP headers, sitemap/robots, Vitest coverage, marketing-ready components, zero mock fallbacks. |
| `contracts/zen` | Foundry workspace for the Horizen deployment. | zk-ready settlement events, Forge tests/fuzzing, run scripts, roadmap for Groth16 verifier. |
| `contracts/polygon` | Foundry workspace for the Polygon deployment (LP vault, hedging plumbing). | Self-contained deps, hardened LP vault with extensive tests, gas checks, and run scripts. |
| `prover/` | Groth16 prover + circuit artifacts. | SnarkJS-backed witness + proof generation, heartbeat endpoint, and helper scripts for refreshing proving/verifying keys (fails fast if the compiled artifacts aren’t mounted so only real proofs are ever produced). |
| `hedger/` | Off-chain hedger + settlement orchestrator. | FastAPI admin API, Prometheus metrics, exposure + risk ledger, Redis idempotency/locks, slippage-gated hedging/unwinds, settlement payload builder from stored commits. |
| `price-streamer/` | Polymarket price ingest + SSE fanout with FX support. | Streams CLOB ticks + optional RTDS crypto feed, applies worsen/haircut/rake server-side, caches in Redis, serves `/stream` SSE + `/history` for charts. |
| `backend/api` + `frontend` + `contracts/zen` | Signed pricing + on-chain enforcement. | API signs ABI-packed quotes (`QUOTE_V1`, chainid, market, wallet, outcome, stake_wei, fx_scaled, expiry, quoteId), frontend requests quotes with those fields and submits `commitWithQuote`, contracts enforce signatures/replay/expiry with `pricingSigner`. |

Additional docs live in each directory’s README.

---

## Current Capabilities

- **FastAPI surface area** – `/markets`, `/categories/{slug}`, `/markets/suggest`, `/proofs`, and `/health` are live today with CSP/HSTS/COOP hardening, schema-based request/response models, Redis-backed caching (schema-tag aware), and Prometheus metrics. The API also publishes structured request metrics into Redis so `/health/heartbeats` immediately surfaces slow requests or cache-miss spikes.
- **Ingestion/automation worker** – The worker runs Alembic migrations on boot, streams active Polymarket markets, prefetches existing rows to minimize Postgres roundtrips, writes sanitized payloads into Postgres + Redis, and invalidates tagged caches per event/category/resolution. It exposes batch stats, publishes heartbeats, hydrates featured caches, and queues Groth16 proof jobs and AI summary jobs when enabled.
- **Frontend** – The Next.js 15 app consumes the live API for every page render, enforces the same security headers, emits sitemap/robots automatically, and ships fully responsive marketing + docs surfaces. Linting, type-checking, and production builds run in CI and require a reachable backend stack before they start.
- **Contracts** – Foundry projects compile/test (unit + fuzz) the RevealMarket suite today, emitting `MarketResolved` data and rake metadata the backend can ingest. Deployment scripts capture manifests, and `forge test`/`forge snapshot` guard gas usage in CI. Both `contracts/zen` (Horizen) and `contracts/polygon` (Polygon LP vault + hedging) run via shared wrappers.
  - Generate custom error selectors via `python scripts/generate_error_selectors.py > contracts/cache/errors.json` (CI runs this before contract tests) so frontend/backend decoders stay in sync with Solidity errors.
- **Groth16 prover** – The prover service verifies that circuit artifacts exist before boot, exposes `/healthz`/`/metrics`, and processes settlement proof jobs the worker submits. `prover/circuits/generate_keys.sh` keeps artifacts fresh for demos and deployments.
  - Use `prover/cmd/verify-artifacts` to fail fast when artifacts are missing and rely on `/metrics`/expvar for proof counts/latency/active requests.
- **Hedger** – FastAPI admin surface with Prometheus metrics; tracks exposures (YES/NO), FX haircuts, risk limits, and emits buy/sell/unwind hedge instructions with slippage gates. Uses Redis locks/idempotency + DB offsets for replay safety, hydrates state from Postgres on restart, and builds prover payloads from stored commits/outcomes before marking markets resolved. Metrics include exposures, coverage, LP utilization, float, PnL placeholders, event lag, hedge executions, and settlement/prover latency.
- **Tooling & CI** – `./backend/run_tests.sh`, `frontend/run_tests.sh`, `contracts/run_local.sh full`, and `./run_tests.sh` are the same flows used in CI (`.github/workflows/ci.yml`). Docker Compose stacks (`./run_local.sh`, `./run_prod.sh`) wire API, worker, frontend, Postgres, Redis, and prover together with health probes so you can test the exact production topology locally.
- **FX & pricing limits** – Price-streamer sources ZEN/USDT from Binance WS (5s stale threshold) with Coingecko fallback; `/fx/zen-usd` exposes the latest quote + staleness. API/hedger reject stale FX and cap per-quote stakes (100 ZEN surfaced in the UI) with haircut/worsen/rake applied server-side. Set `STREAMER_CORS_ALLOW_ORIGINS` to your frontend origin when consuming `/stream` and `/history` from the browser.
- **Signed quotes enforced on-chain** – Quotes now bind chain id, market address, wallet, outcome, stake (wei), FX (1e8), expiry, and quoteId to a `pricingSigner`. The API signs this ABI-packed digest, the frontend requests quotes with those fields and submits `commitWithQuote`, and `RevealMarket` rejects mismatched/expired/replayed quotes.
- **Bet caps (off-chain)** – UI stake inputs clamp to 100 ZEN; API enforces `RM_MAX_STAKE_ZEN`, and hedger mirrors per-commit caps. Per-user/per-market caps are planned on-chain (see service TODOs) and will be mirrored off-chain first.

---

## Investment Snapshot

- **Outcome markets as yield** – Treasury-first rake capture and institutional fee-sharing make markets balance-sheet friendly instead of speculative emissions.
- **Horizen-first + zk moat** – Reveal is the only team operating commit/reveal + Groth16 infrastructure on Horizen’s EVM, giving partners a head start before large CEX integrations land.
- **Compliance-grade delivery** – Segregated services, JSON logging, Prometheus metrics, and security headers keep regulators and auditors aligned from day one.

### Traction

- Multi-service Docker stack ships with health checks, migrations, and hardened logging.
- Investor docs (Next.js) expose sitemap/robots, JSON-LD markup, and legal pages for SEO + AI crawlers.
- Contracts emit `MarketResolved` telemetry today; Foundry tests cover 70+ cases including fuzz/security.

---

## Security & Observability

- **API/Worker** – Strict HSTS, CSP, COOP/CORP, Referrer-Policy, and Trusted Host filters are enabled by default. Health checks are native Python scripts, not cURL hacks.
- **Frontend** – Production headers mirror backend policies; sitemap + robots automatically enumerate investor pages. All docs/legal pages declare canonical URLs and metadata via `lib/seo.ts`. The App Router fetchers now always hit the live API; there are no mock toggles in production.
- **Logging** – Unified formatter across services (`timestamp | LEVEL | logger | file:line | event | request_id`). Optional rotating file output for regulated deployments, structured JSON-LD for site-wide schema.
- **Edge canonicalization** – Caddy terminates TLS, forces HTTP→HTTPS, and redirects `www.` (and any stray HTTP hostnames) to `https://revealmarket.xyz` so crawlers only ever see the canonical domain.
- **SLA telemetry** – Every request logs latency buckets, bytes sent, and cache hit/miss data. The API publishes aggregated metrics to Redis and exposes a live dashboard at `/health/heartbeats`, so you can verify worker/API heartbeats, cache hit rates, and average latency in one place.
- **Tests** – `./backend/run_tests.sh` (pytest, 4-way xdist by default), `./frontend/run_tests.sh` (lint + Next build, fails fast if the API is unreachable), `cd contracts && forge test`. CI (`.github/workflows/ci.yml`) runs all three jobs in parallel and boots the backend stack before frontend tests; `./run_tests.sh` performs the same sequence locally (backend → frontend → contracts → prover) and now checks prover artifacts via `prover/cmd/verify-artifacts`.

---

## Quick Start

```bash
# Backend (Python 3.12 + uv)
uv sync --project backend/api --extra dev --no-install-project
uv sync --project backend/worker --extra dev --no-install-project
./backend/run_tests.sh

# Frontend (Node 20 LTS)
nvm use # respects repo-root .nvmrc, falls back to Node 20
cd frontend && npm install && npm run dev

# Contracts (runs both Base + Zen workspaces)
cd contracts && ./run_tests.sh

# Hedger (FastAPI + exposure/hedging engine)
uv sync --project hedger --extra dev --no-install-project
cd hedger && ./run_tests.sh

# Price Streamer (WS/SSE service)
uv sync --project price-streamer --extra dev --no-install-project
cd price-streamer && ./run_tests.sh
# If calling /stream or /history from the browser, set STREAMER_CORS_ALLOW_ORIGINS to your frontend origin (e.g., http://localhost:3000).

# Full docker stack (API, worker, frontend, Postgres, Redis, prover)
./run_local.sh
```

`./backend/run_tests.sh` now fans pytest across four workers (API, shared modules, worker). Override the fan-out via `PYTEST_WORKER_COUNT=<n>` whenever you need to dial concurrency up or down.

When running `npm run build`, `frontend/run_tests.sh`, or `./run_tests.sh`, ensure the backend stack (API + worker + Postgres + Redis + prover) is reachable at `/health`; frontend builds abort immediately if the API cannot be contacted.

The Dockerized frontend serves the prebuilt `.next/standalone` bundle, so it no longer runs `npm install` or `npm run dev` on container start. Re-run `./run_local.sh` after frontend changes or use `cd frontend && npm run dev` for hot reload.

### Groth16 prover setup / current circuit status

- Run `bash prover/circuits/generate_keys.sh` once (or whenever you regenerate circuits) so `settlement_final.zkey` and the `settlement_js/` assets exist under `prover/circuits/build`. The script now computes proving/verifying key hashes, derives the 10-signal circuit hash, and writes deploy config to `contracts/cache/settlement-vk.json` + `contracts/zen/cache/settlement-vk.json` / `prover/circuits/build/settlement_deploy.json`. The prover container mounts those paths read-only; without them it refuses to start.
- Both `./run_local.sh` and `./run_prod.sh` call a built-in artifact check before launching Docker. If the files are missing, `run_prod.sh` automatically executes `generate_keys.sh`; set `SKIP_PROVER_CHECK=true` only when you have already mounted known-good artifacts.
- The prover exposes `http://localhost:8085/healthz`, `/metrics`, and `/api/v1/proofs/settlement`. After the stack is up, hit `/healthz` or send a sample payload (see `prover/README.md`) to confirm witness generation + `rapidsnark` proofs succeed. Public signals are fixed at 10: `[merkleRoot, marketId, winningOutcomeId, totalEscrow, totalLiability, rakeBps, poolYes, poolNo, circuitHash, padding(0)]`.

### Live market ingestion

- Set `RM_POLYMARKET_API_BASE=https://gamma-api.polymarket.com`, `RM_POLYMARKET_NETWORK=137`, `RM_POLYMARKET_ACTIVE_FILTER=true`, `RM_POLYMARKET_ARCHIVED_FILTER=false`, and `RM_POLYMARKET_CLOSED_FILTER=false` so the worker ingests only active Polygon markets. Leave `RM_MARKET_CATEGORY_ALLOWLIST` empty until you want to curate narratives.
- Tune Gamma rate limiting via `RM_POLYMARKET_RATE_LIMIT_REQUESTS` / `RM_POLYMARKET_RATE_LIMIT_WINDOW_SECONDS` when running multiple workers so you stay under Polymarket’s quotas.
- The worker automatically retries failed Polymarket syncs with exponential backoff (configure `RM_POLYMARKET_SYNC_MAX_ATTEMPTS`, `RM_POLYMARKET_SYNC_RETRY_BACKOFF_SECONDS`, and `RM_POLYMARKET_SYNC_RETRY_BACKOFF_MAX_SECONDS` if you need longer windows during outages).
- Keep `RM_RUN_MIGRATIONS_ON_STARTUP=true` so the worker auto-applies schema updates (e.g., the `markets.tags` column) before syncing.
- Commitments/settlements schema and Merkle/prover payload builders now exist in the worker; wire your on-chain ingestion to persist commitments (ticket hash/leaf/amount/outcome) and settlement aggregates (root, pools, liability, rake, winning outcome, circuit hash) so proof generation can run end-to-end.
- After changing env, restart the worker (`./run_local.sh worker` or `docker compose restart worker`) so it repulls the Gamma feed, writes fresh rows to Postgres, and refreshes Redis caches the frontend reads.
- `/markets` search and the `/markets/suggest` endpoint are backed by a Postgres full-text index (`markets_search_vector_idx`). Run `alembic upgrade head` (or restart the worker/API containers) whenever new migrations land so the index stays current. Client-side search suggestions now flow through a Next.js API route that reuses this backend endpoint, so missing indexes immediately show up in the UI.
- The stack never seeds mock data—every response flows from Polymarket via the worker. Keep the worker running (Docker restarts it automatically) so it continues syncing markets into Postgres/Redis.
- Flip `RM_RATE_LIMIT_ENABLED=true` (optionally tune `RM_RATE_LIMIT_REQUESTS_PER_WINDOW` / `RM_RATE_LIMIT_WINDOW_SECONDS`) to enable the built-in Redis-backed rate limiter so public traffic can’t starve the ingestion path. Use `RM_RATE_LIMIT_WHITELIST` for trusted VPNs/ops hosts.
- The worker keeps recently resolved markets for 24h (`RM_RESOLVED_RETENTION_SECONDS`) and materializes featured categories into Redis so `/categories/<slug>` responds instantly without hitting Gamma/Polygon.

Environment variables follow the `RM_` prefix (see each service README). Security headers can be tuned with `RM_ALLOWED_HOSTS`, CORS lists, and CSP overrides.

---

## Engagement Paths

- **Exchanges & Brokerages** – Deploy the API-only slice behind your firewall, feed liquidity via our worker, or white-label the Next.js storefront. All tiers ship with the same server action + cache tagging strategy the marketing site uses in production.
- **Liquidity Providers & DAOs** – Tap fee-sharing programs, structured webhooks, and rake analytics to model outcome-market exposure.
- **Strategic Investors** – Access diligence packets (contracts, backend, frontend), roadmap briefs, and treasury participation details via `hello@revealmarket.xyz`.

Let’s build prediction markets institutions actually trust. The prover bundled in this repo boots a Groth16 pipeline (Node witness generator + `rapidsnark`) and halts startup if the compiled assets under `prover/circuits/build` are missing or invalid. Run `prover/circuits/generate_keys.sh` to refresh `settlement_final.zkey` and `settlement_js/` before claiming production-grade zk support.
