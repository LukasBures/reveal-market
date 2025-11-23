# Price Streamer TODO

- Add integration tests against a Polymarket WS mock that emit bursts, gaps, and malformed payloads to validate reconnect + debounce.
- Emit Prometheus gauges for per-market stale durations and SSE subscriber counts.
- Sign FX/price payloads for clients that want integrity verification.
- Build candle aggregation worker feeding a `/candles` endpoint for charts.
- Add configurable rate limits and auth on SSE to avoid abuse.
