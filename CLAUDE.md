# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Running Services (Docker Compose)

```bash
make api          # postgres + redis + API service
make worker       # postgres + redis + worker service
make stack        # postgres + redis + api + worker + frontend
make hedger       # postgres + redis + hedger service
make streamer     # streamer service
make prover       # prover service
make frontend     # frontend service
make all          # all services
make down         # stop all containers
make local        # ./run_local.sh (local dev stack)
make prod         # ./run_prod.sh (production stack)
```

### Testing

```bash
make test                       # full sequential suite (all services)
make test-backend               # backend/run_tests.sh (API + shared + worker + mypy)
make test-api                   # cd backend/api && uv run --project . --extra dev pytest
make test-worker                # cd backend/worker && uv run --project . --extra dev pytest
make test-frontend              # cd frontend && ./run_tests.sh
make test-hedger                # cd hedger && ./run_tests.sh
make test-streamer              # cd streamer && ./run_tests.sh
make test-relayer               # cd relayer && ./run_tests.sh
make test-contracts-zen         # cd contracts/zen && ./run_tests.sh
make test-contracts-polygon     # cd contracts/polygon && ./run_tests.sh
make test-prover                # cd prover && ./run_tests.sh
```

Run a single Python test file or pattern (backend example):
```bash
cd backend/api && uv run --project . --extra dev pytest tests/test_markets.py -k "test_list"
```

Run a single Vitest test (frontend):
```bash
cd frontend && npm run test -- --run tests/components/MarketCard.test.tsx
```

Run a single Forge test (contracts):
```bash
cd contracts/zen && forge test --match-test testCommit -vvv
```

### Formatting / Linting

```bash
make format                     # uv run pre-commit run --all-files (ruff + mypy + gofmt + forge)
cd frontend && npm run lint     # ESLint
cd contracts/zen && forge fmt   # Solidity formatter
```

### Frontend Dev

```bash
cd frontend && npm run dev      # Next.js dev server
cd frontend && npm run build    # Production build
cd frontend && npm run generate:css  # Regenerate Tailwind CSS
```

### Database Migrations

```bash
cd backend/migrations && alembic upgrade head
cd backend/migrations && alembic revision --autogenerate -m "description"
```

## Architecture

Reveal Market is a commit-and-reveal prediction market platform. Services communicate via Redis pubsub/cache and REST APIs; the database is PostgreSQL.

### Services

| Service | Language | Role |
|---------|----------|------|
| `backend/api` | Python/FastAPI | Market data REST API, pricing quotes, `/health`, `/metrics` |
| `backend/worker` | Python/FastAPI | Polymarket ingestion, settlement, batch Poseidon hashing, cache hydration |
| `backend/shared` | Python | Shared SQLAlchemy models, Redis cache helpers, logging, on-chain utilities |
| `frontend` | Next.js 15/TS | Marketing site + app UI (App Router) |
| `streamer` | Python/FastAPI | SSE/WebSocket server for Polymarket CLOB + Binance FX feeds |
| `relayer` | Python/FastAPI | On-chain transaction queue (commit/claim/lock) |
| `hedger` | Python/FastAPI | Exposure/risk tracking, settlement orchestration |
| `prover` | Go | Groth16 ZK proof generation using Circom artifacts + rapidsnark |
| `contracts/zen` | Solidity/Foundry | RevealMarket, MarketFactory, ProtocolPool, RelayerEscrow, Verifier |
| `contracts/polygon` | Solidity/Foundry | BaseLpVault, HedgeStrategyExecutor |
| `polymarket-subgraph` | GraphQL | Subgraph indexers (OI, orderbook, activity, wallet, FPMM, etc.) |

### Settlement Flow

Commitments use **Poseidon hashing** (BN254) with `BATCH_SIZE=256` and `MERKLE_DEPTH=8`. These constants must stay aligned across contracts, prover, backend, and relayer. Batch roots are locked via `lockBatches`; proofs are submitted via `verifyAndSettleBatched` (or `verifyAndSettle` for single-batch markets).

### Frontend Structure

- `app/(app)/` — authenticated pages (dashboard, events, proofs)
- `app/(public)/` — marketing pages (docs, about, contact, terms, privacy)
- `app/api/` — API route handlers (suggest, contact, health, proofs)
- `app/actions/` — server actions for data mutations
- `lib/api.ts` — all backend fetches (never fetch backend directly from components)
- `lib/seo.ts` — centralized metadata; import `docsMetadata`/`buildMetadata` for all docs/legal pages
- `lib/wagmi.ts` — wallet/Web3 config (requires `NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID`)

### Backend API Structure

- `backend/api/app/main.py` — FastAPI app, middleware, lifespan (runs migrations on boot)
- Routes: `/markets/*`, `/pricing/*`, `/internal/*` (requires `X-Internal-Secret`), `/health`, `/metrics`
- `/pricing/quote` — pulls FX from `http://streamer:8100/fx/zen-usd`, signs QUOTE_V1 digest with `RM_PRICING_SIGNER_PRIVATE_KEY`
- Market cache uses Redis tagged invalidation; bypasses cleanly when Redis is down

### Key Constraints

- **Default chain**: Horizen Testnet, chain ID `2651420`, RPC `https://horizen-testnet.rpc.caldera.xyz/http`
- **Python version**: 3.12 (exactly)
- **Node version**: >=20.0.0, <21.0.0
- **Package manager (Python)**: `uv` with per-service virtual envs at `<service>/.venv`
- **Line length**: 120 chars (Python); ruff enforces E/F/W/B/I/N/UP/S rules; banned `requests` → use `httpx.AsyncClient`
- **Async**: all Python services use `asyncio_mode = auto`; pytest workers default to `cpu_count - 2`
- **Logging format**: `timestamp | LEVEL | logger | file:line | event | request_id` — maintain this across all services
- **Prover**: refuses to start if artifacts under `prover/circuits/build` are missing; seed from `prover/artifacts` or `PROVER_ARTIFACTS_URL`

### Security Headers

Both the API (`app/security.py`) and frontend (`next.config.mjs`) enforce CSP, HSTS, COOP, CORP, Referrer-Policy, and Permissions-Policy. **Whitelist new external domains in both places** before referencing them. GA/gtag origins are production-only in CSP.

### Observability

All services expose `/metrics` (Prometheus) and `/health`. The unified logging format is JSON-structured. Redis stores worker heartbeats and batch stats accessible via the API `/internal/*` routes.

## Development Notes

- **Before large tasks**: review per-service `TODO.md` files (`backend/TODO.md`, `frontend/TODO.md`, `contracts/zen/TODO.md`, etc.) for prioritized work.
- **Shared helpers first**: prefer `backend/shared/onchain/`, `lib/seo.ts`, existing cache helpers over new abstractions.
- **Pre-commit hooks** run ruff format+lint, mypy (per service), gofmt, and forge gas snapshots automatically. Run `make format` before committing.
- **OpenAPI snapshot test** (`backend/api/tests/test_openapi_snapshot.py`) runs as part of `make test-backend` — update the snapshot when changing API shapes.
- **Frontend API/build**: tests and builds only enforce backend `/health` when `FRONTEND_REQUIRE_API=true`; otherwise they warn and proceed.
- **CORS in streamer**: set `STREAMER_CORS_ALLOW_ORIGINS` to the frontend origin; wildcard CORS is disallowed in prod (`RM_ENVIRONMENT=prod`).
- **Worker complexity**: `_apply_resolution`, `cleanup_resolved_markets`, and `process_once` are large and carry `# noqa: C901`; prefer incremental refactors.
