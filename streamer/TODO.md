# Streamer TODO

- Add alerts for FX staleness, CLOB stream stalls, and history backlog growth; surface stale asset lists in metrics for monitoring.
- Pipeline optimizations: batch Redis writes/publishes in `StreamState.cache_tick` and reuse HTTP clients for REST polls to cut CPU on high-traffic markets.
- Optional: config presets to cap UVicorn workers vs CPU limit and document recommended settings for prod.
