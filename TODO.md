# Reveal Market – MVP TODO (Current)

Only the items below are required to reach MVP. Ordered by priority.

## High
- **Streamer FX alignment**: API FX is hardcoded to `http://streamer:8100/fx/zen-usd` (`backend/api/app/pricing.py`). If your deployed streamer host/port differs, update the constant/env defaults and streamer docs; keep `/fx/zen-usd` stable.
- **Postgres migration/backfill**: apply Alembic head (`0001_initial_schema.py`) to Postgres and backfill normalized tables for legacy markets (outcomes/tags/clob tokens/gamma metadata), including `gamma_raw`.

## Medium
- **Cache/TTL policy**: resolved markets now expire from cache after `resolved_at + 12 hours`; document cache key/tag usage for ops and adjust if a different retention is required.
- **Streamer CORS/hosts**: confirm streamer CORS/allowed hosts align with frontend origin/WSS requirements; codify defaults and update env presets if the origin changes.

## Low
- **Docs alignment**: ensure service READMEs note normalized schema (no JSON outcomes/tags/clob IDs) and the streamer-only FX source; prune any stale references to switchable FX env vars.
