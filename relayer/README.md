# Relayer

FastAPI service that submits on-chain transactions (`commitOnBehalf`, `claim`, `lockBatches`) on behalf of users. Transactions can be submitted synchronously or queued for async processing with retry and dead-letter support.

## Entrypoint

`relayer/src/relayer/main.py`

## Key Responsibilities

- Validate and submit commit, claim, and lock-batches transactions to the RevealMarket escrow contract.
- Recompute Poseidon commitment leaves and Merkle batch roots to verify correctness before submitting.
- Optional Redis-backed (or SQLite-backed) job queue with configurable retries and dead-letter handling.
- Push ingest hooks back to the backend API (commit ingest / settlement ingest) using `X-Internal-Secret`.
- RPC circuit breaker that opens after repeated failures to protect against stale-chain scenarios.
- Token/escrow balance preflight checks before sending transactions.
- IP allowlist, bearer-token auth, and per-route rate limiting.

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/commit` | Bearer + IP | Submit a `commitOnBehalf` transaction (queued if queue enabled, returns `202 {jobId}`) |
| `POST` | `/claim` | Bearer + IP | Submit a `claim` transaction |
| `POST` | `/lock-batches` | Bearer + IP | Submit a `lockBatches` transaction |
| `POST` | `/status` | Bearer + IP | Poll job status by `jobId` |
| `GET` | `/healthz` | None | Returns cached health snapshot or `{"status":"ok"}` |
| `GET` | `/healthz/deep` | None | Full health check: chain head lag, balances, queue stats; `?force=true` bypasses cache |
| `GET` | `/metrics` | None | Prometheus metrics |
| `GET` | `/admin/queue/stats` | Bearer + IP | Queue depth, dead-letter count, oldest backlog age |
| `GET` | `/admin/queue/deadletter` | Bearer + IP | List all dead-letter jobs with payload |
| `POST` | `/admin/queue/deadletter/{job_id}/replay` | Bearer + IP | Reset a dead-letter job to `pending` (attempts reset to 0) |
| `DELETE` | `/admin/queue/deadletter/{job_id}` | Bearer + IP | Permanently delete a dead-letter job |

## Request Schemas

**`POST /commit`** — `CommitRequest`
- `user`, `market` (addresses), `commitment`, `nonce`, `expiry`, `chain_id`, `ticket_value_wei`, `signature` (required)
- `amount_wei`, `payout_wei`, `event_id`, `market_id`, `outcome_id`, `salt`, `ticket_id`, `merkle_path` (optional, for ingest)

**`POST /claim`** — `ClaimRequest`
- `market`, `user`, `ticket_id`, `outcome_id`, `amount`, `payout`, `salt`, `merkle_proof` (required)
- `merkle_root`, `batch_roots`, `batch_counts`, `commitments_count`, `pool_total_yes`, `pool_total_no`, `total_escrow`, `total_liability`, `rake_bps`, `proof_request_id`, `event_id` (optional, for ingest)

**`POST /lock-batches`** — `LockBatchesRequest`
- `market`, `tickets[]` (up to 256), `event_id` or `market_id` (one required)
- `relayer_sig` (optional relayer signature)
- Each ticket: `ticket_id`, `outcome_id`, `amount`, `payout`, `user`, `salt`, `leaf` (optional precomputed leaf)

## Modules

| Module | Description |
|--------|-------------|
| `main.py` | Boots Web3 / account / service / queue / rate limiter; calls `create_app` |
| `app.py` | `create_app` — FastAPI factory with all HTTP routes, auth middleware, and rate limiting |
| `config.py` | `RelayerSettings` (Pydantic BaseSettings, `RM_` prefix); all env var definitions |
| `service.py` | `RelayerService` — signs and submits transactions; handles nonce management, fee bumping, retries, preflight, API ingest push, RPC circuit breaker, and health checks |
| `queue.py` | `TxQueue` — persistent job queue backed by SQLite (default) or PostgreSQL; handles retries, stale-job reclamation, heartbeating, and dead-letter |
| `schemas.py` | Pydantic request models: `CommitRequest`, `ClaimRequest`, `LockTicket`, `LockBatchesRequest` |
| `security.py` | `RateLimiter` (sliding window, async), `resolve_client_ip`, `ip_allowed` |
| `poseidon.py` | Pure-Python BN254 Poseidon hash — `compute_leaf`, `build_batch_root`, `poseidon_t3/t4`; `BATCH_SIZE=256`, `MERKLE_DEPTH=8` |
| `abi.py` | Minimal ABI fragments for `commitOnBehalf`, `claim`, and `lockBatches` |
| `metrics.py` | Prometheus metrics: request latency, tx latency/outcomes, RPC errors, circuit state, queue depth/outcomes/errors |
| `logging_setup.py` | `configure_logging` — structlog JSON renderer with UTC ISO timestamps |

## Directory Structure

```
relayer/
├── src/
│   └── relayer/
│       ├── __init__.py
│       ├── main.py           # entrypoint
│       ├── app.py            # FastAPI factory
│       ├── config.py         # settings
│       ├── service.py        # transaction orchestration
│       ├── queue.py          # persistent job queue
│       ├── schemas.py        # request models
│       ├── security.py       # auth / rate limiting / IP
│       ├── poseidon.py       # BN254 Poseidon hash
│       ├── abi.py            # contract ABI fragments
│       ├── metrics.py        # Prometheus metrics
│       └── logging_setup.py  # structlog configuration
├── tests/
├── scripts/
├── pyproject.toml
├── pytest.ini
└── run_tests.sh
```

## Environment Variables

All variables use the `RM_` prefix (Pydantic `env_prefix`).

| Variable | Default | Description |
|----------|---------|-------------|
| `RM_RPC_URL` | *(required)* | Horizen (or other chain) RPC endpoint |
| `RM_CHAIN_ID` | *(required)* | Chain ID the escrow contract is deployed on |
| `RM_RELAYER_PRIVATE_KEY` | *(required)* | EOA private key that signs and submits transactions |
| `RM_RELAYER_ESCROW_ADDRESS` | *(required)* | `RelayerEscrow` contract address |
| `RM_RELAYER_BEARER_TOKEN` | `None` | Bearer token required on all write endpoints; omit only with `RM_RELAYER_ALLOW_INSECURE_AUTH=true` |
| `RM_RELAYER_ALLOW_INSECURE_AUTH` | `false` | Skip bearer-token enforcement (dev only) |
| `RM_RELAYER_HOST` | `0.0.0.0` | Bind address |
| `RM_RELAYER_PORT` | `8088` | Bind port |
| `RM_RELAYER_MAX_RETRIES` | `3` | Transaction send retries before giving up |
| `RM_RELAYER_RETRY_BACKOFF_SECONDS` | `0.5` | Backoff between retries |
| `RM_RELAYER_TX_TIMEOUT_SECONDS` | `120` | Seconds to wait for tx receipt |
| `RM_RELAYER_MAX_BLOCK_AGE_SECONDS` | `60` | Max chain head age before health reports degraded |
| `RM_RELAYER_FEE_BUMP_PERCENT` | `0.15` | Gas price bump factor per retry attempt (15%) |
| `RM_RELAYER_PREFLIGHT_MODE` | `none` | Pre-send call simulation: `none`, `call`, `estimate`, `both` |
| `RM_RELAYER_MIN_BALANCE_WEI` | `0` | Minimum relayer native balance for health check |
| `RM_RELAYER_MIN_ESCROW_TOKEN_BALANCE_WEI` | `0` | Minimum escrow ERC-20 balance for health check |
| `RM_RELAYER_MIN_RELAYER_TOKEN_ALLOWANCE_WEI` | `0` | Minimum relayer ERC-20 allowance for health check |
| `RM_RELAYER_HTTP_TIMEOUT_SECONDS` | `10` | HTTP client timeout for RPC calls |
| `RM_RELAYER_RATE_LIMIT_REQUESTS` | `30` | Max requests per window (0 = disabled) |
| `RM_RELAYER_RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate limit sliding window |
| `RM_RELAYER_IP_ALLOWLIST` | *(empty)* | CSV of IPs/CIDRs allowed on write endpoints (empty = all) |
| `RM_RELAYER_TRUST_X_FORWARDED_FOR` | `false` | Honour `X-Forwarded-For` header for IP resolution |
| `RM_RELAYER_TRUSTED_PROXY_CIDRS` | *(empty)* | CSV of proxy CIDRs trusted to set `X-Forwarded-For` |
| `RM_RELAYER_QUEUE_DB_PATH` | `relayer_queue.db` | SQLite queue file path (unused when Postgres DSN set) |
| `RM_DATABASE_URL` | `None` | PostgreSQL DSN (`postgresql+psycopg2://...`); switches queue to Postgres |
| `RM_RELAYER_QUEUE_POLL_SECONDS` | `1.0` | Queue worker poll interval |
| `RM_RELAYER_QUEUE_MAX_ATTEMPTS` | `5` | Max attempts before moving job to dead-letter |
| `RM_RELAYER_QUEUE_MAX_PAYLOAD_BYTES` | `131072` | Max serialised payload size (128 KB) |
| `RM_RELAYER_QUEUE_RUNNING_TTL_SECONDS` | `tx_timeout + 30` | Running job lease duration before stale reclamation |
| `RM_RELAYER_API_BASE_URL` | `None` | Backend API URL for commit/settlement ingest hooks |
| `RM_RELAYER_API_BEARER_TOKEN` | `None` | Bearer token for relayer → API requests |
| `RM_RELAYER_API_INTERNAL_SECRET` | `None` | `X-Internal-Secret` header value for ingest calls |
| `RM_RELAYER_API_TIMEOUT_SECONDS` | `10` | HTTP timeout for ingest API calls |
| `RM_RELAYER_API_CLIENT_MAX_AGE_SECONDS` | `900` | Max age of the shared httpx client before recycling |
| `RM_RELAYER_API_HEALTH_FAILURE_COOLDOWN_SECONDS` | `15` | Cooldown before re-checking a failed API health endpoint |
| `RM_RELAYER_HEALTH_DEEP_CACHE_TTL_SECONDS` | `10` | TTL for cached deep health response |
| `RM_RELAYER_RPC_CIRCUIT_BREAKER_THRESHOLD` | `5` | RPC error count to open the circuit breaker |
| `RM_RELAYER_RPC_CIRCUIT_BREAKER_WINDOW_SECONDS` | `30.0` | Error counting window for the circuit breaker |
| `RM_RELAYER_RPC_CIRCUIT_BREAKER_COOLDOWN_SECONDS` | `30.0` | Cooldown before the circuit breaker closes |

## Tests

```bash
cd relayer && ./run_tests.sh
```
