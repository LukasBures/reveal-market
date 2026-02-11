# Streamer TODO

**MVP Critical**
- Confirm Redis history trimming is enforced for long-running streams.

**MVP High**
- Validate rate-limit/connection guard defaults under expected load.

**MVP Medium**
- Add tests for control endpoints and subgraph proxy error handling.

**MVP Nice to have**
- Add backpressure when active connections exceed capacity.

**Production Critical**
- Ensure WS/SSE reconnect policies are tuned for prod traffic.
