# Streamer TODO

**MVP - Critical**
- Ensure CORS and public URL presets are aligned for WS/SSE.
- Confirm Redis history trimming is enforced for long-running streams.

**MVP - High**
- Add optional auth for SSE/WS using access token.

**MVP - Medium**
- Add metrics for stale market detection and FX staleness.

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
