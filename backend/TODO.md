# Backend Growth TODOs

Every enhancement below ties directly to investor confidence, liquidity depth, or partner readiness. Prioritize work that amplifies these signals.

## Pillar 1 – Data Assurance & Transparency (High Priority)

- **AI summary ledger + provenance**
  Persist every AI-generated market summary together with model name, prompt hash, retrieval context pointers, and refresh cadence. Expose this history via `/markets/{event}` so diligence teams can audit how narratives evolved and verify that updates happened within SLA.

- **Request-scoped performance logging**
  Augment API + worker logs with per-endpoint latency buckets, bytes sent, and cache status. Structured timing data (INFO for slow requests, DEBUG for full traces) helps SREs prove SLAs and quickly detect regressions.

- **Worker-led schema enforcement**
  Allow the worker to verify/run Alembic migrations at startup so single-service deployments cannot drift. Investors gain assurance that reported metrics always reflect the latest schema. ✅ (baseline implemented; extend to cover summary tables + future services.)

- **Granular cache invalidation**
  Replace blanket Redis flushes with tag-based or versioned caches. Stable SLAs on `/markets` boost trust from exchanges evaluating latency guarantees.

- **Persistent resolution ledger**
  Continuously hydrate on-chain payout vectors (block number, tx hash, oracle proof hash) into Postgres and Redis. This unlocks immutable audit trails for diligence teams.

- **Resolution automation loop**
  Extend the worker to trigger settlement transactions (or queue them) once `payoutsAreSet` is detected. Include retries, duplicate suppression, and escalation logging so partners see proactive ops.

- **Decompose worker persistence loop**
  `_apply_resolution`, `cleanup_resolved_markets`, and `process_once` in `backend/worker/app/main.py` are sprawling routines (Ruff currently flags them for C901). Break them into focused units (e.g., batch fetch, cache invalidation, retention) so we can add targeted tests and recovery logic without risking regressions.

- **On-chain event mirroring**
  Stream `MarketCreated`, `RakeConfigured`, and guardian events into the shared database to keep rake economics and addresses perfectly aligned between API and contracts.

- **Horizen ZEN testnet switch**
  Ship configuration + tooling so regulated partners can trial the stack on the ZEN testnet before moving capital, reducing onboarding friction.

- **LLM retraining hooks**
  Capture failed/low‑confidence AI summary attempts (empty descriptions, repeated fallbacks, low word counts) and feed them into a feedback queue so NLP engineers can retrain prompts/models without digging through logs. Investors expect explainability around AI‑modified content.

- **Service heartbeats / liveness dashboards**
  Heartbeat logs exist; wire them into a unified dashboard (e.g., Redis-backed status widget + `/health/details`) showing last heartbeat, loop duration, cache hit rate, and outstanding summary jobs so ops teams can spot drift instantly.

## Pillar 2 – Liquidity Automation & Revenue Capture (Medium Priority)

- **Polymarket ingestion resilience**
  Centralize retries, backoff, and metrics for all upstream calls. Visibility into timeout/error counters is critical for LPs modeling data freshness.

- **Secrets + signer hardening**
  Move `RM_WALLET_PRIVATE_KEY` to a pluggable signer (Vault, KMS, etc.). Institutional partners insist on auditable key custody before enabling auto-market creation.

- **Config hot-reload**
  Introduce a safe mechanism (SIGHUP/admin endpoint) to adjust poll intervals, cache TTLs, and rake defaults without downtime. Enables rapid tuning during liquidity campaigns.

- **Backoff-aware Polymarket client**
  `PolymarketClient.fetch_markets` (backend/worker/app/polymarket.py) still issues plain HTTP requests without jitter, retries, or circuit-breaking. Wrap it with tenacity (already a dependency) and emit structured metrics so we can quantify upstream failures before they cause empty `/markets` responses.

- **Summary enrichment sidecar scaling**
  Provide a reference deployment (Celery/Queue, autoscaling rules) for the AI summary worker so heavy news cycles don’t backlog jobs. Include dead-letter metrics, alerting hooks, and the ability to reprocess stale queues via CLI.

- **Environment-aware cache namespaces**
  Allow multi-environment Redis sharing by prefixing keys, preventing cross-talk when staging and production run simultaneously for partner demos.

- **API request governance**
  Add rate limiting/throttling guards to preserve performance as marketing funnels drive more investor traffic toward the metrics endpoints.

- **Custom rake + fee analytics**
  Extend `/markets/stats` with rake scatter plots (min/max/avg per category) and optional timeline snapshots so BD teams can quantify fee exposure when negotiating liquidity partnerships.

- **Historical market snapshots**
  Store daily aggregates (open interest, price ranges, status transitions) for each market. This unlocks cohort analysis for LPs and gives the frontend the ability to show historical depth charts without recomputing from raw data.

## Pillar 3 – Institutional Readiness & Insight (Supporting)

- **Integration-grade testing**
  Spin up pytest-docker suites that boot Postgres + Redis to exercise migrations, cache flows, and worker loops end-to-end—evidence we can meet enterprise QA bars.

- **Structured tracing**
  Emit OpenTelemetry spans linking API requests, Redis hits, and worker batches. This supports external observability platforms used by exchanges and compliance desks.

- **Operational playbooks**
  Document log signatures (`worker.fetch.empty`, `heartbeat.stale`) and recommended responses. Investors value teams with clear incident processes.

- **Autoscaling hooks**
  Provide reference scripts/metrics for scaling workers/API containers when poll lag or queue depth increases, ensuring liquidity programs aren’t capped by infrastructure.

- **Rake visibility in responses**
  Surface `appliedRakeBps`, guardian state, and settlement metadata on every `/markets` payload so capital allocators can instantly calculate expected yield.

- **Compliance-grade audit exports**
  Bundle CLI/scripts that generate tamper-evident JSON/CSV exports (markets, resolutions, AI summaries, cache hit ratios) with signatures so regulated partners can archive the state of the system at any time.

- **End-to-end chaos drills**
  Document and automate simulated outages (Polymarket down, Redis down, OpenAI throttled) to prove recovery procedures. Include synthetic alerts and runbooks for each scenario so teams can practice the exact playbooks investors will expect.

Focus execution on Pillar 1 items first—they are the clearest signal to potential investors that Reveal Market operates with the discipline of a regulated venue.
