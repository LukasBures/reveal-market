# Hedger TODO

Short list of items to reach a functional hedger MVP.

## Ingestion & Recovery
- Stream Horizen commit events and backend outcome hints into the hedger; persist offsets/checkpoints for replay after downtime.
- Add Redis-based idempotency/locks to prevent double-processing commits during catch-up.
- Implement gap fill when downtime > FX staleness window (reseed FX, re-poll missing events).

## Hedging & Risk
- Replace Polymarket/vault stubs with real clients (auth, REST/GraphQL, contract calls), including slippage + partial unwind logic.
- Track LP utilization + ZEN float from on-chain sources and enforce risk actions (throttle, pause, bridge top-ups).
- Add bridge integration to move USDC→ZEN when float low and USDC→vault/bridge when PnL positive.
- Expand risk metrics: slippage, fill quality, hedge latency, implied odds variance.
- Enforce off-chain bet caps: per-bet (100 ZEN), per-user-per-market, and per-market caps mirrored from API; reject hedges before placement when caps are exceeded. Document future on-chain maxTicketStake/maxUserStakePerMarket.

## Settlement
- Build prover payload assembly from stored commits + oracle outcome; handle disputed/late oracles.
- Submit proofs on-chain and confirm state transitions; unwind hedges post-resolution and repay vault.
- Persist settlement receipts + rake distribution accounting for float models.
- Validate prover payload against schema, add retries/backoff, and wire request_id tracing for prover + settlement submissions.
- Add disputed/late outcome handling that pauses unwinds and surfaces risk alerts.

## Ops & API
- Harden admin API with authn/z; add endpoints for positions, PnL, risk limits, float levels, and event lags.
- Prometheus: add gauges for float, LP utilization, hedge coverage ratios, and prover latency buckets per market.
- Logging: add request_id propagation across ingestion/hedge/settlement flows.

## Testing
- Add unit + integration tests for FX staleness, risk breaches, hydration with hedges, and unwind flows.
- Add smoke tests for the real Polymarket/vault clients (flagged as integration) and for bridge calls.
- Integration tests for settlement round-trip with prover stub, replay offsets, slippage gating, and unwind execution paths.
- Load/chaos testing around Redis locks/idempotency and DB offsets.
- CI wiring for hedger integration suite (with env vars for external deps), plus Alembic migration coverage.

## Security & Ops Hardening
- Require auth (token/JWT) on admin API; validate external API responses; enforce request_id propagation through logs/metrics.
- Secrets management for Polymarket/vault/bridge creds; audit logging for admin actions.
- Add alerting/webhooks on risk breaches, settlement failures, and event lag; dashboards for float/utilization/PnL.

## Deployability
- Alembic migration for hedger tables/columns; data retention/backfill plan for commits/hedges/resolutions.
- Health probes that verify Redis/Postgres/polymarket/vault reachability; runbooks for replay/backfill and incident handling.
