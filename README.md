# Reveal Market Platform

Reveal Market delivers a zero-knowledge prediction stack that regulated venues can actually ship: a FastAPI surface with security hardening, an ingestion/automation worker, investor-grade Next.js experiences, and Groth16-ready Foundry contracts. This mono-repo houses every layer so due diligence, security reviews, and automation live in one place.

Follow progress on X: [@RevealMarket](https://x.com/RevealMarket).

Horizen chain support docs: https://docs.goldsky.com/chains/horizen
Default testnet: Horizen Testnet (chain id `2651420`, RPC `https://horizen-testnet.rpc.caldera.xyz/http`, explorer `https://horizen-testnet.explorer.caldera.xyz`).

---

## Repository Map

| Directory | Purpose | Highlights |
| --- | --- | --- |
| [`backend/api`](backend/api/README.md) | FastAPI service for markets, settlements, and partner endpoints. | Trusted-host & CORS controls, CSP/HSTS middleware, Redis cache hydration + tag invalidation, signed pricing quotes, Prometheus/pytest suite, docker health probe. |
| [`backend/worker`](backend/worker/README.md) | Async ingestion + optional on-chain automation. | Alembic migrations at boot, Polymarket+CLOB ingest, Goldsky/ConditionalTokens resolution snapshots + cache priming, prover hooks, structured logging, pytest suite. |
| [`frontend/`](frontend/README.md) | Investor-facing Next.js property. | SEO metadata helpers, CSP headers, sitemap/robots, Vitest coverage, streaming odds/FX, marketing-ready components, zero mock fallbacks. |
| [`contracts/zen`](contracts/zen/README.md) | Foundry workspace for the Horizen deployment. | Commit/reveal markets with Poseidon batch roots (BATCH_SIZE=256), protocol liability caps, rake skimmed at commit, Groth16 verifier + circuit hash enforcement, forge tests/fuzz/gas snapshots. |
| `contracts/polygon` | Foundry workspace for the Polygon deployment (LP vault, hedging plumbing). | Self-contained deps, hardened LP vault with extensive tests, gas checks, and run scripts. |
| [`prover/`](prover/README.md) | Groth16 prover + circuit artifacts. | rapidsnark-backed proofs with artifact gate, heartbeat/metrics, CLI to verify artifacts, integration tests, no mock mode. |
| [`hedger/`](hedger/README.md) | Off-chain hedger + settlement orchestrator. | FastAPI admin API, Prometheus metrics, exposure + risk ledger, Redis idempotency/locks, slippage-gated hedging/unwinds, settlement payload builder from stored commits. |
| [`streamer/`](streamer/README.md) | Polymarket price ingest + SSE/WS fanout with FX support. | Streams CLOB ticks + optional RTDS crypto feed, applies worsen% to display prices (haircut/rake are downstream pricing inputs), caches in Redis, serves `/stream` SSE + `/history` for charts. |
| [`relayer/`](relayer/README.md) | FastAPI relayer for `commitOnBehalf`/`claim`. | Durable queue with fee bumps, health/metrics, bearer auth option, Horizen Testnet defaults. |
| `backend/api` + `frontend` + `contracts/zen` | Signed pricing + relayed commit auth. | API signs ABI-packed quotes (`QUOTE_V1`, chainid, market, wallet, outcome, stake_wei, fx_scaled, expiry, quoteId), consumes them in `/trade/commit`, and the relayer submits `commitOnBehalf` → `commitWithAuthorization` enforced by the authorization signer. |

Additional docs live in each directory’s README.

### Component documentation + TODOs
- Backend API – [`backend/api/README.md`](backend/api/README.md) / [`backend/TODO.md`](backend/TODO.md)
- Worker – [`backend/worker/README.md`](backend/worker/README.md) / [`backend/TODO.md`](backend/TODO.md)
- Frontend – [`frontend/README.md`](frontend/README.md) / [`frontend/TODO.md`](frontend/TODO.md)
- Contracts (Zen) – [`contracts/zen/README.md`](contracts/zen/README.md) / [`contracts/zen/TODO.md`](contracts/zen/TODO.md)
- Streamer – [`streamer/README.md`](streamer/README.md) / [`streamer/TODO.md`](streamer/TODO.md)
- Hedger – [`hedger/README.md`](hedger/README.md) / [`hedger/TODO.md`](hedger/TODO.md)
- Relayer – [`relayer/README.md`](relayer/README.md) / [`relayer/TODO.md`](relayer/TODO.md)
- Prover – [`prover/README.md`](prover/README.md) / [`prover/TODO.md`](prover/TODO.md)

---

**Component Overviews**
- **Backend API** (`backend/api`) – FastAPI surface with Redis-tagged caches, normalized market/outcome/tag/clob metadata tables, signed QUOTE_V1 pricing, health/metrics, rate limiting, and startup migrations; tests via `./backend/run_tests.sh`.
- **Worker** (`backend/worker`) – Async Polymarket Gamma ingest with retries/rate limits, Goldsky + Conditional Tokens resolution ledger, cache priming/invalidation, prover receipt requests, heartbeats/batch stats, retention metrics; runs inside the same test harness.
- **Frontend** (`frontend`) – Next.js 15 App Router with streaming odds/FX, SSR data fetches aligned to backend cache tags, signed-quote flow via `/trade/commit` (API + relayer), CSP/HSTS headers, Vitest suites for hero/nav/featured/search/market cards/FX; lint/test/build via `frontend/run_tests.sh`.
- **Contracts (Zen)** (`contracts/zen`) – Fixed-ticket commit/reveal markets (`RelayerEscrow`, `ProtocolPool`, `MarketFactory`, `RevealMarket`, Groth16 `Verifier`) with Poseidon batch roots (BATCH_SIZE=256, depth 8), `lockBatches` + `verifyAndSettleBatched`, rake skimmed at commit, circuit hash enforced at settle, protocol liability caps, forge tests + gas snapshots via `contracts/run_tests.sh`; use `contracts/zen/run_local.sh full` for fuzz/coverage.
- **Contracts (Polygon)** (`contracts/polygon`) – LP vault/hedging workspace with its own scripts/tests; run with the same `contracts/run_tests.sh`.
- **Streamer** (`streamer`) – FastAPI SSE/WS for Polymarket CLOB + RTDS + Binance FX with REST fallback, Redis cache/history, staleness guards, optional HMAC/access tokens, Prometheus metrics; tests via `streamer/run_tests.sh`.
- **Hedger** (`hedger`) – FastAPI admin API with exposure/risk ledger, FX/slippage caps, Redis locks/idempotency, hedging/unwind instructions, settlement/prover payload builder, metrics; tests via `hedger/run_tests.sh`.
- **Relayer** (`relayer`) – FastAPI relayer for `commitOnBehalf`/`claim` with retries/backoff or durable queue + fee bumps, health/metrics/admin DLQ endpoints; tests via `relayer/run_tests.sh`.
- **Prover** (`prover`) – Go rapidsnark service with artifact gate, witness/proof pipeline, metrics/pprof, integration tests; check artifacts via `prover/cmd/verify-artifacts` and run tests with `prover/run_tests.sh`.

## Database Schema (Postgres)

- **Migrations + head** – Single Alembic head at `backend/migrations/versions/0001_initial_schema.py`; helper in `backend/shared/migrations.py` applies/inspects revisions. `schema_versions` mirrors `alembic_version` for internal tracking.
- **Markets & resolution** – `markets` holds unique `event_id`/`market_address`, status (commit/locked/settled/cancelled), metadata/pricing knobs, and timing fields with indexes on status+category, slug, condition_id, and event_id. Outcomes/tags/clob tokens and Gamma metadata are normalized into `market_outcomes`, `market_tags`, `market_clob_tokens`, and `market_gamma_metadata/events`; JSON columns for outcomes/tags/clob IDs/extra_data were removed. `resolutions` stores payout vectors per `condition_id` (optional `market_id`/`event_id`), on-chain tx metadata, and `checked_at`; indexes on block_number, market_id, event_id.
- **Quotes & factory events** – `quotes` ledger enforces caps/expiry (stake_zen/wei, fx_scaled, zen_usd, market/user/wallet/outcome/chain_id, status issued/consumed/expired, expires_at). `factory_events` mirrors on-chain factory txs (factory/market address, event name, tx hash, block info, payload).
- **Commit/reveal + settlement** – `commitments` capture market_id, user_address, outcome_id, amount_wei, salt, ticket_hash, Poseidon leaf, leaf_index with sibling hashes in `commitment_merkle_paths`. `settlements` stores `batch_roots` + `batch_counts` (depth-8 Poseidon roots, 256 leaves each) and optionally `merkle_root` for single-batch markets, plus pool/liability totals, rake, winning_outcome_id, circuit_hash, proof status/request; `settlement_receipts` stores prover outputs per market/request; `proof_jobs` tracks prover task lifecycle.
- **Ops/analytics tables** – `hedger_treasury_snapshots`, `market_stats` (unique market_id+date), `hedger_positions`, `fx_prices`, `rate_limits`, `webhooks_outbox`, `ingestion_jobs`, `audit_logs`, `wallet_sessions`, `chains` with supporting indexes for common lookups (e.g., rate_limits scope+key, webhooks status).
- **Hedger service DB (separate URL)** – `hedger/app/storage.py` defines audit/recovery tables: `hedger_commits`, `hedger_hedge_actions` (includes unwind flag + response payloads), `hedger_settlements`, `hedger_offsets` (stream replay), `hedger_resolved_markets`, and a mirrored `hedger_treasury_snapshots`. Created via `HedgerRepository.create_schema()` against `RM_DATABASE_URL`.
- **Hardening** – FKs now link commitments/settlements/quotes/receipts/hedger positions/treasury snapshots to markets, status columns carry CHECK constraints, wallet/user lookup indexes were added (plus partial index on issued quotes by expiry, GIN on `markets.tags`), updated_at triggers guard non-ORM writes, and `market_outcomes` normalizes labels/prices for server-side querying.

---

## Current Capabilities

- **FastAPI surface area** – `/markets`, `/categories/{slug}`, `/markets/suggest`, `/proofs`, and `/health` are live today with CSP/HSTS/COOP hardening, schema-based request/response models, Redis-backed caching (schema-tag aware), startup/interval cache hydrators, and Prometheus metrics. Resolved markets are cached for at most 12 hours after `resolved_at`; when Redis is down, endpoints bypass cache cleanly and avoid tagging.
- **Ingestion/automation worker** – The worker runs Alembic migrations on boot, streams active Polymarket markets (with optional CLOB enrichment), prefetches existing rows to minimize Postgres roundtrips, writes sanitized payloads into Postgres + Redis, and invalidates tagged caches per event/category/resolution. It persists Goldsky/ConditionalTokens resolution snapshots (backfills gaps), exposes batch stats, publishes heartbeats, hydrates featured caches (first 150 markets for homepage/categories), and queues Groth16 proof jobs when enabled.
- **Frontend** – The Next.js 15 app consumes the live API for every page render, enforces the same security headers, emits sitemap/robots automatically, and ships fully responsive marketing + docs surfaces. The homepage hero now ships category pills + search suggestions (with artwork) and auto-loads five pages (30 each) before showing a manual “load more”; grouped markets are rendered as a single card with aggregated volume/liquidity by default. CI runs lint/test/build; use `FRONTEND_REQUIRE_API=true` in `frontend/run_tests.sh` if you want a strict `/health` check before builds.
- **Contracts** – Foundry projects compile/test (unit + fuzz) the RevealMarket suite today, emitting `MarketResolved` data and rake metadata the backend can ingest. The Horizen deployment locks Poseidon batch roots (BATCH_SIZE=256) and settles via `verifyAndSettleBatched` when multiple batches are present. Deployment scripts capture manifests, and `forge test`/`forge snapshot` guard gas usage in CI. Both `contracts/zen` (Horizen) and `contracts/polygon` (Polygon LP vault + hedging) run via shared wrappers.
  - Generate custom error selectors via `uv run --with eth-utils --with "eth-hash[pysha3]" python scripts/generate_error_selectors.py > contracts/cache/errors.json` whenever Solidity errors change so frontend/backend decoders stay in sync.
- **Groth16 prover** – The prover service verifies that circuit artifacts exist before boot, exposes `/healthz`/`/metrics`, and processes settlement proof jobs the worker submits. `prover/circuits/generate_keys.sh` keeps artifacts fresh for demos and deployments.
  - Use `prover/cmd/verify-artifacts` to fail fast when artifacts are missing and rely on `/metrics`/expvar for proof counts/latency/active requests.
- **Hedger** – FastAPI admin surface with Prometheus metrics; tracks exposures (YES/NO), FX haircuts, risk limits, and emits buy/sell/unwind hedge instructions with slippage gates. Uses Redis locks/idempotency + DB offsets for replay safety, hydrates state from Postgres on restart, and builds prover payloads from stored commits/outcomes before marking markets resolved. Metrics include exposures, coverage, LP utilization, float, PnL placeholders, event lag, hedge executions, and settlement/prover latency.
- **Price streamer** – FastAPI SSE/WS fanout that ingests Polymarket CLOB WS + RTDS feeds, hydrates token IDs via REST, applies worsen% to display prices, caches ticks/history in Redis, and serves `/stream`, `/stream/ws`, `/history`, and `/fx/zen-usd[c|t]` with Binance WS first, Binance REST + CryptoCompare fallback. Presets pin CORS origins and public/internal streamer hosts to the frontend so WSS upgrades work locally and in prod.
- **Tooling & CI** – `./backend/run_tests.sh`, `frontend/run_tests.sh`, `contracts/zen/run_local.sh`, `contracts/polygon/run_local.sh`, and `./run_tests.sh` map to CI in `.github/workflows/cicd.yml`. Docker Compose stacks (`./run_local.sh`, `./run_prod.sh`) wire API, worker, frontend, Postgres, Redis, and prover together with health probes so you can test the exact production topology locally.
- **FX & pricing limits** – Price-streamer sources ZEN/USDT from Binance WS (5s stale threshold) with Binance REST then CryptoCompare HTTP fallback; `/fx/zen-usd` exposes the latest quote + staleness. The API hardcodes FX to the streamer endpoint (`http://streamer:8100/fx/zen-usd`; update `app/pricing.py` if your host/port differs) and ignores env overrides. API/hedger reject stale FX and enforce configurable caps; the UI uses a fixed 0.1 ZEN ticket size. Haircut/worsen/rake apply in pricing logic. Set `STREAMER_CORS_ALLOW_ORIGINS` to your frontend origin when consuming `/stream` and `/history` from the browser.
- **Signed quotes (off-chain enforcement)** – Quotes bind chain id, market address, wallet, outcome, stake (wei), FX (1e8), expiry, and quoteId to a `pricingSigner`. The API ignores client FX, signs this ABI-packed digest, enforces per-user/per-market caps via the quote ledger, and consumes quotes during `/trade/commit`. On-chain enforcement is via CommitAuth signatures in `commitWithAuthorization`.
- **Bet caps (off-chain)** – UI stake inputs clamp to 0.1 ZEN; API enforces `RM_MAX_STAKE_ZEN`, and hedger mirrors per-commit caps. Per-user/per-market caps are planned on-chain (see service TODOs) and will be mirrored off-chain first.

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
- **SLA telemetry** – Every request logs latency buckets, bytes sent, and cache hit/miss data. The API publishes aggregated metrics to Redis and exposes a live dashboard at `/healthz/heartbeats`, so you can verify worker/API heartbeats, cache hit rates, and average latency in one place.
- **Rate limiting** – API rate limiting defaults on in non-dev environments; configure via `RM_RATE_LIMIT_ENABLED`, `RM_RATE_LIMIT_REQUESTS_PER_WINDOW`, `RM_RATE_LIMIT_WINDOW_SECONDS`, and `RM_RATE_LIMIT_WHITELIST`.
- **Tests** – `./backend/run_tests.sh` (pytest, 4-way xdist by default), `./frontend/run_tests.sh` (lint + build; set `FRONTEND_REQUIRE_API=true` for a strict `/health` check), `cd contracts && ./run_tests.sh`. CI (`.github/workflows/cicd.yml`) runs the suites in parallel; `./run_tests.sh` runs backend, hedger, streamer, relayer, frontend, contracts, and prover sequentially, and the prover stage runs `check_artifacts.sh`.

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
uv sync --project streamer --extra dev --no-install-project
cd streamer && ./run_tests.sh
# If calling /stream or /history from the browser, set STREAMER_CORS_ALLOW_ORIGINS to your frontend origin (e.g., http://localhost:3000).

# Full docker stack (API, worker, frontend, Postgres, Redis, prover)
./run_local.sh
```

`./backend/run_tests.sh` now fans pytest across four workers (API, shared modules, worker). Override the fan-out via `PYTEST_WORKER_COUNT=<n>` whenever you need to dial concurrency up or down.

When running `npm run build`, `frontend/run_tests.sh`, or `./run_tests.sh`, keep the backend stack (API + worker + Postgres + Redis + prover) reachable at `/health`. Use `FRONTEND_REQUIRE_API=true` in `frontend/run_tests.sh` if you want an explicit preflight check before the build.

The Dockerized frontend serves the prebuilt `.next/standalone` bundle, so it no longer runs `npm install` or `npm run dev` on container start. Re-run `./run_local.sh` after frontend changes or use `cd frontend && npm run dev` for hot reload.

### Groth16 prover setup / current circuit status

- Run `bash prover/circuits/generate_keys.sh` once (or whenever you regenerate circuits) so `settlement_final.zkey` and the `settlement_js/` assets exist under `prover/circuits/build`. The script now computes proving/verifying key hashes, derives the 10-signal circuit hash, and writes deploy config to `contracts/cache/settlement-vk.json` + `contracts/zen/cache/settlement-vk.json` / `prover/circuits/build/settlement_deploy.json`. The prover container mounts those paths read-only; without them it refuses to start.
- Both `./run_local.sh` and `./run_prod.sh` call a built-in artifact check before launching Docker. If files are missing, the scripts attempt to sync from `prover/artifacts` or download via `PROVER_ARTIFACTS_URL`; otherwise they exit with instructions to run `prover/circuits/generate_keys.sh`. Set `SKIP_PROVER_CHECK=true` only when you have already mounted known-good artifacts.
- The prover exposes `http://localhost:8085/healthz`, `/metrics`, and `/api/v1/proofs/settlement`. If `PROVER_SHARED_SECRET` is set, include `X-Prover-Secret` on proof requests. After the stack is up, hit `/healthz` or send a sample payload (see `prover/README.md`) to confirm witness generation + `rapidsnark` proofs succeed. Public signals are fixed at 10: `[merkleRoot, marketId, winningOutcomeId, totalEscrow, totalLiability, rakeBps, poolYes, poolNo, circuitHash, padding(0)]` where `merkleRoot` is the per-batch Poseidon root; multi-batch markets submit one proof per batch and settle via `verifyAndSettleBatched`.

### Live market ingestion

- Set `RM_POLYMARKET_API_BASE=https://gamma-api.polymarket.com`, `RM_POLYMARKET_ACTIVE_FILTER=true`, `RM_POLYMARKET_ARCHIVED_FILTER=false`, and `RM_POLYMARKET_ONLY_OPEN_MARKETS=true` so the worker ingests only active markets.
- The worker now ingests via Gamma’s `/events`, flattening embedded markets and assigning `group_slug` to the event slug when an event has multiple markets. The API caches up to 150 markets (first page) for instant homepage/category loads and defaults to `coalesce_groups=1` so grouped events surface once with aggregated volume/liquidity.
- Tune Gamma rate limiting via `RM_POLYMARKET_RATE_LIMIT_REQUESTS` / `RM_POLYMARKET_RATE_LIMIT_WINDOW_SECONDS` when running multiple workers so you stay under Polymarket’s quotas.
- The worker automatically retries failed Polymarket syncs with exponential backoff (configure `RM_POLYMARKET_SYNC_MAX_ATTEMPTS`, `RM_POLYMARKET_SYNC_RETRY_BACKOFF_SECONDS`, and `RM_POLYMARKET_SYNC_RETRY_BACKOFF_MAX_SECONDS` if you need longer windows during outages).
- Keep `RM_RUN_MIGRATIONS_ON_STARTUP=true` so the worker auto-applies schema updates (e.g., the `markets.tags` column) before syncing.
- Resolution snapshots are fetched from Goldsky (preferred) or Conditional Tokens RPC, stored in Postgres + Redis, and refreshed on a configurable interval; the worker logs gaps and backfills missing ledger rows.
- Commitments/settlements schema and Merkle/prover payload builders now exist in the worker; wire your on-chain ingestion to persist commitments (ticket hash/leaf/amount/outcome) and settlement aggregates (root, pools, liability, rake, winning outcome, circuit hash) so proof generation can run end-to-end. Proof requests start once the prover is configured (`RM_PROVER_BASE_URL`) and receipts are cached.
- After changing env, restart the worker (`./run_local.sh worker` or `docker compose restart worker`) so it repulls the Gamma feed, writes fresh rows to Postgres, and refreshes Redis caches the frontend reads.
- `/markets` search and the `/markets/suggest` endpoint are backed by a Postgres full-text index (`markets_search_vector_idx`). Run `alembic upgrade head` (or restart the worker/API containers) whenever new migrations land so the index stays current. Client-side search suggestions now flow through a Next.js API route that reuses this backend endpoint, so missing indexes immediately show up in the UI.
- The stack never seeds mock data—every response flows from Polymarket via the worker. Keep the worker running (Docker restarts it automatically) so it continues syncing markets into Postgres/Redis.
- Flip `RM_RATE_LIMIT_ENABLED=true` (optionally tune `RM_RATE_LIMIT_REQUESTS_PER_WINDOW` / `RM_RATE_LIMIT_WINDOW_SECONDS`) to enable the built-in Redis-backed rate limiter so public traffic can’t starve the ingestion path. Use `RM_RATE_LIMIT_WHITELIST` for trusted VPNs/ops hosts.
- Retention now reports metrics only; `RM_RESOLVED_RETENTION_SECONDS` gates how long “eligible for cleanup” markets are counted (nothing is deleted yet). Featured categories/suggestions are still prefetched into Redis so `/categories/<slug>` and `/markets/suggest` respond instantly without hitting Gamma/Polygon.

Environment variables follow the `RM_` prefix (see each service README). Security headers can be tuned with `RM_ALLOWED_HOSTS`, CORS lists, and CSP overrides.

---

## Engagement Paths

- **Exchanges & Brokerages** – Deploy the API-only slice behind your firewall, feed liquidity via our worker, or white-label the Next.js storefront. All tiers ship with the same server action + cache tagging strategy the marketing site uses in production.
- **Liquidity Providers & DAOs** – Tap fee-sharing programs, structured webhooks, and rake analytics to model outcome-market exposure.
- **Strategic Investors** – Access diligence packets (contracts, backend, frontend), roadmap briefs, and treasury participation details via the contact form on the site.

Let’s build prediction markets institutions actually trust. The prover bundled in this repo boots a Groth16 pipeline (Node witness generator + `rapidsnark`) and halts startup if the compiled assets under `prover/circuits/build` are missing or invalid. Run `prover/circuits/generate_keys.sh` to refresh `settlement_final.zkey` and `settlement_js/` before claiming production-grade zk support.




https://horizen-testnet.explorer.caldera.xyz/address/0xe928a273C83c80445adF89a880D0c7cc8Ee089b0?tab=tokens




  Step-by-step (single source of truth = artifacts submodule):

  1. Generate + stage artifacts: cd prover/circuits && bash export_artifacts.sh (writes to prover/artifacts/...).
  2. Commit/push the submodule: cd prover/artifacts && git status -> add/commit/push; then cd .. and git add prover/artifacts to update the pointer in the main repo.
  3. Deploy verifier from the vetted vk: use contracts/zen/cache/settlement-vk.json (populated by export/import) with your forge script ... Deploy.s.sol flow; set RM_VERIFIER_ADDRESS to the new verifier.
  4. Sync artifacts on any machine/CI: cd prover/circuits && bash import_from_artifacts.sh (copies vetted artifacts into prover/circuits/build and vk caches).
  5. Run services: mount prover/artifacts/prover/circuits/build (or run the import script) for the prover; restart worker/API with `RM_PROVER_BASE_URL` set and the funded signer/RPC envs.
  6. Validate alignment: cast call <verifier> "circuitHash()(bytes32)" must equal jq -r '.circuitHash' prover/circuits/build/settlement_hashes.json.
