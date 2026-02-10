# Backend API

FastAPI service that exposes market data, pricing, trading, and internal ingestion endpoints.

**Entrypoint**
- `backend/api/app/server.py` builds the app, middleware, and background tasks.

**Public routes (high level)**
- `/events` list events with filters and caching.
- `/events/{event_id}` event detail and grouped markets.
- `/categories/{category_slug}` category list.
- `/pricing/*` FX quote and signed quote flow.
- `/trade/commit` commit a ticket via the relayer.
- `/trade/claim` initiate claim via the relayer.
- `/positions` wallet positions.
- `/claim/bundles` and `/claim/status` claim helpers.
- `/healthz`, `/healthz/deep`, `/ready`, `/live` health endpoints.

**Internal routes**
- `/internal/commitments/sync` and `/internal/settlements/ingest`.
- `/internal/relayer/*` relayer hooks.
- These require `X-Internal-Secret` and are blocked at the edge.

**Key behavior**
- Cache-aware market list endpoints with Redis tags.
- Pricing uses FX from streamer and signs QUOTE_V1 digest.
- Relayer calls use circuit breaker and optional queue.
- List endpoints emit slow-query alerts and cache observability metrics.
- Profiling endpoints are available behind internal auth.

**Config**
- See `backend/api/app/config.py` for all settings.
- Important: `RM_INTERNAL_API_SECRET`, `RM_PRICING_SIGNER_PRIVATE_KEY`, `RM_DATABASE_URL`, `RM_REDIS_URL`.

**Tests**
- `backend/run_tests.sh` (API portion).
