# Backend TODOs & Enhancements

This list captures remaining items that would strengthen reliability, developer experience, or production readiness beyond the current MVP scope.

## High Priority

- **End-to-end migrations in worker startup**  
  The worker assumes migrations have run. Add an optional flag to apply migrations (or at least assert schema version) when the worker starts, preventing subtle schema drift in single-service deployments.

- **Cache invalidation granularity**  
  Current invalidation wipes all list caches. Introduce smarter invalidation (e.g., tag-based keys or cache versioning) to avoid evicting every list page when only one market updates. This keeps cache hit rates high as traffic grows.

- **Better error handling around Polymarket API**  
  Add retries with exponential backoff and surfaced metrics for failures/timeouts. Prevents temporary upstream hiccups from generating noisy logs and gives better visibility when the feed degrades.

- **Contract awareness in backend/worker**  
  Today the backend never touches on-chain state. Add Web3 clients (e.g., `web3.py` with async providers), wire the new `.env` contract variables (`RM_FACTORY_ADDRESS`, etc.), and implement flows to open/monitor markets and handle failures. Ensure all interactions emit structured logs.

- **More comprehensive tests**  
  Add integration tests that spin up ephemeral Postgres/Redis (via pytest-docker) to cover migrations + caching end-to-end, and property tests for cache key generation. Ensures production-like confidence before shipping changes.

## Medium Priority

- **Config reloading / dynamic tuning**  
  Currently all settings require restarts. Supporting dynamic reload (e.g., SIGHUP to re-read environment or a small admin endpoint) would allow tuning poll intervals or TTLs without downtime.

- **API rate limiting / request throttling**  
  Consider adding simple rate limits (via Redis or a gateway) once public traffic hits the endpoints to shield the database from unexpected load.

- **Dedicated cache namespace per environment**  
  Introduce an `RM_CACHE_NAMESPACE` env var to prevent key collisions when multiple environments share the same Redis (useful on shared infrastructure or during blue/green deployments).

## Low Priority / Nice-to-have

- **Structured tracing / OpenTelemetry**  
  Add request-level tracing (OTLP exporter) to tie together API requests with worker fetch cycles for richer observability.

- **Alerting playbooks**  
  Document how to interpret key logs/metrics (`worker.fetch.empty`, heartbeat misses, cache miss spikes) and recommended responses. Beneficial when handing off to ops teams.

- **Autoscaling hooks**  
  Provide docs or scripts for scaling workers/API containers (CPU-based or backlog-based) should Polymarket ingest rates increase.

Each item is valuable, but prioritise “Schema safety for worker”, “Smarter cache invalidation”, and “Polymarket retries” first—they protect correctness and availability as usage grows.
