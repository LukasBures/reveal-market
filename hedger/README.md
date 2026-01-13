# Reveal Hedger

FastAPI service that tracks commit exposure, applies risk/FX guardrails, optionally places hedges via Polymarket, coordinates LP vault borrow/repay, and requests settlement proofs from the prover. The API surface is operator-focused under `/admin/*` with Prometheus metrics and a lightweight health endpoint.

```
Backend/chain commits -> Hedger (admin API)
      |                |-> Postgres (exposure ledger, offsets, settlements)
      |                |-> Redis (locks/idempotency)
      |                |-> Polymarket REST (quote/execute hedge)
      |                |-> LP Vault (borrow/repay)
      |                |-> Prover (settlement proofs)
      |                '--> Bridge client (manual ZEN/USDC moves)
```

## Responsibilities

- **Commit ingestion** (`POST /admin/commits`): validate FX freshness (FX oracle with optional alt feed + haircut/staleness checks), enforce per-commit cap, optional signed quote validation (`HEDGER_PRICING_SIGNER_ADDRESS`), and record commit exposure with Redis idempotency + DB uniqueness. Returns acceptance/duplicate/rejection reasons.
- **Risk & exposure**: Exposure ledger tracks YES/NO vectors per market, coverage ratios, and LP utilization. `RiskEngine` checks per-market/global limits, coverage target, LP utilization limit, float thresholds, and per-commit cap. Reports are exposed at `/admin/risk` and `/admin/positions`.
- **Hedging**: Pricing engine applies haircut/worsen/rake to commits; `PolymarketClient` can quote/execute hedges with slippage caps. LP vault client (on-chain by default) borrows/repays USDC for hedges; utilization and PnL feed metrics.
- **Settlement**: `POST /admin/settlements/{market_id}` triggers a settlement proof request to the prover using stored commits; responses are persisted and the market is marked resolved with exposure cleared. On-chain submission is not wired.
- **Bridge helper**: `POST /admin/bridge` proxies manual ZEN/USDC bridge requests to an external bridge endpoint with idempotency.
- **Ops surface**: `/healthz` (fx staleness, latest commit timestamp, LP utilization) and `/metrics` (hedge latency, prover latency, coverage ratio, event lag, utilization) plus structured heartbeat logs.

## API Endpoints

- `GET /healthz` – status + fx staleness + latest commit timestamp + LP utilization.
- `GET /metrics` – Prometheus scrape target.
- `/admin/exposures` – current exposure snapshots.
- `/admin/commits` (POST) – ingest a commit event (idempotent).
- `/admin/risk` – risk report for current exposures.
- `/admin/positions` – exposures + LP utilization.
- `/admin/settlements/{market_id}` (POST) – request prover payload for a market/outcome (payload in body).
- `/admin/bridge` (POST) – manual bridge request (`direction` `usdc_to_zen|zen_to_usdc`, `amount`, `destination`, optional `slippage_bps`).

All routes are open by default; front them with your preferred auth/proxy for production.

## Configuration Highlights

Defaults live in `app/config.py` (prefixed `HEDGER_`, many also aliased to `RM_`):

- **Core**: `RM_DATABASE_URL`/`HEDGER_DATABASE_URL` (asyncpg DSN), `HEDGER_REDIS_URL`, `HEDGER_RUN_MIGRATIONS_ON_STARTUP`.
- **Polymarket**: `HEDGER_POLYMARKET_API_BASE`, `HEDGER_POLYMARKET_TIMEOUT_SECONDS`, `HEDGER_POLYMARKET_RETRY_ATTEMPTS/BACKOFF_SECONDS`.
- **FX**: `HEDGER_FX_FEED_URL` (align with streamer FX), `HEDGER_FX_FEED_ALT_URL`, `HEDGER_FX_MAX_AGE_SECONDS`, `HEDGER_FX_HAIRCUT_BPS`, `HEDGER_FX_FALLBACK_PRICE`.
- **Pricing/risk**: `HEDGER_PRICING_SIGNER_ADDRESS` (optional signed-quote requirement), `HEDGER_RISK_MAX_COMMIT_ZEN`, `HEDGER_RISK_MAX_GLOBAL_EXPOSURE_USD`, `HEDGER_RISK_MAX_PER_MARKET_USD`, `HEDGER_RISK_COVERAGE_RATIO_TARGET`, `HEDGER_RISK_LP_UTILIZATION_LIMIT`, `HEDGER_FLOAT_MIN_ZEN`, `HEDGER_MAX_SLIPPAGE_BPS`, `HEDGER_HAIRCUT_PERCENT`, `HEDGER_WORSEN_PERCENT`, `HEDGER_RAKE_PERCENT`, `HEDGER_LP_SHARE_PERCENT`.
- **LP vault (required)**: `HEDGER_LP_VAULT_ADDRESS`, `HEDGER_VAULT_RPC_URL`, `HEDGER_VAULT_CHAIN_ID`, `HEDGER_VAULT_PRIVATE_KEY`, `HEDGER_VAULT_SENDER_ADDRESS`, `HEDGER_VAULT_GAS_PRICE_GWEI`. Missing values raise at startup (defaults are placeholder values).
- **Prover**: `HEDGER_PROVER_BASE_URL`, `HEDGER_PROVER_TIMEOUT_SECONDS`, `HEDGER_PROVER_SHARED_SECRET`.
- **Bridge**: `HEDGER_BRIDGE_ENDPOINT`.
- **Runtime**: `HEDGER_API_HOST/PORT`, `HEDGER_LOG_LEVEL`, `HEDGER_HEARTBEAT_INTERVAL_SECONDS`, `HEDGER_EVENT_POLL_INTERVAL_SECONDS`.

## Running & Testing

```bash
cd hedger
uv sync --extra dev --no-install-project
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8090

# Tests
uv run pytest       # or: ./run_tests.sh
```

Docker/compose: `./run_local.sh hedger` brings up dependencies (Postgres/Redis) and the hedger container.

## File Map

- `app/main.py` – FastAPI app creation, CORS/trusted host, heartbeat logger.
- `app/service.py` – core orchestration: commit ingestion, risk checks, hedging, settlement, bridge helpers, health.
- `app/config.py` – Pydantic settings with env aliases.
- `app/fx.py` – FX oracle with staleness/haircut and optional alt feed.
- `app/risk.py` / `app/exposure.py` – exposure ledger + risk engine.
- `app/pricing_engine.py` / `app/bet_processor_zen.py` – pricing with haircut/worsen/rake.
- `app/polymarket.py` – REST client (quote + execute) with retries/backoff.
- `app/vault.py` / `app/hedger_usdc.py` – LP vault client (on-chain) and borrow/repay helpers.
- `app/settlement.py` – prover client + settlement recording.
- `app/bridge.py` – bridge client for manual transfers.
- `app/admin.py` – `/admin/*` routes; `app/healthcheck.py` – Docker health probe (DB connectivity).

## Operational Notes

- Requires LP vault RPC/key/sender even in dev; defaults are placeholders only. Provide real values or use a local chain/fork.
- FX must be fresh for commit ingestion; stale or errored feeds return `fx_unavailable` rejections.
- Hedging calls Polymarket REST; failures are surfaced in responses and metrics. LP borrow/repay uses the configured vault client.
- Settlement requests only talk to the prover and database; on-chain submission is out of scope for this service.
