# Reveal Market TODO

## MVP
- MVP blockers are tracked in `MVP.md` and the service-specific TODOs; nothing is duplicated here.

## Production/Mainnet Readiness
- **Secrets & configs**: lock real RPCs/API keys in secret managers; audit `.env` usage and ensure defaults reference testnet only. Align chain IDs across API/worker/frontend/contract envs.
- **Prover artifacts**: ensure `prover/circuits/build` contains the latest audited zkey/WASM, hash-verify them at startup, and pin `PROVER_RAPIDSNARK_BINARY`/Node versions in deployment manifests.
- **DB & migrations**: apply Alembic head to production Postgres, confirm `settlement_receipts`/resolution tables are indexed, and backfill any legacy market rows into normalized tables.
- **Batch settlement**: validate `batch_roots`/`batch_counts` ingestion, per-batch proof receipts, and `verifyAndSettleBatched` on a >256 commitment market (BATCH_SIZE=256, MERKLE_DEPTH=8).
- **Caching/CORS**: confirm streamer CORS/hosts match frontend origin (HTTPS for WSS), and revisit cache TTLs for resolved markets if production needs longer/shorter retention.
- **Monitoring/alerts**: scrape `/metrics` (API, worker, prover, streamer), add alerts for proof failures/latency, cache miss spikes, and health endpoints; capture pprof profiles in staging under load.

## Performance Optimizations (Per Running Container)

### Streamer (highest CPU)
- Batch Redis writes in `StreamState.cache_tick` using pipelines/Lua (HSET + PUBLISH + LPUSH + EXPIRE) to reduce per-tick round-trips. (`streamer/app/state.py`, `streamer/app/data_streamer.py`)
- Reuse long-lived `httpx.AsyncClient` for REST polling and FX refresh instead of creating per-loop clients. (`streamer/app/data_streamer.py`, `streamer/app/state.py`)
- Reduce per-tick Decimal parsing: precompute worsen factor; use float internally then stringify once. (`streamer/app/data_streamer.py`)
- Gate orderbook depth parsing behind env toggle to avoid heavy per-message work when not needed. (`streamer/app/data_streamer.py`)
- Align `UVICORN_WORKERS` with CPU limit (currently 0.5 CPU); set to 1 or raise CPU limit. (`docker-compose.yml`)

### Worker (DB + cache heavy)
- Replace normalized-table ORM upserts with bulk SQL upserts to reduce per-market overhead. (`backend/worker/app/market_sync.py`)
- Reduce flush/commit frequency; increase `RM_POLYMARKET_COMMIT_BATCH_SIZE` and avoid per-page flush unless necessary. (`backend/worker/app/service.py`)
- Cache commitment counts per tick instead of per page to reduce repeated queries. (`backend/worker/app/market_sync.py`)
- Skip gamma event rewrites when `content_hash` unchanged; short-circuit normalized work. (`backend/worker/app/market_sync.py`)

### API (cache miss path)
- Move sort/order_by into SQL for volume/popularity; avoid Python resort on large lists. (`backend/api/app/routes/markets.py`, `backend/api/app/services/markets.py`, `backend/api/app/crud.py`)
- Enrich only the final slice (after limit/offset) to reduce heavy `enrich_market_models` work. (`backend/api/app/routes/markets.py`)
- Prefer caching event_id lists + lazy hydrate more broadly to reduce cache payload size. (`backend/api/app/services/markets.py`)

### Relayer (queue)
- Allow multiple queue workers with `SELECT ... FOR UPDATE SKIP LOCKED` (PG path) and remove global lock for PG. (`relayer/src/relayer/queue.py`)
- Batch queue depth metrics on a timer instead of per job to reduce DB reads. (`relayer/src/relayer/queue.py`)

### Prover
- Set `PROVER_TEMP_DIR` to tmpfs to reduce I/O latency. (`docker-compose.yml`, `prover/main.go`)
- Set `PROVER_MAX_CONCURRENCY=1` for 1 CPU limit to avoid context switching. (`prover/internal/shared/config.go`)
- Prefer `PROVER_WITNESS_BINARY` (C++ witnesscalc) to avoid Node overhead. (`prover/groth16_prover.go`)

### Redis
- Ensure all cache keys have TTLs or switch eviction to `allkeys-lru`; `volatile-lru` keeps non-TTL keys forever. (`docker/redis/redis.conf`, `streamer/app/state.py`, `backend/shared/cache_async.py`)
- Reduce payload sizes (compact JSON; drop redundant fields) for tick/history entries. (`streamer/app/state.py`)

### Postgres
- Confirm indexes on market list filters (status/category/volume/updated_at) and normalized tables by `market_id`. (`backend/migrations/*`)
- Review pool sizing for API/worker if pool waits appear; adjust `RM_DATABASE_POOL_SIZE`/`RM_DATABASE_MAX_OVERFLOW`. (`backend/api/app/config.py`, `backend/worker/app/database.py`)


___

• Below is a deep, per‑container performance review based on the code + current runtime config. I focused on hotspots, I/O patterns, and concurrency/CPU limits. I included concrete file refs for anything I’d change.

  Quick runtime notes from docker stats:

  - reveal-market-streamer is the only CPU‑heavy service (≈20% with a 0.5 CPU limit). It’s the primary bottleneck.
  - reveal-market-worker is memory‑heavy (≈316MB) and very DB/Redis chatty.
  - Redis is using ~491MB with maxmemory 768MB and volatile-lru (keys without TTL never evict).
  - Postgres is ~658MB; tuned, but parallelism is capped to 2 workers per gather.

  ———

  Top 5 speed wins (highest impact first)

  1. Streamer: reduce per‑tick CPU + Redis round‑trips
      - In streamer/app/data_streamer.py, each tick path does multiple Decimal conversions and per‑tick Redis hset + publish + lpush. This is the CPU hotspot.
      - Fix: batch hset/publish/lpush via pipeline in StreamState.cache_tick() and only JSON encode once. Add optional drop‑unchanged fields (price + timestamp only).
      - Files: streamer/app/data_streamer.py, streamer/app/state.py
  2. Worker: reduce DB churn per page
      - collect_market_changes_with_summary() does a lot of per‑market work and repeated normalized table queries. It does prefetch, but still per‑market decisions + ORM overhead.
      - Fix: switch normalized tables to bulk upserts (SQLAlchemy core) and reduce per‑market ORM writes; reduce session.flush() frequency (flush every N pages or only on commit).
      - Files: backend/worker/app/market_sync.py, backend/worker/app/service.py
  3. API: avoid Python sorting + enrichment when DB can do it
      - /markets and /categories fetch, then enrich_market_models() + Python sort. That’s expensive on cache misses.
      - Fix: push order_by and aggregation into SQL (especially volume/popularity); defer enrichment to only the slice needed.
      - Files: backend/api/app/routes/markets.py, backend/api/app/services/markets.py, backend/api/app/crud.py (not opened yet but likely)
  4. Redis: eviction policy mismatch
      - Current volatile-lru means any key without TTL never evicts → memory pressure spikes.
      - Fix: ensure all cache keys have TTLs or switch to allkeys-lru if you want hard memory protection.
      - Files: docker/redis/redis.conf, backend/shared/cache_async.py, streamer/app/state.py (history TTLs)
  5. Streamer CPU vs workers mismatch
      - Streamer has UVICORN_WORKERS=2 but only 0.5 CPU in compose; extra workers = context switching, not throughput.
      - Fix: set workers to 1 or raise CPU limit.
      - Files: docker-compose.yml (streamer env), docker/streamer/Dockerfile

  ———

  Per‑container deep analysis & targeted optimizations

  ### 1) reveal-market-streamer (FastAPI + WS/SSE)

  Hotspots

  - Heavy JSON parsing and Decimal math per tick in DataStreamer._normalize_and_publish(); per‑tick Redis ops in StreamState.cache_tick().
  - DataStreamer._flush_loop() builds _publish_cache then iterates each entry individually (still per‑key Redis writes).
  - REST poll uses a new httpx.AsyncClient per poll (no reuse).

  Optimizations

  - Pipeline Redis writes: batch hset/publish/lpush/expire (Lua or pipeline) per flush batch instead of per tick.
    Files: streamer/app/state.py, streamer/app/data_streamer.py
  - Reuse HTTP client: keep a long‑lived httpx.AsyncClient on StreamState or DataStreamer for REST poll + FX refresh.
    Files: streamer/app/data_streamer.py, streamer/app/state.py
  - Reduce Decimal work: precompute worsen_factor = 1 - worsen_percent once and use float for best_bid/ask and prices, then stringify once.
    Files: streamer/app/data_streamer.py
  - Throttle book depth parsing: optional skip deep orderbook parsing unless requested (guard with env).
    Files: streamer/app/data_streamer.py
  - Workers vs CPU: set UVICORN_WORKERS=1 if CPU limit stays 0.5.
    File: docker-compose.yml

  ———

  ### 2) reveal-market-worker (Ingestion + cache + proofs)

  Hotspots

  - Per‑market ORM/normalized writes; repeated queries for outcomes/tags/tokens/metadata on each page.
  - session.flush() on every page; commit batch size might be too small.
  - collect_market_changes_with_summary() does commit counts query every page.

  Optimizations

  - Bulk upserts: use insert().on_conflict_do_update() (SQLAlchemy Core) for outcomes/tags/tokens/gamma metadata to reduce ORM overhead.
    File: backend/worker/app/market_sync.py
  - Reduce flush/commit frequency: set RM_POLYMARKET_COMMIT_BATCH_SIZE higher (or add a max page count to flush).
    File: backend/worker/app/service.py
  - Batch commit counts: fetch commit counts once per tick (not per page) or per 10 pages; cache in memory.
    File: backend/worker/app/market_sync.py
  - Prefetch normalized state only when needed: you already check content_hash mismatch; could also skip gamma events if unchanged by hash.
    File: backend/worker/app/market_sync.py

  ———

  ### 3) reveal-market-api (FastAPI)

  Hotspots

  - Cache misses cause full enrich_market_models() and Python sorting for /markets and /categories.
  - hydrate_markets_cache() runs full enrichment + sorting; does multiple cache writes.

  Optimizations

  - DB‑side ordering: push order_by and coalesce_groups into SQL for volume and popularity when possible.
    Files: backend/api/app/routes/markets.py, backend/api/app/services/markets.py
  - Partial enrichment: enrich only after slicing to the final page size; avoid enriching unused models.
    File: backend/api/app/routes/markets.py
  - Cache list payload format: cache event_id list + lazy hydrate (already supported) more often; minimize full payload caching.
    File: backend/api/app/services/markets.py

  ———

  ### 4) reveal-market-relayer (FastAPI + queue)

  Hotspots

  - Queue uses SQLite/PG with a global thread lock and one worker; heavy lock contention + asyncio.to_thread() on every operation.
  - Each process_job is single‑threaded, sequential.

  Optimizations

  - Multi‑worker queue: allow multiple queue workers with SELECT … FOR UPDATE SKIP LOCKED (already supported in PG).
    File: relayer/src/relayer/queue.py
  - Reduce lock scope: use separate connection per operation; avoid global lock around PG path; lock only around SQLite.
    File: relayer/src/relayer/queue.py
  - Batch metrics updates: update QUEUE_DEPTH on a timer instead of on every job.
    File: relayer/src/relayer/queue.py

  ———

  ### 5) reveal-market-prover (Go Groth16)

  Hotspots

  - Disk I/O for witness/proof files; each request creates temp dir & writes JSON.
  - MaxConcurrency defaults to CPU count; but container CPU limit is 1.

  Optimizations

  - Use tmpfs: set PROVER_TEMP_DIR to a tmpfs mount for faster disk I/O.
    File: prover/main.go, docker-compose.yml (volume)
  - Tune concurrency: set PROVER_MAX_CONCURRENCY=1 for 1 CPU limit to avoid context switching.
    File: prover/internal/shared/config.go (env-driven)
  - Binary witness calc: use PROVER_WITNESS_BINARY to skip Node when possible.
    File: prover/groth16_prover.go

  ———

  ### 6) reveal-market-redis (cache)

  Hotspots

  - Memory at 64% of max; eviction policy volatile-lru only evicts TTL keys.
  - Streamer history keys may not have TTL if config says 0.

  Optimizations

  - Ensure TTL on all cache keys (especially history + latest ticks); or switch to allkeys-lru.
    File: docker/redis/redis.conf, streamer/app/state.py, backend/shared/cache_async.py
  - Reduce payload size: store compact JSON fields instead of full string mapping.
    File: streamer/app/state.py

  ———

  ### 7) reveal-market-postgres

  Hotspots

  - No obvious code shown, but worker reads/writes a lot of normalized tables; API has filters + sorts.

  Optimizations

  - Indexing: ensure indexes on market(event_id, status, category, updated_at, volume_24h_usd) and normalized tables by market_id.
    Files: backend/migrations/* (not reviewed yet)
  - Connection pools: API + worker pool sizes are small (5 + overflow 10). If you see pool waits, bump.
    Files: backend/api/app/config.py, backend/worker/app/database.py

  ———
