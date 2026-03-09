# Hedger

FastAPI service for real-time exposure tracking, Polymarket CLOB hedging, treasury management, and settlement coordination.

## Entrypoint

`hedger/app/main.py`

## Key Responsibilities

- Ingest commit events from the backend API and update per-market exposure ledgers.
- Size and execute hedge orders on the Polymarket CLOB (FAK market orders) to mirror user direction in USDC.
- Track FX rates (ZEN/USD) from the streamer with staleness enforcement and haircut application.
- Enforce risk limits: per-market exposure cap, global exposure cap, coverage ratio, and ZEN float minimum.
- Trigger proof generation via the prover service and coordinate on-chain settlement.
- Manage liquidity bridging between ZEN and USDC rails.
- Expose health, metrics, and admin endpoints.

## Hedging Model (v1)

The platform's primary exposure is FX (ZEN/USD), not outcome risk. When a user commits YES, the hedger buys YES on Polymarket; when a user commits NO, the hedger buys NO. Funding comes from the hot USDC.e wallet on Polygon (EOA). USDC allowances are pre-approved; `auto_approve=true` manages this automatically.

Flow: validate USDC.e balance → ensure allowance → submit FAK CLOB order → accept commit only if hedge succeeds.

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/healthz` | None | Returns cached health snapshot or `{"status":"ok","service":"hedger"}` |
| `GET` | `/healthz/deep` | None | Full health check (Redis, DB, FX, wallet); `?force=true` bypasses cache |
| `GET` | `/metrics` | None | Prometheus metrics (public) |
| `GET` | `/admin/exposures` | `X-Internal-Secret` | Per-market exposure snapshots |
| `GET` | `/admin/positions` | `X-Internal-Secret` | Alias for exposures list |
| `GET` | `/admin/risk` | `X-Internal-Secret` | Risk limit breach report (includes ZEN float balance) |
| `POST` | `/admin/commits` | `X-Internal-Secret` + writable | Ingest a commit event; triggers hedge execution |
| `POST` | `/admin/settlements/{market_id}` | `X-Internal-Secret` + writable | Trigger settlement proof request for a market |
| `POST` | `/admin/bridge` | `X-Internal-Secret` + writable | Manually trigger USDC↔ZEN bridge transfer |
| `GET` | `/admin/metrics` | `X-Internal-Secret` | Prometheus metrics (internal, same data as public `/metrics`) |

All `/admin/*` routes require the `X-Internal-Secret` header. Write routes additionally refuse when `HEDGER_ADMIN_READ_ONLY=true`.

## Modules

| Module | Description |
|--------|-------------|
| `main.py` | `create_app` — FastAPI factory; lifespan startup/shutdown, CORS/TrustedHost middleware, request ID middleware, admin rate limiting |
| `config.py` | `Settings` (Pydantic BaseSettings, `HEDGER_` prefix); all env var definitions |
| `service.py` | `HedgerService` — orchestrates exposure ingestion, hedge decisions, settlement triggers, float controls, and health snapshots |
| `admin.py` | Admin router — exposures, risk, commits ingest, settlements, bridge, internal metrics |
| `exposure.py` | `MarketExposure` / `ExposureLedger` — per-market YES/NO ZEN and USD tracking, coverage ratio, in-memory ledger with optional Redis persistence |
| `risk.py` | `RiskEngine` / `RiskLimits` — evaluates per-market and global exposure caps, coverage ratio target, and ZEN float minimum |
| `clob.py` | `HedgerClob` — Polymarket CLOB client wrapper (FAK market orders via `py-clob-client`) |
| `fx.py` | `FxOracle` — fetches and caches ZEN/USD quotes from the streamer; enforces staleness, applies haircut, falls back to alternate feed or configurable fallback price |
| `pricing_engine.py` | `PricingEngine` — deterministic ZEN bet pricing: haircut, worsen, rake percentages → `PricingQuote` |
| `bet_processor_zen.py` | `BetProcessorZen` — coordinates `PricingEngine` and `TreasuryManager` for bet settlement math |
| `settlement.py` | `SettlementCoordinator` — submits settlement payloads to the prover service and persists receipts |
| `treasury_manager.py` | `TreasuryManager` — dual ZEN/USDC ledger: records losing stakes, rake, USDC revenue, LP share allocation |
| `wallet.py` | `HedgerWallet` / `WalletConfig` — Polygon EOA: USDC.e balance, allowance checks, ERC-20 approval |
| `bridge.py` | `BridgeClient` — HTTP client for USDC↔ZEN bridge with retry (tenacity) |
| `storage.py` | `HedgerRepository` — SQLAlchemy async ORM; `hedger_commits` and `hedger_settlement_receipts` tables |
| `locks.py` | `RedisLockManager` — Redis-backed distributed locks and idempotency keys with in-memory fallback |
| `types.py` | Shared types: `CommitEvent`, `MarketExposureSnapshot`, `OutcomeSide`, `HedgeAction`, `RiskBreach`, `RiskSeverity`, `FxQuote`, `PricingQuote`, `SettlementBreakdown`, `TreasurySnapshot` |
| `metrics.py` | Prometheus metrics: exposure gauges, coverage ratio, float balance, hot wallet balance, hedge executions, risk breaches, settlement latency, prover latency |
| `rate_limit.py` | `RateLimiter` — sliding window rate limiter (synchronous, used for admin routes) |
| `local_logging.py` | `log_event` helper, request ID context var, heartbeat logger |
| `logging_config.py` | `setup_logging` — structured logging configuration |
| `healthcheck.py` | Standalone DB connection check script (used as a Docker health probe) |

## Directory Structure

```
hedger/
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI factory
│   ├── config.py             # settings
│   ├── service.py            # core orchestration
│   ├── admin.py              # admin router
│   ├── exposure.py           # exposure ledger
│   ├── risk.py               # risk engine
│   ├── clob.py               # Polymarket CLOB client
│   ├── fx.py                 # FX oracle
│   ├── pricing_engine.py     # bet pricing
│   ├── bet_processor_zen.py  # settlement math
│   ├── settlement.py         # prover coordination
│   ├── treasury_manager.py   # dual-ledger treasury
│   ├── wallet.py             # Polygon EOA / USDC.e
│   ├── bridge.py             # USDC↔ZEN bridge client
│   ├── storage.py            # async ORM / DB
│   ├── locks.py              # Redis locks + idempotency
│   ├── types.py              # shared data types
│   ├── metrics.py            # Prometheus metrics
│   ├── rate_limit.py         # rate limiter
│   ├── local_logging.py      # logging helpers
│   ├── logging_config.py     # logging setup
│   └── healthcheck.py        # DB health probe
├── tests/
├── run.py
├── pyproject.toml
├── pytest.ini
└── run_tests.sh
```

## Environment Variables

All variables use the `HEDGER_` prefix unless noted. `RM_DATABASE_URL` is accepted as an alias for the database URL.

### Server & General

| Variable | Default | Description |
|----------|---------|-------------|
| `HEDGER_ENVIRONMENT` | `prod` | Runtime environment (`local`, `dev`, `test`, `prod`); non-local enforces secrets |
| `HEDGER_LOG_LEVEL` | `INFO` | Log level |
| `HEDGER_API_HOST` | `0.0.0.0` | Bind address |
| `HEDGER_API_PORT` | `8090` | Bind port |
| `HEDGER_ALLOWED_HOSTS` | `["*"]` | CSV or JSON list of trusted hostnames; wildcard disallowed in prod |
| `HEDGER_CORS_ALLOW_ORIGINS` | `["*"]` | CSV or JSON list of CORS origins; wildcard disallowed in prod |
| `HEDGER_HEARTBEAT_INTERVAL_SECONDS` | `60` | Heartbeat log interval |
| `HEDGER_HEALTH_DEEP_CACHE_TTL_SECONDS` | `10` | Deep health check cache TTL |
| `HEDGER_RUN_MIGRATIONS_ON_STARTUP` | `true` | Run Alembic migrations at startup |
| `HEDGER_METRICS_ENABLED` | `true` | Enable Prometheus metrics |

### Admin

| Variable | Default | Description |
|----------|---------|-------------|
| `HEDGER_ADMIN_INTERNAL_SECRET` | `None` | Required `X-Internal-Secret` for all `/admin/*` routes; required in non-local environments |
| `HEDGER_ADMIN_READ_ONLY` | `false` | Freeze all write routes (commits, settlements, bridge) |
| `HEDGER_ADMIN_RATE_LIMIT_REQUESTS` | `30` | Max admin requests per window (0 = disabled) |
| `HEDGER_ADMIN_RATE_LIMIT_WINDOW_SECONDS` | `60` | Admin rate limit sliding window |

### Database & Redis

| Variable | Default | Description |
|----------|---------|-------------|
| `RM_DATABASE_URL` / `HEDGER_DATABASE_URL` | `postgresql+asyncpg://market_admin:<REDACTED>@postgres:5432/reveal_market` | PostgreSQL async DSN |
| `HEDGER_REDIS_URL` | `redis://redis:6379/0` | Redis connection URL |
| `HEDGER_REDIS_REQUIRED` | `false` | If true, hedging write routes enter read-only mode when Redis is unavailable |
| `HEDGER_REDIS_LOCK_TTL_SECONDS` | `10` | Distributed lock lease duration |
| `HEDGER_REDIS_IDEMPOTENCY_TTL_SECONDS` | `86400` | Idempotency key TTL (24 hours) |
| `HEDGER_COMMIT_STREAM_NAME` | `horizen_commits` | Redis stream name for commit events |

### Polymarket CLOB

| Variable | Default | Description |
|----------|---------|-------------|
| `HEDGER_POLYMARKET_CLOB_BASE` | `https://clob.polymarket.com` | Polymarket CLOB API base URL |
| `HEDGER_POLYMARKET_API_KEY` | `None` | CLOB API key |
| `HEDGER_POLYMARKET_API_SECRET` | `None` | CLOB API secret |
| `HEDGER_POLYMARKET_API_PASSPHRASE` | `None` | CLOB API passphrase |
| `HEDGER_POLYMARKET_TIMEOUT_SECONDS` | `10` | CLOB request timeout |
| `HEDGER_POLYMARKET_RETRY_ATTEMPTS` | `3` | CLOB retry attempts |
| `HEDGER_POLYMARKET_RETRY_BACKOFF_SECONDS` | `0.5` | CLOB retry backoff |
| `HEDGER_MAX_SLIPPAGE_BPS` | `100` | Max acceptable slippage for hedge orders (bps) |
| `HEDGER_MIN_FILL_PERCENT` | `90` | Minimum fill percentage to accept a hedge order |

### FX Oracle

| Variable | Default | Description |
|----------|---------|-------------|
| `HEDGER_FX_FEED_URL` | `http://streamer:8100/fx/zen-usd` | Primary ZEN/USD feed URL |
| `HEDGER_FX_FEED_ALT_URL` | `None` | Secondary FX feed (used only if primary is unreachable or stale) |
| `HEDGER_FX_TIMEOUT_SECONDS` | `5` | FX fetch timeout |
| `HEDGER_FX_MAX_AGE_SECONDS` | `60` | Max quote age before stale |
| `HEDGER_FX_HAIRCUT_BPS` | `500` | FX haircut applied to hedge sizing (500 = 5%) |
| `HEDGER_FX_FALLBACK_PRICE` | `1` | ZEN/USD fallback when feed is down |
| `HEDGER_PRICING_SIGNER_ADDRESS` | `None` | Expected signer address for API-issued quotes (optional validation) |

### Wallet & Polygon

| Variable | Default | Description |
|----------|---------|-------------|
| `HEDGER_HEDGER_PRIVATE_KEY` | `None` | EOA private key for Polygon hot wallet |
| `HEDGER_HEDGER_ADDRESS` | `None` | EOA address (optional; derived from key if unset) |
| `HEDGER_POLYGON_RPC_URL` | `https://polygon-rpc.com` | Polygon JSON-RPC endpoint |
| `HEDGER_POLYGON_CHAIN_ID` | `137` | Polygon chain ID |
| `HEDGER_USDC_ADDRESS` | `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` | USDC.e contract address |
| `HEDGER_USDC_DECIMALS` | `6` | USDC.e token decimals |
| `HEDGER_POLYMARKET_EXCHANGE` | `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` | Polymarket exchange (USDC spender) address |
| `HEDGER_AUTO_APPROVE` | `true` | Auto-approve USDC allowance when insufficient |

### Risk Limits

| Variable | Default | Description |
|----------|---------|-------------|
| `HEDGER_RISK_MAX_GLOBAL_EXPOSURE_USD` | `250000` | Global absolute exposure cap in USD |
| `HEDGER_RISK_MAX_PER_MARKET_USD` | `75000` | Per-market absolute exposure cap in USD |
| `HEDGER_RISK_COVERAGE_RATIO_TARGET` | `0.98` | Minimum hedge coverage ratio (warn/breach if below) |
| `HEDGER_FLOAT_MIN_ZEN` | `5000` | Minimum ZEN float balance for risk check |
| `HEDGER_RISK_MAX_COMMIT_ZEN` | `1000` | Per-commit stake limit in ZEN |
| `HEDGER_RISK_CATEGORY_LIMITS` | `None` | JSON map of market category to max USD exposure, e.g. `{"crypto":50000}` |

### Pricing & Revenue

| Variable | Default | Description |
|----------|---------|-------------|
| `HEDGER_RAKE_PERCENT` | `0.02` | Protocol rake taken from each stake (2%) |
| `HEDGER_HAIRCUT_PERCENT` | `0.12` | FX haircut percentage applied when sizing hedge (12%) |
| `HEDGER_WORSEN_PERCENT` | `0.03` | Price worsening applied to displayed payout (3%) |
| `HEDGER_LP_SHARE_PERCENT` | `0.18` | LP revenue share of platform USDC proceeds (18%) |

### Settlement & Bridge

| Variable | Default | Description |
|----------|---------|-------------|
| `HEDGER_PROVER_BASE_URL` | `http://prover:8085` | Prover service base URL |
| `HEDGER_PROVER_TIMEOUT_SECONDS` | `30` | Prover request timeout |
| `HEDGER_PROVER_SHARED_SECRET` | `None` | `X-Prover-Secret` header value for prover requests |
| `HEDGER_BRIDGE_ENDPOINT` | `https://bridge.revealmarket.xyz/submit` | Bridge API submit URL |
| `HEDGER_SETTLEMENT_POLL_SECONDS` | `20` | Settlement status polling interval |
| `HEDGER_EVENT_POLL_INTERVAL_SECONDS` | `10` | On-chain event polling interval |

## Tests

```bash
cd hedger && ./run_tests.sh
```
