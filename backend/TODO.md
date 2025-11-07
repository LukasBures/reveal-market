# Backend Growth TODOs

Every enhancement below ties directly to investor confidence, liquidity depth, or partner readiness. Prioritize work that amplifies these signals.

## Pillar 1 – Data Assurance & Transparency (High Priority)

- **Worker-led schema enforcement**  
  Allow the worker to verify/run Alembic migrations at startup so single-service deployments cannot drift. Investors gain assurance that reported metrics always reflect the latest schema.

- **Granular cache invalidation**  
  Replace blanket Redis flushes with tag-based or versioned caches. Stable SLAs on `/markets` boost trust from exchanges evaluating latency guarantees.

- **Persistent resolution ledger**  
  Continuously hydrate on-chain payout vectors (block number, tx hash, oracle proof hash) into Postgres and Redis. This unlocks immutable audit trails for diligence teams.

- **Resolution automation loop**  
  Extend the worker to trigger settlement transactions (or queue them) once `payoutsAreSet` is detected. Include retries, duplicate suppression, and escalation logging so partners see proactive ops.

- **On-chain event mirroring**  
  Stream `MarketCreated`, `RakeConfigured`, and guardian events into the shared database to keep rake economics and addresses perfectly aligned between API and contracts.

- **Horizen ZEN testnet switch**  
  Ship configuration + tooling so regulated partners can trial the stack on the ZEN testnet before moving capital, reducing onboarding friction.

## Pillar 2 – Liquidity Automation & Revenue Capture (Medium Priority)

- **Polymarket ingestion resilience**  
  Centralize retries, backoff, and metrics for all upstream calls. Visibility into timeout/error counters is critical for LPs modeling data freshness.

- **Secrets + signer hardening**  
  Move `RM_WALLET_PRIVATE_KEY` to a pluggable signer (Vault, KMS, etc.). Institutional partners insist on auditable key custody before enabling auto-market creation.

- **Config hot-reload**  
  Introduce a safe mechanism (SIGHUP/admin endpoint) to adjust poll intervals, cache TTLs, and rake defaults without downtime. Enables rapid tuning during liquidity campaigns.

- **Environment-aware cache namespaces**  
  Allow multi-environment Redis sharing by prefixing keys, preventing cross-talk when staging and production run simultaneously for partner demos.

- **API request governance**  
  Add rate limiting/throttling guards to preserve performance as marketing funnels drive more investor traffic toward the metrics endpoints.

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

Focus execution on Pillar 1 items first—they are the clearest signal to potential investors that Reveal Market operates with the discipline of a regulated venue. 
