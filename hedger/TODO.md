# Hedger TODO

Short list of items to reach a functional hedger MVP.

## Ingestion & Recovery
- Stream Horizen commit events and backend outcome hints into the hedger; persist offsets/checkpoints for replay after downtime (per stream/partition).
- Redis locks + DB uniqueness on commits/settlements to prevent double-processing during catch-up; include request_id propagation.
- Gap fill when downtime > FX staleness window: reseed FX, re-poll missing events, and reconcile exposure vs DB; emit alerts when offsets jump.

## Hedging & Risk
- Replace Polymarket/vault stubs with real clients (auth, REST/GraphQL, contract calls); include slippage ceilings, partial unwind logic, fee bumps, and retry/backoff with idempotent identifiers.
- Track LP utilization + ZEN float from on-chain sources and enforce risk actions (throttle/pause/bridge top-ups). Persist float snapshots with reason codes.
- Bridge integration to move USDC→ZEN when float low and USDC→vault/bridge when PnL positive; add dry-run/test mode and alerting on failures.
- Expand risk metrics: slippage, fill quality, hedge latency, implied odds variance, hedge coverage ratio trend; expose via Prometheus + admin API.
- Enforce off-chain bet caps: per-bet (1000 ZEN default via `HEDGER_RISK_MAX_COMMIT_ZEN`), per-user-per-market, and per-market caps mirrored from API; reject before placement when caps are exceeded. Document future on-chain `maxTicketStake`/`maxUserStakePerMarket` mirror path.
- Keep envs/chain config aligned to Horizen Testnet defaults (chain id `2651420`, RPC `https://horizen-testnet.rpc.caldera.xyz/http`) when validating quote signatures, vault targets, and bridge destinations.

## Settlement
- Finalize prover payload assembly from stored commits + oracle outcome; handle disputed/late oracles and publish warnings when payload does not match DB expectations.
- Split settlement payloads into 256-ticket Poseidon batches and support `verifyAndSettleBatched` (one proof per batch root).
- Submit proofs on-chain and confirm state transitions; unwind hedges post-resolution and repay vault; retries/backoff + idempotency keys for prover + chain txs.
- Persist settlement receipts, rake distribution, hedger PnL for the market, and float adjustments; expose in admin API.
- Validate prover payload schema, add request_id tracing end-to-end, and alert on hash/verifier mismatches.
- Consume API-issued signed quotes (stake/fx/outcome-bound) and ensure hedger-side validation matches contract digest before hedging; reject if caps/staleness/expiry violated.

## Ops & API
- Harden admin API with authn/z; add endpoints for positions, PnL, risk limits, float levels, offsets, and event lags. Include pagination and filtering.
- Prometheus: gauges for float, LP utilization, hedge coverage ratios, hedge backlog, prover latency buckets per market, and bridge success/error counts.
- Logging: add request_id propagation across ingestion/hedge/settlement; include external request metadata (Polymarket/vault/bridge/prover) for auditing.

## Testing
- Unit + integration tests for FX staleness, risk breaches, hydration with hedges, unwind flows, and offset replay; include regression tests for duplicate commit ingestion.
- Smoke tests for real Polymarket/vault clients (integration-flagged) and bridge calls; add fixtures to replay recorded responses.
- Integration tests for settlement round-trip with prover stub, slippage gating, unwind execution paths, and idempotent retries.
- Load/chaos testing around Redis locks/idempotency and DB offsets; simulate Redis/DB outages and catch-up.
- CI wiring for hedger integration suite (env vars for external deps) and Alembic migration coverage; fail fast when migrations missing.

## Security & Ops Hardening
- Require auth (token/JWT) on admin API; validate external API responses; enforce request_id propagation through logs/metrics; rate-limit admin actions.
- Secrets management for Polymarket/vault/bridge creds; audit logging for admin actions + hedge triggers; configurable redaction for sensitive fields.
- Alerting/webhooks on risk breaches, settlement failures, FX staleness, and event lag; dashboards for float/utilization/PnL and prover latency.

## Deployability
- Alembic migration for hedger tables/columns; retention/backfill plan for commits/hedges/resolutions and offset compaction.
- Health probes that verify Redis/Postgres/polymarket/vault reachability; runbooks for replay/backfill, bridge failures, and prover outages.
- Sanity check frontend/API/streamer CORS alignment in staging so hedger metrics/health endpoints remain reachable through the stack; document port exposure and firewall expectations.
