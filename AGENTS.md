# Repository Guidelines

## Project Structure & Module Organization
- **backend/** – FastAPI API (`api/`) and ingestion/automation worker (`worker/`) sharing utilities in `backend/shared/`. Alembic migrations live in `backend/migrations/`. Each service has its own README describing security/logging/health probes.
- **contracts/** – Foundry workspace (`src/`, `test/`, `script/`). `run_local.sh` wraps build → tests → gas snapshot; `run_local.sh full` adds fuzz + coverage.
- **frontend/** – Next.js 15 + TypeScript + Tailwind workspace powering the marketing/docs site. SEO helpers sit in `frontend/lib/seo.ts`; sitemap/robots and security headers are auto-generated via the app router.

## Build, Test, and Development Commands
- `make api` / `make worker` – Build + run individual Docker services (includes Postgres/Redis dependencies).
- `make test` – Runs `./backend/run_tests.sh` (API + worker pytest suites).
- `backend/run_tests.sh` – Discovers Poetry/venv envs and executes pytest with asyncio plugins.
- `forge build`, `forge test` (inside `contracts/`) – Compile/test Solidity. `contracts/run_local.sh [full]` for full pipeline.
- `npm run dev|build|start|lint|test` (inside `frontend/`) – Next.js workflows. `npm run test` executes Vitest + Testing Library.
- `./run_local.sh` – Build every Docker image with `--no-cache` and launch the full stack (API, worker, frontend, Postgres, Redis).
- `./run_prod.sh` – Build with cache + start stack detached (production/VPS flow).

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

## Agent-Specific Instructions
- Review `backend/TODO.md`, `contracts/TODO.md`, and `frontend/TODO.md` before large tasks; they capture prioritized work.
- Prefer existing helpers (e.g., `shared/onchain/`, `lib/seo.ts`) over introducing new frameworks.
- Maintain the unified logging format (`timestamp | LEVEL | logger | file:line | event | request_id`).
- When editing docs/marketing copy, ensure metadata (via `docsMetadata`/`buildMetadata`) stays accurate so sitemap/robots remain valid.

## Agent Notes

### Backend (FastAPI + Worker)
- **Architecture** – API and worker share SQLAlchemy models, cache helpers, and logging utilities in `backend/shared/`. Alembic migrations live in `backend/migrations/` and can be invoked via `shared/migrations.py`. Docker images copy migrations so health probes can run `_ensure_schema()` safely.
- **API** – `backend/api/app/main.py` wires structured logging, Prometheus instrumentation, TrustedHost + CORS middleware, and security headers (CSP/HSTS/COOP). Lifespan runs migrations on boot. `/health` returns Postgres/Redis/Polymarket status; `/markets` family uses Redis-tagged caches; mutation endpoints invalidate tags. `app/security.py` manages header defaults.
- **Worker** – `backend/worker/app/main.py` pulls Polymarket feeds, writes markets/resolutions, emits Redis heartbeats, and can call `maybe_create_onchain_market`. `worker/app/healthcheck.py` verifies Postgres connectivity for Docker. Logs mirror the API format.

### Frontend (Next.js)
- **SEO/AI readiness** – Metadata centralised in `lib/seo.ts`. Every docs/legal/about page imports `docsMetadata` so canonical URLs + keywords stay consistent. `app/sitemap.ts`/`app/robots.ts` update automatically.
- **Security headers** – Configured in `next.config.mjs` (CSP, HSTS, Referrer/Permissions policies, COOP/CORP). Update the CSP when adding external assets.
- **Testing** – Vitest + Testing Library cover hero CTA, DocsNav, MainNav, DocsLayout. Keep tests updated when components change.

### Contracts (Foundry)
- `src/` houses RevealMarket, MarketFactory, RakeManager, Verifier. `test/` contains Forge suites (unit + fuzz). `run_local.sh full` builds/tests/gas-checks/fuzzes; CI runs this via GitHub Actions.
- Events like `MarketResolved` + `resolutionSummary()` emit settlement metadata for downstream services.

### CI / Automation
- `.github/workflows/ci.yml` runs three jobs in parallel:
  - **backend**: setup Python 3.13 + Poetry, cache virtualenvs, run `./backend/run_tests.sh`.
  - **contracts**: install Foundry via `foundryup`, execute `./contracts/run_local.sh full`.
  - **frontend**: setup Node 20, `npm install`, `npm run build` (ready for lint/test when expanded).
- `.github/workflows/contracts-ci.yml` exists for legacy Forge-only runs; keep it unless instructed otherwise.

---

Use this document as a quick refresher before changing architecture, security posture, or CI.
