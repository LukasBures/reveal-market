# Reveal Hedger

The Hedger keeps RevealMarket economically neutral while preserving privacy. It ingests commits, converts ZEN exposure into hedges on Base/Polymarket, manages LP vault utilization and float, coordinates proof-based settlement, and exposes operator-facing APIs/metrics.

## What’s inside
- FastAPI admin API (`/admin/...`) plus Prometheus metrics (`/metrics`) and health probes.
- Exposure + risk: tracks YES/NO vectors per market, net deltas, FX haircuts, coverage ratios, and risk limits; emits buy/sell/unwind hedge instructions (partial unwinds when over-hedged).
- FX + slippage: FX oracle cache with staleness enforcement and haircut; hedges are rejected if quotes exceed `HEDGER_MAX_SLIPPAGE_BPS`.
- Persistence + recovery: Postgres audit trails for commits (with idempotency keys), hedges (incl. unwind flag), settlements, float moves, risk actions, and replay offsets; restart hydration rebuilds exposures/hedged USD and offsets.
- Concurrency + idempotency: Redis locks + idempotency for commit ingestion and hedge execution, plus DB duplicate checks; stream offsets stored for replay safety.
- Metrics: exposures, net exposure, coverage ratio, LP utilization, float balance, PnL placeholders, event lag, hedge executions, and settlement/prover latency histograms.
- Settlement orchestration: builds per-batch prover payloads (Poseidon depth-8 roots, 256 tickets) from stored commits + outcome, persists receipts, marks markets resolved, and clears exposure (on-chain submission is stubbed).
- Pricing guardrails: hedges refuse stale FX and enforce per-commit stake caps; default cap is 1000 ZEN (tune via `HEDGER_RISK_MAX_COMMIT_ZEN`) and haircuts/worsen/rake are applied server-side.

### Current implementation snapshot
- **State model** – `hedger_commits`, `hedger_hedge_actions`, `hedger_settlements`, `hedger_offsets`, `hedger_resolved_markets`, and `hedger_treasury_snapshots` store everything needed to replay exposure and audit hedging/settlement decisions. Hydration rebuilds YES/NO vectors and hedged USD on startup.
- **Exposure ingestion** – Commit ingestion path expects backend/chain events with idempotency keys; Redis locks + DB uniqueness stop duplicate exposure. Offsets mark last processed commit/stream slot for replay.
- **Risk/FX gating** – FX cache enforces staleness + haircut; slippage ceiling via `HEDGER_MAX_SLIPPAGE_BPS`. Risk checks enforce per-commit cap (1000 ZEN default), optional per-market/global caps, and coverage ratio thresholds before emitting hedge instructions.
- **Hedging actions** – Buy/sell/unwind instructions are persisted with execution payloads/response bodies; partial unwinds occur when over-hedged. Polymarket/vault bridges are stubbed but the control surface (state + retries) is in place.
- **Settlement path** – Given stored commits + oracle outcome, the hedger builds per-batch prover payloads (BATCH_SIZE=256), requests proofs, stores receipts, marks resolved markets, and clears exposure. Tx submission is stubbed; logs/metrics cover latency and retries.
- **API/metrics** – Admin API exposes exposures, risk config, positions, offsets, and settlements; Prometheus histograms for hedge latency, prover latency, coverage ratios, and event lag. Health probes check Postgres + Redis + FX reachability.

## Running locally
The Docker image is wired into `docker-compose.yml` as `hedger`. To start it alongside the rest of the stack:

```bash
./run_local.sh hedger
```

Useful env vars (defaults live in `app/config.py`):

- `RM_DATABASE_URL` – Postgres URL (defaults to the shared `postgres` service).
- `HEDGER_REDIS_URL` – Redis URL for lightweight locks/state.
- `HEDGER_POLYMARKET_API_BASE` – Base URL for Polymarket REST/GraphQL.
- `HEDGER_FX_FEED_URL` – Trusted ZEN/USD feed (align with API/streamer endpoint, e.g., http://streamer:8100/fx/zen-usd).
- `HEDGER_FX_FEED_ALT_URL` – Optional secondary FX feed used if the primary feed is unreachable.
- `HEDGER_FX_HAIRCUT_BPS` – FX haircut in basis points (e.g., 500 = 5% haircut).
- `HEDGER_PRICING_SIGNER_ADDRESS` – If set, all commits must carry a signed quote from this address; validation occurs before hedging.
- `HEDGER_RISK_MAX_GLOBAL_EXPOSURE_USD` – Cap on aggregate USD exposure.
- `HEDGER_RISK_MAX_PER_MARKET_USD` – Per-market exposure cap before throttling.
- `HEDGER_FLOAT_MIN_ZEN` – Minimum ZEN float before triggering a bridge top-up.
- `HEDGER_MAX_SLIPPAGE_BPS` – Max allowed slippage for hedge placement (bps).
- `HEDGER_PROVER_SHARED_SECRET` – Optional shared secret; when set, the hedger sends `X-Prover-Secret` to the prover.
- Network defaults: Horizen Testnet (chain id `2651420`, RPC `https://horizen-testnet.rpc.caldera.xyz/http`, explorer `https://horizen-testnet.explorer.caldera.xyz`). Keep signer/treasury addresses and pricing chain id aligned with this network when running end-to-end demos.

API docs and metrics during local runs:
- Health: `http://localhost:8090/health`
- Admin: `http://localhost:8090/admin/exposures`, `.../risk`, `.../positions`
- Metrics: `http://localhost:8090/metrics`
