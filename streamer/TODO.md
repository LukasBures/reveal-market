# Streamer TODO

- [ ] **Integration tests (mocked sockets)** – Simulate Polymarket CLOB + RTDS WS (book/price_change) with reconnects/staleness, assert publish payloads, history writes, and dedupe. Cover FX WS/REST fallbacks and staleness gates.
- [ ] **Control API** – Harden `/control/*` with auth + validation; expose current subscriptions, add/remove asset IDs/symbols, and document max_subscriptions/active_connection limits for ops dashboards.
- [ ] **HMAC signing doc** – Provide client verification examples (fields included, sort order, HMAC construction) and add a flag to disable signing when secret missing; test signature mismatch path.
- [ ] **Metrics & dashboards** – Gauges for per-market staleness, dropped messages, SSE delivery counts; Prometheus labels for source=ws/rest/rtds and fx_source. Extend `/dashboard` to surface staleness + active subscriptions.
- [ ] **History/debounce controls** – Allow per-market debounce tuning and trim history by age in addition to count; add tests for TTL expiry and debounced writes.
- [ ] **CORS/host enforcement** – Enforce `STREAMER_CORS_ALLOW_*` defaults with tests; healthcheck warning when frontend/API origins are missing or mismatched. Document reverse-proxy deployment guidance.
- [ ] **Bet cap note** – Mirror future on-chain caps (maxTicketStake/maxUserStakePerMarket) into streamer pricing if contracts expose them; keep messaging aligned with backend/front caps.
- [ ] **WS-first FX resiliency** – Ensure shared FX WS keeps retrying after HTTP fallback, with backoff logs and single-connection pooling; add tests for source switching and stale flags.
- [ ] **Network alignment** – Warn when MODE/env hosts diverge from Horizen Testnet defaults (chain id `2651420`, RPC `https://horizen-testnet.rpc.caldera.xyz/http`) or when streamer host differs from frontend/API origins.
