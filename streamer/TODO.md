# Streamer TODO (MVP)

- [ ] **Upstream health visibility** – Track CLOB WS/REST + RTDS connectivity and last message timestamps; surface in `/healthz` and `/metrics` so ops can tell when ingestion is live.
- [ ] **FX fallback policy** – Decide whether to publish market ticks when FX is stale/fallback (currently skipped unless `fallback`); align streamer semantics with backend/frontend expectations.
- [ ] **Configurable CLOB REST URL** – Move the hardcoded `https://clob.polymarket.com/markets` into settings (e.g., `STREAMER_CLOB_REST_URL`) so staging/testnet upstreams can override without code changes.
- [ ] **Client bootstrap** – Optionally send the latest cached tick on SSE/WS connect (or document required `/clob/latest` prefetch) so quiet markets render immediately.
