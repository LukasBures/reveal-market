# Streamer TODO

- [ ] Add integration tests with mocked Polymarket CLOB and RTDS sockets (book/price_change) to verify subscription payloads, reconnect, and staleness.
- [ ] Expose a lightweight control API for adding/removing asset IDs/symbols and inspect current subscription state.
- [ ] Optional HMAC signing verification example for clients (document payload fields, signature construction).
- [ ] Add metrics for per-market staleness, dropped messages, and SSE delivery counts; export Prometheus labels for source=ws/rest/rtds and fx_source.
- [ ] Support configurable debounce per market/outcome and bounded history trimming by age.
- [ ] Document recommended CORS/allowed-origins when deploying behind a reverse proxy.
- [ ] Enforce configurable CORS defaults (STREAMER_CORS_ALLOW_*) in code/tests and add a healthcheck to warn when frontend origins are missing.
- [ ] Wire on-demand subscription control API and document max_subscriptions behavior for ops; surface current FX/market staleness in a dashboard.
- [ ] Note future on-chain caps: mirror off-chain bet caps (maxTicketStake/maxUserStakePerMarket) once contracts expose them.
- [ ] Ensure WS-first FX flow with shared connections keeps retrying WS after HTTP fallbacks; add tests/logs for backoff + single-connection pooling and data-source selection logging.
- [ ] Keep streamer env/host aligned to Horizen Testnet defaults (chain id `2651420`, RPC `https://horizen-testnet.rpc.caldera.xyz/http`) and warn when origins don’t match frontend/API hosts.
