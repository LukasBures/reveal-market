# Repository Guidelines

## Project Structure & Module Organization
- **backend/** – FastAPI service (`api/`) and worker (`worker/`) sharing code in `backend/shared/`. Alembic migrations live in `backend/migrations/`.
- **contracts/** – Foundry workspace (`src/` for Solidity, `test/` for Forge tests, `script/` for deployments).
- **frontend/** – Next.js 14 + TypeScript + Tailwind workspace (marketing site + docs + wallet-ready app shell). Keep new UI work inside this app.

## Build, Test, and Development Commands
- `make api` / `make worker` – Build and run Docker Compose services individually.
- `make test` – Runs API and worker pytest suites.
- `forge build`, `forge test` (inside `contracts/`) – Compile and test Solidity contracts.
- `npm run dev|build|start` (inside `frontend/`) – Frontend workflows powered by Next.js; see Docker service for containerised runs.
- `./run_local.sh` – Build every container with `--no-cache` and launch the full Docker Compose stack.
- `./run_prod.sh` – Build images with cache and start the stack detached (production VPS flow).
- `backend/run_local.sh` – Spins up the API, worker, Postgres, and Redis stack via Docker Compose.
- `backend/run_tests.sh` – Pytest runner for API and worker services (uses Poetry/.venv automatically).
- `contracts/run_local.sh` – Build, test, and check gas snapshots for the Foundry workspace.
- `contracts/run_tests.sh` – Convenience wrapper around `forge build` + `forge test`.
- `frontend/run_tests.sh` – Runs `npm run lint` + `npm run build` to smoke-test the Next.js app.

## Coding Style & Naming Conventions
- Python: PEP 8 with Black formatting (120 columns), isort, and Flake8 (`make fmt` or `pre-commit run --all-files`).
- Solidity: Use `forge fmt`; contracts follow UpperCamelCase, storage variables lowerCamelCase, constants ALL_CAPS.
- Env variables are SCREAMING_SNAKE_CASE (see `.env.example`).

## Testing Guidelines
- Python: Pytest with `asyncio` plugin. Place tests under `backend/*/tests/` using `test_*.py` naming.
- Solidity: Forge’s `Test.t.sol` per contract component. Keep gas snapshots current (`forge snapshot`).
- Minimum expectation: All suites green before PR merge; aim for >90% coverage in contracts.

## Commit & Pull Request Guidelines
- Commits use imperative tense (`feat: add rake override`). Group related changes; avoid large unrelated diffs.
- Pull Requests should include: summary, testing evidence (`make test`, `forge test`), linked issues, and screenshots/logs when UI/API behavior changes.
- Ensure `.env` secrets never appear in commits; use sample placeholders.

## Security & Configuration Tips
- Store real RPC URLs and wallet keys in secret managers; `.env.example` is reference only.
- Verify smart-contract addresses and rake overrides before enabling auto on-chain operations.

## Agent-Specific Instructions
- Reference `backend/TODO.md` and `contracts/TODO.md` for pending MVP work before automating tasks.
- Prefer Python/ABI helpers already present (e.g., `shared/onchain/`) instead of adding new frameworks.

## Agent Notes

### Backend (FastAPI + worker)
- **Architecture snapshot** – Two Python services live under `backend/`. The API (`backend/api/app`) exposes REST endpoints; the worker (`backend/worker/app`) ingests upstream feeds and optionally transacts on-chain. Both share SQLAlchemy models, caching helpers, logging utilities, and on-chain clients from `backend/shared/`. Alembic migrations are stored in `backend/migrations/` and can be executed from either service (API runs them on lifespan startup; worker can run them once via `_ensure_schema` when `run_migrations_on_startup` is true). `backend/shared/migrations.py` provides a helper so non-Alembic processes can invoke migrations programmatically.

- **Data model** – Defined in `backend/shared/models.py`. Core tables: `markets` (event metadata, commit/reveal deadlines, on-chain addresses, rake overrides) and `resolutions` (Conditional Tokens snapshots). `event_id` acts as the natural key, `condition_id` is always downcased, `extra_data` stores JSON Polymarket payloads plus resolution metadata, and indexes cover status/category/oracle/slug for quick filtering.

- **API service** – `backend/api/app/main.py` configures JSON logging, Prometheus instrumentation (`prometheus_fastapi_instrumentator`), and request-scoped IDs that flow through structured logs. The FastAPI lifespan runs migrations synchronously on boot. Endpoints:
  - `/` basic metadata (service, version, environment).
  - `/health` fans out to Postgres, Redis, and Polymarket checks (see `app/health.py` for HTTP + Redis probes).
  - `/markets` supports filtering (status/category/oracle/search), pagination, and returns cached responses keyed by query params; cache layer uses Redis JSON helpers + tag-based invalidation from `shared.cache`.
  - `/markets/stats`, `/markets/{event_id}`, and `/resolution/{condition}` cache their payloads with distinct prefixes and tags.
  - Mutation endpoints (`POST /markets`, `PATCH /markets/{event_id}`) invalidate tagged cache entries. `/markets/onchain` calls `fetch_factory_markets` and requires `RM_RPC_URL` + `RM_FACTORY_ADDRESS`.
  - `/metrics` exposed via Instrumentator.
  CRUD logic lives inside `app/crud.py`, Pydantic schemas in `app/schemas.py`, DB session wiring in `app/database.py`.
  Settings are defined in `app/config.py` (Pydantic `BaseSettings` reading `RM_*` env vars). Key knobs: `RM_DATABASE_URL`, `RM_REDIS_URL`, Polymarket paging (`RM_POLYMARKET_*`), cache TTLs, request limits, `APP_WORKERS`, etc. `.env` overrides are supported via `SETTINGS_FILE`.

- **Worker service** – `backend/worker/app/main.py` continuously:
  1. Pulls markets from Polymarket/Gamma via `PolymarketClient` (configurable pagination/order/closed filters + timeout).
  2. Upserts them using `shared.repository` helpers (`upsert_market`, `touch_heartbeat`, etc.).
  3. Emits Redis heartbeats whose TTL is controlled by `RM_HEARTBEAT_TTL_SECONDS`.
  4. Optionally enriches markets with Conditional Tokens resolutions (`ConditionalTokensClient`) using throttle interval `resolution_refresh_interval_seconds`.
  5. Optionally creates on-chain markets via `maybe_create_onchain_market` when `auto_create_onchain_markets` et al. are configured (`RM_RPC_URL`, `RM_WALLET_PRIVATE_KEY`, gas overrides).
  6. Invalidates API cache tags through `shared.cache.invalidate_tag`.
  Configuration lives in `backend/worker/app/config.py`. Additional envs: `RM_POLL_INTERVAL_SECONDS`, `RM_POLYMARKET_TIMEOUT_SECONDS`, `RM_POLYMARKET_MAX_PAGES`, `RM_POLL_INTERVAL_SECONDS`, `RM_POLYMARKET_CLOSED_FILTER`, `RM_HEARTBEAT_KEY` etc.

- **Shared utilities** – `backend/shared/cache.py` supplies typed Redis clients, JSON serde helpers, tag-based invalidation, and TTL handling. `shared/logging.py` defines JSON logging with context (request IDs). `shared/repository.py` centralises DB operations for both services (upserts, resolution persistence, on-chain metadata). `shared/onchain` bundles ABI helpers (factory + reveal market ABIs, AsyncWeb3 loader, checksum utilities, `ConditionalTokensClient`). `shared/migrations.py` wraps Alembic programmatic API to run migrations from Python.

- **Tests** – API tests (`backend/api/tests`) include:
  - `test_health.py` verifying Postgres/Redis/Polymarket health behaviours.
  - `test_cache_behavior.py` ensuring list/detail caches, tag invalidation, eviction on mutation.
  - `test_markets.py` covering filters, search, stats, resolution responses via mocked repositories.
  - `test_smoke.py` ensures root + basic endpoints respond under test client.
  Test fixtures (`conftest.py`) spin up SQLite and faker Redis for isolation.
  Worker tests (`backend/worker/tests`) cover Polymarket client pagination, sync/upsert logic, heartbeat updates, on-chain creation gating, and process orchestration. Many tests monkeypatch HTTP clients / Polymarket feeds to simulate specific scenarios.
  TODOs for backend live in `backend/TODO.md` (migrations on worker startup, smarter cache invalidation, persisting resolution backfills, Polymarket retry metrics, Horizen ZEN chain support, etc.).

### Contracts (Foundry workspace)
- Structure: `contracts/src` (core contracts), `contracts/test` (Forge tests), `contracts/script` (deployment), `contracts/lib` (openzeppelin, solmate, forge-std). `foundry.toml` sets 0.8.24 compiler, optimizer, via IR, gas reports. Remappings defined both in `foundry.toml` and `contracts/remappings.txt`.
- Key contracts:
  - `RevealMarket.sol`: commit-reveal market with phases, guardian controls, pause toggles, refund logic, zk-proof verification stub calling `IVerifier`. Tracks tickets, payouts, rake overrides. Emits events for every state change (commit, lock, result posted, proofs, settlements, cancellations, guardian changes). Depends on `IRakeManager`, `IVerifier`, `IMarketFactoryStatus` for global pauses. TODO: replace stub verifier, add settlement guards, metadata events.
  - `MarketFactory.sol`: Ownable2Step factory deploying clones via `Clones.clone`. Maintains collateral allowlist, guardian, default collateral, global commit/claim pauses. Creates markets with references to rake manager, treasury, verifier, guardian. Emits numerous events (MarketCreated, CollateralStatusUpdated, etc.). TODO: implement metadata handling, event indexing.
  - `RakeManager.sol`: Ownable2Step that holds treasury address and rake basis points (max 200 bps). Provides `takeRake` helper returning net amount + event emission.
  - `Verifier.sol`: stub contract always returning true (needs replacement with real Groth16/Noir verifier).
- Tests: `MarketFactory.t.sol`, `RevealMarket.t.sol`, `RevealMarketFuzz.t.sol`, `RevealMarketSecurity.t.sol`, `FactoryLifecycle.t.sol`, `RakeManager.t.sol`, `Verifier.t.sol`. Coverage includes lifecycle flows, fuzzing reveal/claim invariants, guardian controls, pause semantics, and event assertions. Additional mocks under `contracts/test/mocks/`.
- TODOs tracked in `contracts/TODO.md` (real verifier integration, settlement guards, deployment tooling, invariants, gas regression, cross-chain strategy, etc.).

### Frontend (Next.js app)
- Stack: Next.js 14 App Router + TypeScript + Tailwind + React Query + Wagmi/Viem. Lives under `frontend/`. `components/` houses layout (nav/footer), marketing sections (hero, markets preview, CTA), docs nav, provider shell hooking Wagmi + React Query. `lib/api.ts` fetches `/markets` from FastAPI with caching, `lib/wagmi.ts` preconfigures Polygon Amoy RPC (placeholder RPC override via env).
- Routing: `app/` contains `layout.tsx` (global metadata, fonts, nav/footer), root page with hero + markets section, `/about`, `/docs/*` (overview, getting started, architecture, API reference). Docs host rewriting handled via `middleware.ts` which inspects `Host` header (`DOCS_HOST` env) and rewrites to `/docs` namespace for `docs.revealmarket.xyz`. Added `/api/health` route so Docker healthchecks can probe the frontend container directly.
- Styling: Tailwind config defines brand palette + glow shadows; `app/globals.css` sets dark theme. Components use `clsx` for active states. `Hero`/`MarketsSection` read live backend data (server component fetch + client hydration). `wa` gm config stub ensures wallet integrations can be added later.
- Tooling: `frontend/run_tests.sh` runs lint + build; `package.json` contains Next lint script; `.dockerignore` prevents node_modules from polluting build context. `TODO.md` outlines frontend roadmap (market detail, wallet interactions, live updates, docs improvements, E2E tests).

### Migrations & shared infrastructure
- Alembic config lives in `backend/migrations` with `alembic.ini`, `env.py`, and versioned scripts (`backend/migrations/versions/0001_*`, etc.). `backend/shared/migrations.py` exposes `run_migrations` for services. Worker has stub `backend/shared/migrations.py` for future improvements (`backend/shared/migrations.py` is currently tracked separately).
- Redis is used for caching, tag invalidation, worker heartbeats. Healthcheck commands in Compose use `redis-cli ping`. Postgres 15 stores core data; Compose volume `postgres_data` persists DB state.

### Docker & scripts
- Dockerfiles relocated under `docker/` with multi-stage builds:
  - `docker/api/Dockerfile` and `docker/worker/Dockerfile` install Poetry + export requirements in builder stage, then copy only shared/service code plus migrations into slim runtime images (with `curl`, `libpq5`, `build-essential` for compiling deps). Healthchecks hit `/health` (API) and `python -m app.healthcheck` (worker).
  - `docker/frontend/Dockerfile` builds Next.js standalone bundle and serves via `node server.js`, with healthcheck hitting `/api/health`.
- Compose services: `postgres`, `redis`, `api`, `worker`, `frontend`. Override file mounts source code for live reload (API/worker) and runs `npm install && npm run dev` for frontend. Root scripts:
  - `run_local.sh` – full rebuild (`--no-cache`) + `docker compose up`.
  - `run_prod.sh` – cached `docker compose build` + `up -d` (production deploy).
  - `backend/run_local.sh` – reuses cached backend images for quick dev loops.
  Healthchecks are wired both in Dockerfiles and Compose (for Postgres/Redis, etc.).

### Testing status & automation gaps
- Backend test coverage is strong (unit + integration stubs). TODOs call for end-to-end tests with real Postgres/Redis, plus property tests for cache keys.
- Contracts have deterministic + fuzz tests, but TODO highlights need for invariants, static analysis (Slither/solhint), and real verifier integration.
- Frontend currently lacks automated UI/E2E tests; roadmap suggests adding Playwright/Cypress + Lighthouse budgets.
- `.pre-commit-config.yaml` currently only runs Black/isort/Flake8 for `backend/api`. Consider extending to worker, contracts (`forge fmt`), and frontend (`eslint`/`prettier`).

### Operational cautions
- Worker auto-creation of markets depends on `RM_WALLET_PRIVATE_KEY` – ensure secrets are stored securely (Vault/KMS) before production. Rate limits + retries for Polymarket should be monitored (`worker.fetch.*` logs). Conditional Tokens RPC reliability affects resolution freshness; metrics/alerting should watch heartbeats and fetch latency. Keep `.env` files out of VCS and ensure `RM_*` envs are set per environment. TODOs mention Horizen ZEN testnet support; verify RPC URLs before enabling cross-chain deployments.
