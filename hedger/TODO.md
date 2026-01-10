# Hedger TODO

Targeted work to harden the hedger now that core ingestion/risk/settlement flows exist.

## MVP-critical
- **Auth + rate limits**: Protect `/admin/*` routes with auth and optional rate limiting/IP allowlists; propagate `request_id` through logs/metrics.
- **Event ingestion & replay**: Wire a durable commit/settlement feed (backend or chain) with stored offsets and Redis idempotency to avoid manual POSTs; document replay/backfill steps.
- **Settlement on-chain**: Add optional on-chain settlement submission/unwind flows after prover responses, with retries/backoff and idempotency.

## Risk & Operations
- Persist offsets/heartbeats in metrics so lags are visible; alert on FX staleness or replay gaps.
- Expand risk checks to include per-user/per-market caps aligned with API, and surface breach reports in `/admin/risk`.
- Expose float/utilization/PnL metrics and snapshots via `/metrics` or admin endpoints; add alerts when utilization or float thresholds are crossed.

## Testing
- Integration tests for commit ingestion idempotency, FX staleness rejection, hedge placement (Polymarket client) with slippage caps, and settlement proof requests.
- Smoke tests for LP vault on-chain client and bridge client (gated by env flag). Add regression tests for duplicate commits/settlements.
