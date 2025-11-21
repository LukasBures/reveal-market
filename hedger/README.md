# Reveal Hedger

The Hedger is the off-chain controller that keeps RevealMarket economically neutral while preserving user privacy. It listens to commits on Horizen, converts ZEN exposure into hedges on Base/Polymarket, manages LP vault utilization, performs FX haircuts, coordinates settlement with the prover, and exposes operator-facing APIs/metrics.

## What’s inside
- FastAPI admin API (`/admin/...`) plus Prometheus metrics (`/metrics`) and health probes.
- Exposure ledger that tracks YES/NO vectors per market, net deltas, FX haircuts, and risk limits (per-market and global).
- FX oracle cache with staleness enforcement so hedges are never sized off stale prices.
- Polymarket + Base LP vault clients with retry-aware HTTP calls; hedging planner that emits buy/sell instructions and tracks realized/unrealized PnL.
- Postgres-backed audit trails for commits, hedges, settlements, float movements, and risk actions to guarantee crash-safe recovery.
- Concurrency controls (async locks) around book mutations to keep hedges serialized even under load.
- Settlement orchestration stubs that prepare prover inputs, wait for Groth16 proof generation, and push receipts on-chain before unwinding hedges.
- On restart, the hedger hydrates exposure + hedge state from Postgres aggregates so short outages can resume hedging without drifting.
- Redis-backed idempotency + locking pairs with DB offsets to replay event streams without double-processing commits or hedges.
- Prometheus metrics now include float/LP utilization gauges, event lag, PnL placeholders, and settlement latency histograms.
- Hedging planner enforces slippage limits, aborts quotes that exceed `HEDGER_MAX_SLIPPAGE_BPS`, and emits unwind instructions when over-hedged.
- Settlement path can build prover payloads from stored commits, persist receipts, and mark markets resolved (on-chain submission is stubbed).

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

API docs and metrics during local runs:
- Health: `http://localhost:8090/health`
- Admin: `http://localhost:8090/admin/exposures`, `.../risk`, `.../positions`
- Metrics: `http://localhost:8090/metrics`
