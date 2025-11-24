# Price Streamer TODO

- [ ] Add integration tests with mocked Polymarket CLOB and RTDS sockets (book/price_change, crypto_prices) to verify subscription payloads, reconnect, and staleness.
- [ ] Expose a lightweight control API for adding/removing asset IDs/symbols and inspect current subscription state.
- [ ] Optional HMAC signing verification example for clients (document payload fields, signature construction).
- [ ] Add metrics for per-market staleness, dropped messages, and SSE delivery counts; export Prometheus labels for source=ws/rest/rtds.
- [ ] Support configurable debounce per market/outcome and bounded history trimming by age.
- [ ] Document recommended CORS/allowed-origins when deploying behind a reverse proxy.
- [ ] Wire on-demand subscription control API and document max_subscriptions behavior for ops; surface current FX/market staleness in a dashboard.
- [ ] Note future on-chain caps: mirror off-chain bet caps (maxTicketStake/maxUserStakePerMarket) once contracts expose them.
