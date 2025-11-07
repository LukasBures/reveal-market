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
- **Architecture snapshot** – Two Python services under `backend/`: FastAPI API (`backend/api/app`) and ingest worker (`backend/worker/app`) share ORM models, cache helpers, and logging in `backend/shared`. Alembic migrations live in `backend/migrations` and are invoked from both services (`app/database.py`, worker `_ensure_schema`).
- **Data model** – Core tables: `markets` (`backend/shared/models.py`) and `resolutions` for Conditional Tokens snapshots. Natural key is `event_id`; `condition_id` stored lowercase; `extra_data` JSON stores Polymarket payloads plus resolution metadata. Indices on status/category, slug, condition.
- **API service** – Entry in `backend/api/app/main.py`: runs migrations on lifespan, wires Prometheus instrumentation, structured logging, and request ID middleware. Endpoints cover `/health` (checks Postgres, Redis, Polymarket via `httpx`), `/metrics`, paginated `/markets` with Redis caching keyed by filters, `/markets/stats`, `/markets/{event_id}`, `/resolution/{condition}`, CRUD for markets (POST/PATCH with cache invalidation), and `/markets/onchain` that calls `fetch_factory_markets` (requires `RM_RPC_URL` + `RM_FACTORY_ADDRESS`). Cache tags stored via `shared.cache` helpers.
- **Worker service** – `backend/worker/app/main.py` polls Polymarket (Gamma) via `PolymarketClient`, upserts markets, emits Redis heartbeats, and invalidates caches. Supports Conditional Tokens resolution refresh with throttling (`resolution_refresh_interval_seconds`) and optional on-chain `createMarket` transactions when `auto_create_onchain_markets` and RPC/wallet config are present (`app/onchain.py` with async web3 + tenacity retries). Worker applies migrations once at startup when `run_migrations_on_startup` true.
- **Shared utilities** – `backend/shared/cache.py` wraps Redis get/set/tag invalidation, logging via `shared/logging.py` (JSON logs with request ID context), `shared/repository.py` centralises upserts, `shared/onchain` exposes ABI/constants, AsyncWeb3 loader, checksum helpers, and `ConditionalTokensClient` resolution reader.
- **Configuration surfaces** – Both services use Pydantic `BaseSettings` (settings prefixed `RM_`, `backend/api/app/config.py`, `backend/worker/app/config.py`). Key knobs: database pool sizing, Redis URL, Polymarket pagination/order/filters, cache TTL, resolution refresh interval, worker heartbeat TTL, default commit/reveal leads, optional Polygon RPC/Conditional Tokens addresses, and gas overrides. `SETTINGS_FILE` env enables .env overrides.
- **Local workflows** – Docker Compose (`docker-compose.yml` + override) provisions Postgres, Redis, API, worker, and the new frontend container; override mounts source and sets dev logs/poll interval. Use `./run_local.sh` when you need a clean build (`--no-cache`) of every image, while `backend/run_local.sh` skips the rebuild for faster backend-only loops. For production deployments run `./run_prod.sh` to build with cache and start the stack detached. `contracts/run_local.sh` handles Foundry build→test→snapshot, and the frontend container runs `npm install && npm run dev` for hot reload. `Makefile` shortcuts: `make api`, `make worker`, `make test`, `make fmt`. `backend/run_tests.sh`, `contracts/run_tests.sh`, and `frontend/run_tests.sh` cover the respective test suites.
- **Testing strategy** – API tests under `backend/api/tests/` use SQLite + in-memory Redis stubs (see `conftest.py`) to cover caching semantics, filtering, and resolution responses. Worker tests in `backend/worker/tests/` prefer its package path, exercise Polymarket pagination, sync upserts, resolution persistence, on-chain flow (with monkeypatched send), and process heartbeat stats.
- **Contracts workspace** – Located in `contracts/` (Foundry). Key contracts (`RevealMarket`, `MarketFactory`, `RakeManager`, `Verifier` stub) with extensive tests, deployment script (`script/Deploy.s.sol`), and backlog in `contracts/TODO.md` (notably: integrate real verifier, resolution eventing, invariants). Use `forge build/test`, `contracts/run_local.sh` for build→test→snapshot.
- **Frontend status** – `frontend/` now hosts a Next.js 14 + Tailwind + React Query + Wagmi app. It serves marketing (`/`, `/about`) and docs (`/docs/*`) routes, with middleware-based host routing for `docs.revealmarket.xyz`. Docker service `frontend` builds the production bundle; devs can run `npm run dev` or rely on the compose override that runs `npm install && npm run dev`.
- **Operational cautions** – Worker auto-creation depends on private key secrets; ensure these come from secure storage. Resolution caching relies on Conditional Tokens event logs—RPC reliability impacts freshness. TODOs highlight needs: smarter cache invalidation, migrations on worker, Polymarket retry metrics, Horizen ZEN testnet option (per TODO). Keep `.env` secrets out of VCS and align with `RM_` prefix expectations.
