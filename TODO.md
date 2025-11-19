# Reveal Market Backlog Snapshot

Use this doc as the index for outstanding cross-team work. Each area has a dedicated `TODO.md`; the bullets below highlight the current top priorities so planning conversations start in the right place.

## Snapshot priorities (Nov 2025)
- **Backend** – Ship an auditable AI summary ledger, persist on-chain resolution data inside Postgres/Redis, and expand automation/analytics so `/markets` responses always come with provenance, rake history, and SLA-backed telemetry.
- **Contracts** – Finish the Groth16 production rollout (keys + rotation tooling), add replay-proof observability, and harden governance via deployment artifacts, invariants/fuzzing, and rehearsed ownership/guardian transfers before broader exchange integrations.
- **Frontend** – Replace placeholder data (charts/search), add diligence-ready proofs/filters, refresh trust messaging, and introduce investor-facing metrics hubs plus responsive docs navigation so stakeholders see polished, real data everywhere.
- **Proover** – Profile rapidsnark, expose Prometheus metrics, add artifact validation + setup ergonomics, and document the roadmap for embedding/upgrading the proving backend to keep zk claims credible.

Refer to the service-specific TODO files for deep context and acceptance criteria.

## Backend gaps

- Data-assurance features—AI summary provenance, persistent resolution ledgers, and on-chain mirroring—are still missing, so `/markets` cannot yet prove narrative lineage or settlement metadata in audits.
- Liquidity automation work (summary worker scaling, API governance, richer rake analytics) is outstanding; these features tie directly to deal velocity.

See `backend/TODO.md` for full scope and sequencing.

## Contracts gaps

- Groth16 verifier work is incomplete: production keys, rotation tooling, and proof replay persistence remain undone, preventing end-to-end zk audits.
- Deployment/ops tooling (consuming `last-deployment.json`, invariants/fuzz gates, guardian transfer drills) is still required to make governance credible.
- Treasury mechanics (validated rake overrides, flexible routing, metadata lifecycle definitions, guardian operating models) and expansion-readiness (Horizen ZEN testnet, verifier registry, gas regression gates, cross-chain alignment) have yet to begin.

See `contracts/TODO.md` for the detailed roadmap.

## Frontend gaps

- Immediate polish—live market charts, full search experience, responsive docs nav, proof filters/exports, trust banners, and accessibility sweeps—hasn’t landed.
- Narrative/credibility systems (hero refresh, segmented messaging, KPI proof points, testimonials, reorganized docs, metrics hub, lead forms, case studies, localized trust badges) remain in flight.
- Partnership workflows (due-diligence vault, live ops status, roadmap calendar, performance hardening) and engineering foundations (dynamic imports, scalable proof pagination, structured logging, cache-aware fetch helpers) are still queued.

See `frontend/TODO.md` for prioritization.

## Proover gaps

- Performance profiling, concurrency tuning, and potential rapidsnark pooling are unbuilt, so we lack latency guarantees.
- Observability needs Prometheus exports and rolling latency/concurrency metrics, alongside artifact validation helpers and non-root/hardening documentation.
- Ergonomics (sample envs, input validation) and the longer-term roadmap (cgo embedding, upgrade procedures) remain outstanding.

See `proover/TODO.md` for specifics.

---

## Redis cache guardrails

1. **Limit what you cache**
    - Reduce limit on cached endpoints (e.g. cache only the latest 20 markets per key). For deeper pagination, skip caching entirely or shorten TTL to a few seconds.
    - Avoid caching search results with unique queries. Set a minimum length and maybe don’t tag/filter them so they won’t reappear.
2. **Trim payloads before caching**
    - In the API, build a “cache-safe” version of each market: drop extra_data.gamma, events, clobSnapshots, etc., keeping only fields the frontend reads. You can still return the full payload from Postgres, but cache the slimmed copy. That alone cuts size by ~90%.
3. **Shorter TTLs / no priming**
    - Keep RM_MARKETS_CACHE_TTL_SECONDS low (30 s is fine) and consider disabling RM_PRIME_MARKETS_CACHE_ENABLED so the worker isn’t eagerly generating keys you never read. Let demand drive caching.
4. **Cap total keys**
    - Use Redis keyspace notifications/metrics to watch how many markets:list:* keys exist. If it explodes, clamp offsets or implement a simple LRU: before writing, delete random old keys (or use Redis maxmemory-policy allkeys-lru with maxmemory 3gb so Redis handles it).
5. **Clean other structures**
    - Ensure summary workers are running so the queues drain.
    - If you don’t use proofs, leave RM_PROVER_ENABLED=false so the worker never writes proofs:receipt:*.
      - Periodically purge old schema tags or set a TTL when writing them.

  With trimmed payloads (~20 KB per market) and a handful of cached cohorts (say 10 keys), Redis would sit well under 500 MB. Even if you keep 100 keys you’d still be <2 GB. The key is to stop storing the giant Gamma blobs and avoid caching every permutation. Use redis-cli INFO memory and SCAN markets:list:*
  to verify improvements as you tune.




• Current Integration Snapshot

  - The worker only calls GET /markets via PolymarketClient.fetch_markets, with params limit, offset, order, ascending, and closed. We default to order=id, ascending=false, closed filter from RM_POLYMARKET_CLOSED_FILTER. Requests are retried with Tenacity, pooled through a single httpx client, and each page
    is normalized into MarketPayload.
  - We don’t hit any of the other Gamma endpoints (tags, events, series, comments, public-search). All category/tag metadata is derived from the market payload itself.
  - Health checks hit /markets with limit=1 to verify reachability. No explicit network or active flags are passed.
  - Pagination is the standard offset/limit loop; we stop when a page returns less than the page size or a configured max_pages is reached.
  - Rate limiting is handled implicitly via backoff/retry; we don’t throttle proactively but the default poll interval (60 s) and page size (100) keep us well under Gamma’s 125 req / 10s for /markets.

  Gaps vs. Gamma Best Practices

  1. Network / Polygon filtering
     Gamma collapsed networks behind /markets, but they still support filters (e.g., categories_labels, tag_id, or even the network query param you tested earlier). Since you only ingest Polygon, passing network=137 (or the appropriate filter once Polymarket documents it) would reduce noise and detect
     misconfigured upstreams sooner.
  2. Active/archived filters
     Gamma recommends combining closed=false with active=true & archived=false to avoid dormant listings. We currently set closed, but not active/archived, so the worker still sees suspended markets that happen to be closed=false. Add those flags to cut db churn.
  3. Ordering by update time
     order=id correlates with creation order but isn’t guaranteed when Polymarket backfills. Gamma exposes order=createdAt or order=updatedAt; switching to order=updatedAt keeps the newest changes at the top and reduces reliance on skipping duplicates via hashes.
  4. Tag / category fetches
     Instead of deriving tags from each market payload, you can use /tags or /tags/slug/{slug} for curated relationships. That’s optional, but if you ever need Polymarket’s canonical tag definitions (color/icon, related tags), pulling that once and mapping events locally is more accurate than mining partial
     metadata from each market.
  5. Robust pagination
     The client stops when a page returns < page_size or max_pages hits. If Gamma temporarily returns empty lists mid-stream (known behavior), you’ll stop early. Consider checking meta.total (if provided) or continuing until offset >= reported total. Alternatively, detect an empty page but retry a limited
     number of times before concluding sync.
  6. Rate limiting telemetry
     Gamma’s /markets limit (125 req/10s) allows ~12.5 requests/sec. With limit=100 and limitless loops you won’t hit it, but adding a simple sliding window (sleep if >100 requests in the last 8s) plus logging rate-limit responses would make the integration more production-proof.
  7. Health + failover
     Current health uses /markets?limit=1. Gamma recommends hitting / or /health (if they expose it) for lighter checks. Also consider failing over to a cached snapshot (skip sync for this loop) if Gamma returns 5xx, instead of raising immediately.
  8. Retry budgets
     Tenacity handles per-request retries; the outer _run_with_retries also retries whole syncs. Make sure RM_POLYMARKET_SYNC_MAX_ATTEMPTS × RM_POLYMARKET_MAX_RETRIES stays low enough not to blow the 10-second rate window. With defaults (3 attempts × 3 retries) you’re fine, but document it.
  9. Missing endpoints
     If you ever need richer context (events or sports metadata), use /events?closed=false&limit=50 with nested markets so you’re aligned with Polymarket’s recommended workflow. Right now that’s not necessary, but the doc explicitly suggests it for active listings.

  Actionable tweaks

  - Update PolymarketClient.fetch_markets to accept extra filters: active, archived, network.
  - Default order to updatedAt (descending) so new/changed markets bubble up.
  - Add a “network” check in health and warn if the base URL is missing the network param (like we did for /markets/markets).
  - Optionally add a simple rate limiter or monitor Gamma’s x-ratelimit- headers to ensure we’re under quotas.
  - If you plan to surface tags in the UI again, fetch them from /tags once per sync instead of inferring them piecemeal.

  Your core integration (httpx client, retries, schema-normalizing MarketPayload) is solid. The above adjustments bring it closer to the “best practice” recommendations in Polymarket’s doc and help keep the dataset strictly Polygon + newest updates.







• What Lives In Redis

  - markets:list:* – every /markets response (homepage, search, pagination). Each key holds the full serialized array of markets for a specific combination of status/category/oracle/search/limit/offset. Payload includes extra_data.gamma, so each entry can be hundreds of kilobytes.
  - markets:category:* – cached /categories/{slug} results, same payload shape as above.
  - markets:suggest:* – cached /markets/suggest responses (lighter, just market summaries).
  - markets:resolution:* – per-condition resolution snapshots the worker writes after checking Goldsky/CTF. TTL matches RM_MARKETS_CACHE_TTL_SECONDS.
  - proofs:receipt:* – only when RM_PROVER_ENABLED=true, stores Groth16 receipts so the API can serve /proofs.
  - Schema and heartbeat keys – reveal_market_worker:heartbeat, reveal_market_worker:batch_stats, reveal_market:schema_version, plus invalidation tag sets (cache:tag:*) the worker uses to delete cached pages.
  - Queues – AI summary job queue/dead-letter (Redis lists), batch stats, rate-limit counters if enabled.

  How To Avoid Duplicate Keys And Reuse Cache Entries

  1. Normalize cache keys – We already slugify category/tag filters before building cache keys. Extend this to search queries (trim/lower/limit length) so “ Biden ” and “biden” hit the same markets:list:* key.
  2. Deduplicate payloads – Instead of caching entire market objects per key, cache normalized market records separately (e.g., market:evt-123 → sanitized JSON) and have list caches store only event IDs. Lists become tiny, and multiple views reuse the same per-market entry. When the worker updates a market,
     it writes the market:* record once and invalidates all list keys referencing that ID.
  3. Cap filter permutations – Only cache predictable cohorts: homepage (status=live, limit=18), per-category (limit 18), and the top few search queries you care about. Skip caching arbitrary search/offset combos, or use a fixed LRU bucket and drop oldest keys when exceeding N entries (Redis maxmemory-policy
     allkeys-lru helps).
  4. Avoid redundant priming – When RM_PRIME_MARKETS_CACHE_ENABLED runs, ensure it doesn’t duplicate what the API already cached (e.g., same limit/offset). Use tagged invalidation so the API reuses the worker-warmed keys.
  5. Trim payloads before caching – Remove extra_data.gamma and other heavy fields if the frontend doesn’t need them directly. Store only the fields the UI actually renders (title, category, status, prices, image). This also reduces duplication because repeated metadata no longer bloats every list entry.

  Keeping Responses Fast While Hydrating From Postgres

  - DB as Source of Truth – The worker and API already share a Postgres schema. On startup (or after cache flush), you can preload hot keys by reading from Postgres: run a short script that queries the latest N markets and populates the market:* + markets:list:* caches. Or let the worker’s
    prime_markets_cache() run once at boot—it already fetches /markets from the API and writes the cache.
  - Atomic updates – Whenever the worker upserts a market:
      1. Write the row to Postgres (shared_repository.upsert_market).
      2. Update the market:<event_id> cache entry with the sanitized payload.
      3. Invalidate relevant list tags (markets:list, category:<slug>) so the next request repopulates them from Postgres instantly.
         No request waits on Gamma; cache misses fall back to DB, not the external API.
  - Periodic refresh – Leave the existing poll loop (default 60 s) to repopulate from Gamma. Between loops, the API serves data from Redis/Postgres. If Redis is empty (cold start), the first client request hits Postgres, caches the result, and subsequent requests are fast.
  - Search performance – /markets with search uses Postgres full-text index (markets_search_vector_idx). Keep that index healthy (alembic upgrade head) and limit caching to popular searches so random queries just rely on the DB, which is optimized for search. For consistent low latency:
      - Ensure Postgres has enough RAM and analyze/vacuum regularly.
      - Use LIMIT to keep responses small (e.g., 20 results) and cache only the normalized event IDs so repeated searches hit Redis quickly.
  - Predictable cache size – With per-market caching + trimmed payloads, you can estimate memory: (#markets × ~5 KB) plus a few list keys, comfortably <2 GB for thousands of markets. Monitor with redis-cli INFO memory and enforce a maxmemory (e.g., 3 GB) with volatile-lru so Redis discards the least-used
    TTL’d keys when nearing the cap.

  In short: store a single canonical copy of each market in Redis, have list caches point to those IDs, trim large blobs before caching, and keep Postgres as the authoritative store that repopulates caches on demand. That keeps responses instant (Redis hits for hot paths, indexed Postgres for cold paths)
  while making Redis memory consumption stable and predictable.
