# Streamer TODO

**MVP - Critical**
- Confirm Redis history trimming is enforced for long-running streams.

**MVP - High**
- Validate rate-limit/connection guard defaults under expected load.

**MVP - Medium**
- Add metrics for stale market detection and FX staleness.
- Add tests for control endpoints and subgraph proxy error handling.

**MVP - Low**
- Add better error surfacing for subgraph endpoints.

**MVP - Nice to have**
- Add backpressure when active connections exceed capacity.

**Production - Critical**
- Ensure WS/SSE reconnect policies are tuned for prod traffic.

**Production - High**
- Add regional redundant streamer and failover for FX.

**Production - Medium**
- Add message sampling for payload size analysis.

**Production - Low**
- Add per-client rate limits for SSE/WS.

**Production - Nice to have**
- Add static snapshots for pre-warming cache.
