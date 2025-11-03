# Repository Guidelines

## Project Structure & Module Organization
- **backend/** – FastAPI service (`api/`) and worker (`worker/`) sharing code in `backend/shared/`. Alembic migrations live in `backend/migrations/`.
- **contracts/** – Foundry workspace (`src/` for Solidity, `test/` for Forge tests, `script/` for deployments).
- **frontend/** / **other dirs** – Additions should mirror the patterns above (not present today).

## Build, Test, and Development Commands
- `make api` / `make worker` – Build and run Docker Compose services individually.
- `make test` – Runs API and worker pytest suites.
- `forge build`, `forge test` (inside `contracts/`) – Compile and test Solidity contracts.
- `./run_local.sh` (contracts) – Build, test, and check gas snapshots in one pass.

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
