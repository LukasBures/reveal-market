# Reveal Hedger

The Hedger keeps RevealMarket economically neutral while preserving privacy. It ingests commits, converts ZEN exposure into hedges on Base/Polymarket, manages LP vault utilization and float, coordinates proof-based settlement, and exposes operator-facing APIs/metrics.

## What’s inside
- FastAPI admin API (`/admin/...`) plus Prometheus metrics (`/metrics`) and health probes.
- Exposure + risk: tracks YES/NO vectors per market, net deltas, FX haircuts, coverage ratios, and risk limits; emits buy/sell/unwind hedge instructions (partial unwinds when over-hedged).
- FX + slippage: FX oracle cache with staleness enforcement and haircut; hedges are rejected if quotes exceed `HEDGER_MAX_SLIPPAGE_BPS`.
- Persistence + recovery: Postgres audit trails for commits (with idempotency keys), hedges (incl. unwind flag), settlements, float moves, risk actions, and replay offsets; restart hydration rebuilds exposures/hedged USD and offsets.
- Concurrency + idempotency: Redis locks + idempotency for commit ingestion and hedge execution, plus DB duplicate checks; stream offsets stored for replay safety.
- Metrics: exposures, net exposure, coverage ratio, LP utilization, float balance, PnL placeholders, event lag, hedge executions, and settlement/prover latency histograms.
- Settlement orchestration: builds prover payloads from stored commits + outcome, persists receipts, marks markets resolved, and clears exposure (on-chain submission is stubbed).

## Running locally
The Docker image is wired into `docker-compose.yml` as `hedger`. To start it alongside the rest of the stack:

```bash
./run_local.sh hedger
```

Useful env vars (defaults live in `app/config.py`):

- `HEDGER_DATABASE_URL` – Postgres URL (defaults to the shared `postgres` service).
- `HEDGER_REDIS_URL` – Redis URL for lightweight locks/state.
- `HEDGER_POLYMARKET_API_BASE` – Base URL for Polymarket REST/GraphQL.
- `HEDGER_FX_FEED_URL` – Trusted ZEN/USD feed.
- `HEDGER_FX_HAIRCUT_BPS` – FX haircut in basis points (e.g., 500 = 5% haircut).
- `HEDGER_RISK_MAX_GLOBAL_EXPOSURE_USD` – Cap on aggregate USD exposure.
- `HEDGER_RISK_MAX_PER_MARKET_USD` – Per-market exposure cap before throttling.
- `HEDGER_FLOAT_MIN_ZEN` – Minimum ZEN float before triggering a bridge top-up.
- `HEDGER_MAX_SLIPPAGE_BPS` – Max allowed slippage for hedge placement (bps).

API docs and metrics during local runs:
- Health: `http://localhost:8090/health`
- Admin: `http://localhost:8090/admin/exposures`, `.../risk`, `.../positions`
- Metrics: `http://localhost:8090/metrics`
