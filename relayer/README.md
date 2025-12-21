# Reveal Relayer (Python)

Minimal HTTP relayer that submits `commitOnBehalf` and `claim` transactions to the Reveal Market contracts. Runs as a FastAPI service with Web3 + EOA signer.

## What it does today
- Accepts `/commit` and `/claim` payloads and enqueues them in a durable queue (Postgres via `RM_DATABASE_URL`, SQLite fallback) that retries with backoff + fee bumps before submitting transactions. The default entrypoint runs in queue mode.
- Healthcheck `/healthz` reports RPC connectivity, latest block age, relayer/escrow addresses, balances/allowances, and owner checks; `/metrics` exports HTTP latency, tx outcomes/latency, and queue depth/outcomes; `/status` returns job state.
- Optional ingest hooks push commitment/settlement metadata to the backend when `RELAYER_API_BASE_URL` is set. Admin endpoints list/replay/purge dead-lettered jobs when auth is enabled.

## Requirements
- Python 3.12
- `uv` (package manager): `pip install uv` or download from https://github.com/astral-sh/uv
- RPC: Horizen Testnet `https://horizen-testnet.rpc.caldera.xyz/http` (default)

## Config (env vars)
- `RELAYER_PRIVATE_KEY`: hex EOA key used to sign txs.
- `RELAYER_ESCROW_ADDRESS`: deployed `RelayerEscrow` address.
- `RPC_URL`: JSON-RPC endpoint (e.g., Horizen testnet).
- `CHAIN_ID`: matching chain ID (e.g., `2651420`).
- `RELAYER_HOST`: bind host (e.g., `0.0.0.0`).
- `RELAYER_PORT`: bind port (e.g., `8088`).
- `RELAYER_BEARER_TOKEN` (optional): if set, `Authorization: Bearer <token>` is required for `/commit`, `/claim`, `/status`, and `/admin/*`.
- `RELAYER_MAX_BLOCK_AGE_SECONDS` (default `60`): mark health degraded if the latest block is older.
- `RELAYER_MIN_BALANCE_WEI` (default `0`): mark health degraded when relayer ETH balance is below this.
- `RELAYER_MAX_RETRIES` (default `3`), `RELAYER_RETRY_BACKOFF_SECONDS` (default `0.5`), `RELAYER_TX_TIMEOUT_SECONDS` (default `120`): tx retry/backoff + receipt wait tuning.
- `RELAYER_HTTP_TIMEOUT_SECONDS` (default `10`): RPC HTTP request timeout.
- Queue + bumping: prefer Postgres via `RM_DATABASE_URL` (e.g., `postgresql+psycopg2://user:<REDACTED>@host:5432/db` or `postgresql://...`); fallback SQLite path via `RELAYER_QUEUE_DB_PATH` (default `relayer_queue.db`). Tuning: `RELAYER_QUEUE_POLL_SECONDS` (default `1`), `RELAYER_QUEUE_MAX_ATTEMPTS` (default `5`), `RELAYER_FEE_BUMP_PERCENT` (default `0.15` bump per retry).
- Token health thresholds: `RELAYER_MIN_ESCROW_TOKEN_BALANCE_WEI`, `RELAYER_MIN_RELAYER_TOKEN_ALLOWANCE_WEI`.
- Backend ingest (optional): `RELAYER_API_BASE_URL`, `RELAYER_API_BEARER_TOKEN`, `RELAYER_API_TIMEOUT_SECONDS` (default `10`).

## Install & Run (local)
```bash
cd relayer
uv sync --group dev
PYTHONPATH=src uv run uvicorn relayer.main:app --reload --host 0.0.0.0 --port 8088
# or: make run
```

## Docker
```bash
docker build -t reveal-relayer -f docker/relayer/Dockerfile .
docker run --rm -p 8088:8088 \
  -e RELAYER_PRIVATE_KEY=0x... \
  -e RELAYER_ESCROW_ADDRESS=0x... \
  -e RPC_URL=https://horizen-testnet.rpc.caldera.xyz/http \
  reveal-relayer
```

## API
- `GET /healthz` — status + addresses.
- `GET /metrics` — Prometheus scrape target.
- `POST /status` — body: `{jobId}`; returns queue state, attempts, and tx hash when available.
- `POST /commit` — body: `user, market, commitment, nonce, expiry, chain_id, ticket_value_wei, signature` plus optional ingest fields; queue mode returns `202 Accepted` with `{jobId, status: queued}`.
- `POST /claim` — body: `market, user, ticket_id, outcome_id, amount, salt, merkle_proof[]` plus optional ingest fields; queue mode returns `202 Accepted` with `{jobId, status: queued}`.
- Admin (auth if bearer set): `GET /admin/queue/deadletter` lists dead-lettered jobs; `POST /admin/queue/deadletter/{id}/replay` resets to pending; `DELETE /admin/queue/deadletter/{id}` purges.

## Tests
```bash
cd relayer
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src uv run pytest
# or: make test
```

## Notes
- Service uses a durable queue with automatic fee bumping; set `RM_DATABASE_URL` to a Postgres instance to persist across restarts (mount a volume if using SQLite).
- Gas funding: ensure the relayer EOA is funded on the target network; health exposes ETH balance, collateral token balances/allowances, and block freshness.
- Contracts must match the deployed ABI (commit/claim paths). Update `abi.py` if needed.
- Queue mode is the default in `relayer.main`; to run synchronous commits/claims, construct the app without a `TxQueue`.
- Logs are structured JSON with timestamp/level/event fields and tx metadata for observability.
