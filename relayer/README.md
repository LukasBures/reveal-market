# Reveal Relayer

FastAPI + Web3 service that signs and submits `commitOnBehalf`, `claim`, and `lockBatches` transactions to the Reveal Market contracts. A durable queue (SQLite by default, Postgres when `RM_DATABASE_URL` is provided) handles retries and fee bumps so RPC hiccups don’t lose jobs.

```
Clients -> Relayer API -> Queue -> Web3 RPC -> RevealMarket/RelayerEscrow
                        \-> optional ingest -> Backend
```

## How it works

- **Startup**: load env (`config.load_config`), configure logging, build Web3 client + relayer account, create `RelayerService`, initialize `TxQueue` (SQLite path or Postgres DSN), and optional in-memory rate limiter/IP allowlist.
- **Queue**: `TxQueue` stores jobs with status/attempts/tx hash. A background worker pops pending jobs, bumps gas per retry, optionally drops expired commits, and records results. Dead-lettered jobs can be replayed or purged via admin routes.
- **Endpoints** (all guarded by bearer/IP/rate-limit when configured):
  - `GET /healthz` – RPC connectivity, block freshness, balances/allowances, escrow owner check, queue stats.
  - `POST /commit` – validate CommitAuth payload, enqueue or send immediately, optional ingest to backend.
  - `POST /claim` – validate claim payload, enqueue or send immediately, optional ingest to backend.
  - `POST /lock-batches` – build Poseidon batch roots (BATCH_SIZE=256, MERKLE_DEPTH=8), enqueue or send; optional ingest of batch roots/counts.
  - `POST /status` – lookup job state/attempts/tx hash.
  - `GET /metrics` – Prometheus metrics (HTTP, queue depth/outcomes, tx latency).
  - Admin: `/admin/queue/deadletter` (list), `/admin/queue/deadletter/{id}/replay`, `/admin/queue/deadletter/{id}` (delete).
- **Auth & abuse controls**: bearer token (recommended), optional IP allowlist and in-memory sliding-window rate limiter, optional `x-forwarded-for` trust.
- **Logging/metrics**: structured logs for every request and queue attempt; Prometheus counters/gauges for queue depth, deadletter depth, tx outcomes, and latency.

## Configuration (env)

- **RPC**: `RPC_URL`, `CHAIN_ID`, `RELAYER_PRIVATE_KEY` (EOA), `RELAYER_ESCROW_ADDRESS`.
- **Server**: `RELAYER_HOST` (default `0.0.0.0`), `RELAYER_PORT` (default `8088`).
- **Auth**: `RELAYER_BEARER_TOKEN` (required unless `RELAYER_ALLOW_INSECURE_AUTH=true`), `RELAYER_IP_ALLOWLIST` (CSV IPs/CIDRs), `RELAYER_TRUST_X_FORWARDED_FOR`.
- **Queue**: `RM_DATABASE_URL` (Postgres DSN) or `RELAYER_QUEUE_DB_PATH` (SQLite path, default `relayer_queue.db`), `RELAYER_QUEUE_POLL_SECONDS`, `RELAYER_QUEUE_MAX_ATTEMPTS`, `RELAYER_FEE_BUMP_PERCENT`, `RELAYER_TX_TIMEOUT_SECONDS`.
- **Rate limit**: `RELAYER_RATE_LIMIT_REQUESTS`, `RELAYER_RATE_LIMIT_WINDOW_SECONDS` (set requests=0 to disable).
- **Tx safety**: `RELAYER_PREFLIGHT_MODE` (`none|call|estimate|both`), `RELAYER_MAX_RETRIES`, `RELAYER_RETRY_BACKOFF_SECONDS`, `RELAYER_HTTP_TIMEOUT_SECONDS`, `RELAYER_MAX_BLOCK_AGE_SECONDS`, `RELAYER_MIN_BALANCE_WEI`, `RELAYER_MIN_ESCROW_TOKEN_BALANCE_WEI`, `RELAYER_MIN_RELAYER_TOKEN_ALLOWANCE_WEI`.
- **Backend ingest (optional)**: `RELAYER_API_BASE_URL`, `RELAYER_API_BEARER_TOKEN`, `RELAYER_API_TIMEOUT_SECONDS`.

Defaults live in `src/relayer/config.py`.

## Running & Testing

```bash
cd relayer
uv sync --group dev
PYTHONPATH=src uv run uvicorn relayer.main:app --reload --host 0.0.0.0 --port 8088

# Tests
PYTHONPATH=src uv run pytest   # or: ./run_tests.sh
```

Docker: `docker compose up relayer` (uses `docker/relayer/Dockerfile`).

## File Map

- `src/relayer/main.py` – load config, build Web3 + service, initialize queue/rate limiter, create FastAPI app.
- `src/relayer/app.py` – routes, auth/abuse guards, metrics middleware.
- `src/relayer/service.py` – tx builders + validation for commit/claim/lock-batches, optional backend ingest.
- `src/relayer/queue.py` – durable queue, retries, deadletter handling.
- `src/relayer/security.py` – bearer/IP allowlist/rate limiter helpers.
- `src/relayer/poseidon.py` – Poseidon hash helpers for batch roots.
- `src/relayer/abi.py` – contract ABIs; keep in sync with deployed contracts.

## Operational Tips

- Fund the relayer EOA and ensure `RelayerEscrow` owner matches expectations; `/healthz` reports balances/allowances and owner check.
- Queue mode is default; to run synchronously, construct the app without `TxQueue` (not the default in `main.py`).
- `lockBatches` succeeds only if the relayer key is the oracle (`onlyOracle`); otherwise expect on-chain reverts.
- When using SQLite, mount a volume if you need queue durability across restarts; prefer Postgres in production.
