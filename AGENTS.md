# Repository Guidelines

## Project Structure & Module Organization
- **backend/** – FastAPI API (`api/`) and ingestion/automation worker (`worker/`) sharing utilities in `backend/shared/`. Alembic migrations live in `backend/migrations/`. Each service has its own README describing security/logging/health probes.
- **contracts/** – Two Foundry workspaces (`contracts/zen`, `contracts/polygon`) with their own `src/`, `test/`, `script/` trees. `contracts/run_local.sh` and `contracts/run_tests.sh` orchestrate both.
- **frontend/** – Next.js 15 + TypeScript + Tailwind workspace powering the marketing/docs site. SEO helpers sit in `frontend/lib/seo.ts`; sitemap/robots and security headers are auto-generated via the app router.
- **streamer/** – FastAPI SSE/WS service for Polymarket CLOB + RTDS ingestion with Binance FX, Redis cache/pubsub, and Redis-backed history.
- **relayer/** – FastAPI relayer that queues and submits commit/claim/lock transactions.
- **hedger/** – FastAPI hedger for exposure/risk tracking, settlement orchestration, and admin APIs.
- **prover/** – Go-based Groth16 prover service with circuits/artifacts.

## Build, Test, and Development Commands
- `make api` / `make worker` / `make hedger` / `make streamer` / `make prover` / `make frontend` / `make caddy` – Build + run individual Docker services.
- `make test` – Runs `./run_tests.sh` (full sequential suite).
- `backend/run_tests.sh` – Uses `backend/api/.venv` + `backend/worker/.venv` (via `uv sync`) to run pytest (xdist, default 4 workers), OpenAPI snapshot checks, and mypy.
- `forge build`, `forge test` (inside `contracts/zen` or `contracts/polygon`) – Compile/test Solidity. `./run_local.sh [full]` in each workspace adds gas snapshot + optional fuzz/coverage; `contracts/run_local.sh` runs both.
- `npm run dev|build|start|lint|test` (inside `frontend/`) – Next.js workflows. `npm run test` executes Vitest + Testing Library.
- `cd streamer && ./run_tests.sh` – Validates Python 3.12, runs mypy, installs dev extras if missing, then runs pytest (xdist when available).
- `./run_local.sh` – Build + launch the stack with cached BuildKit by default (pass `--no-cache` for clean rebuilds).
- `./run_prod.sh` – Cached builds + detached compose; verifies prover artifacts before booting.
- `./run_tests.sh` – Sequential harness (backend → hedger → streamer → relayer → frontend → contracts/polygon → contracts/zen → prover). Frontend API reachability is enforced only when `FRONTEND_REQUIRE_API=true`.

## Coding Style & Naming Conventions
- Python: PEP 8, Black 120 cols, isort, Flake8 (`make fmt` / `pre-commit`).
- Solidity: `forge fmt`; contracts use UpperCamelCase types, lowerCamelCase storage, ALL_CAPS constants.
- Env vars are SCREAMING_SNAKE_CASE (see `.env.example`).

## Testing Guidelines
- Python: Pytest with `asyncio` plugin. Tests live under `backend/*/tests/` with `test_*.py`.
- Solidity: Forge tests per component (`*.t.sol`). Keep gas snapshots current (`forge snapshot`).
- Frontend: Vitest (`npm run test`) + ESLint (`npm run lint`).
- Expectation: all suites green before PR merge; aim for >90% coverage in contracts.

## Commit & Pull Request Guidelines
- Commits: imperative tense (`feat: add rake override`). Keep diffs scoped.
- PRs: include summary, testing evidence (`make test`, `npm run test`, `forge test`), linked issues, screenshots/logs when UI/API behavior changes.
- Never commit secrets; rely on `.env.example` placeholders.

## Security & Configuration Tips
- Store real RPC URLs, wallet keys, and API keys in secret managers. `.env.example` is reference-only.
- Verify smart-contract addresses/rake overrides before enabling auto on-chain operations.
- API + frontend ship strong CSP/HSTS/COOP/Permissions-Policy headers. Whitelist new domains before referencing external assets.
- Default chain is Horizen Testnet (chain id `2651420`, RPC `https://horizen-testnet.rpc.caldera.xyz/http`, explorer `https://horizen-testnet.explorer.caldera.xyz`). Keep frontend/backend/contract envs aligned when switching networks.
- Streamer presets pin public/internal hosts and CORS origins; align `STREAMER_PUBLIC_BASE_URL`/`NEXT_PUBLIC_PRICE_STREAMER_URL` with your frontend origin (HTTPS for WSS) and keep CORS lists tight even in dev.

## Agent-Specific Instructions
- Review `TODO.md`, `backend/TODO.md`, `backend/worker/TODO.md`, `contracts/TODO.md`, `contracts/zen/TODO.md`, `frontend/TODO.md`, `streamer/TODO.md`, `relayer/TODO.md`, `hedger/TODO.md`, and `prover/TODO.md` before large tasks; they capture prioritized work.
- Prefer existing helpers (e.g., `shared/onchain/`, `lib/seo.ts`) over introducing new frameworks.
- Maintain the unified logging format (`timestamp | LEVEL | logger | file:line | event | request_id`).
- When editing docs/marketing copy, ensure metadata (via `docsMetadata`/`buildMetadata`) stays accurate so sitemap/robots remain valid.
- Batch settlement is Poseidon-based (BN254): keep `BATCH_SIZE=256` and `MERKLE_DEPTH=8` aligned across contracts, prover, backend, and relayer helpers.
- Frontend tests/builds only enforce backend `/health` when `FRONTEND_REQUIRE_API=true`; otherwise they warn and proceed. Start the backend stack (or set `NEXT_PUBLIC_API_BASE_URL`) when you need a live API during builds.
- Global lint/tool settings live in repo-root `.flake8`, `.isort.cfg`, and `pyproject.toml` (Black/isort/flake8/pytest). Keep overrides centralized there.
- The bundled `prover` service now boots a real Groth16 pipeline (Node witness generation + `rapidsnark`) and refuses to start if required artifacts under `prover/circuits/build` are missing. `run_local.sh`/`run_prod.sh` can seed artifacts from `prover/artifacts` or `PROVER_ARTIFACTS_URL`; keep keys current before claiming production-grade zk.

## Agent Notes

### Backend (FastAPI + Worker)
- **Architecture** – API and worker share SQLAlchemy models, cache helpers, and logging utilities in `backend/shared/`. Alembic migrations live in `backend/migrations/` and can be invoked via `shared/migrations.py`. Docker images copy migrations so health probes can run `_ensure_schema()` safely.
- **API** – `backend/api/app/main.py` wires structured logging, Prometheus instrumentation, TrustedHost + CORS middleware, and security headers (CSP/HSTS/COOP). Lifespan runs migrations on boot. `/health` returns Postgres/Redis/Polymarket status; markets endpoints use Redis-tagged caches with startup/interval hydrators and clean bypass when Redis is down; resolution lookups persist Goldsky fallbacks; request metrics + API/worker heartbeats live in Redis; resolved markets expire from cache 12 hours after `resolved_at`. `app/security.py` manages header defaults. Market outcomes/tags/clob tokens/Gamma metadata are normalized tables (`market_outcomes`, `market_tags`, `market_clob_tokens`, `market_gamma_metadata/events`); legacy JSON columns were dropped.
- **API pricing & caps** – `/pricing/quote` ignores client FX and now always pulls FX from the streamer endpoint (`http://streamer:8100/fx/zen-usd`), enforcing per-user/per-market caps via the quote ledger, building and signing the QUOTE_V1 digest (`chain id`, `market address`, `wallet`, `outcome id`, `stake_wei`, `fx_scaled 1e8`, `expiry`, `quoteId`) with `RM_PRICING_SIGNER_PRIVATE_KEY`, and storing issued quotes. `/pricing/submit` revalidates signature, expiry, optional FX drift, and marks quotes consumed.
- **Health checks** – `app/health.py` now delegates each dependency check (DB, Redis ping, worker heartbeat, Polymarket reachability) to helper functions so flake8 stays green. Keep that structure when adding new dependencies.
- **Worker** – `backend/worker/app/main.py` pulls Polymarket feeds (optionally enriches with CLOB), persists markets + Goldsky/ConditionalTokens resolution snapshots, propagates schema tags, primes category/suggest caches, emits Redis heartbeats/batch stats, and can enqueue AI summaries + prover jobs when enabled. On-chain helpers (`maybe_create_onchain_market`) remain manual-only. Retention currently reports metrics only (no deletions). `worker/app/healthcheck.py` verifies Postgres connectivity for Docker. Logs mirror the API format.
- **Commitments + settlement** – Commitments hash with Poseidon and are locked via `lockBatches` into depth-8 batch roots; settlement proofs are generated per batch and submitted via `verifyAndSettleBatched` (single-batch markets still use `verifyAndSettle`).
- **Worker complexity hotspots** – `_apply_resolution`, `cleanup_resolved_markets`, and `process_once` are intentionally large and currently silenced with `# noqa: C901`. Prefer incremental refactors over new mega-functions when touching them.
- **Polymarket client** – `backend/worker/app/polymarket.py` normalizes Gamma payloads, has rate limiting/empty-page tolerance, and uses tenacity-backed retries for pagination; keep metrics wiring (empty/rate-limit/retry counters) intact when extending it. Default ingest now calls Gamma `/events`, flattening embedded markets and assigning `group_slug` to the event slug for multi-market events.
- **Prover reality** – `prover` strictly runs Groth16 generation (`rapidsnark` + the Circom artifacts under `prover/circuits/build`) using the batch settlement circuit (Poseidon depth-8, 256 leaves). The Docker image installs rapidsnark ahead of time, exposes `/healthz`, `/metrics`, and `/debug/pprof/*`, and the service exits with a fatal error if artifacts are missing or invalid. Keep the keys fresh and mount them into the container before shipping claims about zk attestations.
- **Testing defaults** – Pytest fan-out is pinned to four workers (API, shared modules, worker) unless `PYTEST_WORKER_COUNT` overrides; expect this concurrency when validating suites locally or in CI.

### Frontend (Next.js)
- **SEO/AI readiness** – Metadata centralised in `lib/seo.ts`. Every docs/legal/about page imports `docsMetadata` so canonical URLs + keywords stay consistent. `app/sitemap.ts`/`app/robots.ts` update automatically.
- **Security headers** – Configured in `next.config.mjs` (CSP, HSTS, Referrer/Permissions policies, COOP/CORP). GA/gtag origins are only allowed in production; update the CSP when adding external assets.
- **Testing** – Vitest + Testing Library cover hero CTA, DocsNav, MainNav, DocsLayout, featured markets pagination, search suggestions, and market cards. Keep tests updated when components change.
- **Data fetching** – `lib/api.ts` only fetches from FastAPI. Server actions (`app/actions/markets.ts`) power “Load more”, keeping cache tags intact. `/app/api/markets/suggest` proxies suggestions so client keystrokes never hit the backend twice.
- **Live ops badge** – The homepage no longer surfaces worker heartbeats or sync badges; data freshness stays internal even though structured logs still emit `fetchFeaturedMarkets:*` events for observability.

### Streamer (FastAPI SSE/WS)
- **Architecture** – `app/main.py` builds FastAPI with preset CORS origins/hosts, starts `DataStreamer` (Polymarket CLOB WS + RTDS + REST fallback) and `PriceStreamer` (Binance FX WS with REST/crypto-compare fallback), and exposes `/stream`/`/stream/ws`/`/history`/`/fx/*` plus `/metrics`.
- **State** – `StreamState` holds Redis connections, FX cache with priority (ws > rest), signing secret (optional HMAC), history limits, and asset refcounts; placeholder market_id subscriptions are swapped for concrete `clobTokenIds` when discovered.
- **Data ingest** – CLOB WS reconnects via `iter_ws`, REST poll hydrates token IDs and swaps placeholders, RTDS runs in a background thread with `PolymarketRTDSClient`; publish throttling dedups unchanged prices, with Redis pubsub + history trimming.
- **FX** – Binance WS is primary; staleness triggers REST refresh (Binance then CryptoCompare) with jump/bounds guards, single-connection pooling, and Prometheus gauges/counters for source/staleness/ws restarts.
- **Client expectations** – Browsers should pass `assets_ids` when possible; missing assets fall back to market_id with metrics; keep `STREAMER_CORS_ALLOW_ORIGINS` set to the frontend origin so SSE/WS upgrades succeed locally and in prod.

### Contracts (Foundry)
- `contracts/zen/src` houses RevealMarket, MarketFactory, ProtocolPool, RelayerEscrow, and Verifier; `contracts/polygon/src` houses BaseLpVault and HedgeStrategyExecutor. `contracts/run_local.sh` runs both workspaces; `run_local.sh full` adds fuzz/coverage per workspace.
- Events like `MarketResolved` + `resolutionSummary()` emit settlement metadata for downstream services.
- MarketFactory, ProtocolPool, RelayerEscrow, and Verifier use `Ownable2Step`; follow the TODO guidance to script/test ownership transfers when modifying admin logic.
- RevealMarket commitments use Poseidon leaf hashing and batch roots (`BATCH_SIZE=256`, `MERKLE_DEPTH=8`); use `lockBatches` + `verifyAndSettleBatched` when multiple batches are present.

### CI / Automation
- `.github/workflows/cicd.yml` runs pre-commit checks (Foundry + uv sync + pre-commit), then backend, streamer, relayer, hedger, contracts-polygon, contracts-zen, frontend, and prover jobs; deploy runs on `main` after all test jobs succeed.
- Repo-root `./run_tests.sh` mirrors the CI ordering (backend → hedger → streamer → relayer → frontend → contracts/polygon → contracts/zen → prover) and passes `FRONTEND_REQUIRE_API` through when set.

---

Use this document as a quick refresher before changing architecture, security posture, or CI.
