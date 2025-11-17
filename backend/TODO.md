# Backend Growth TODOs

Every enhancement below ties directly to investor confidence, liquidity depth, or partner readiness. Prioritize work that amplifies these signals.

## Pillar 1 – Data Assurance & Transparency (High Priority)

- **AI summary ledger + provenance**
  Persist every AI-generated market summary together with model name, prompt hash, retrieval context pointers, and refresh cadence. Expose this history via `/markets/{event}` so diligence teams can audit how narratives evolved and verify that updates happened within SLA.

- **Worker-led schema enforcement**
  Allow the worker to verify/run Alembic migrations at startup so single-service deployments cannot drift. Investors gain assurance that reported metrics always reflect the latest schema. ✅ (baseline implemented; extend to cover summary tables + future services.)

- **Persistent resolution ledger**
  Continuously hydrate on-chain payout vectors (block number, tx hash, oracle proof hash) into Postgres and Redis. This unlocks immutable audit trails for diligence teams.

- **Resolution automation loop**
  Extend the worker to trigger settlement transactions (or queue them) once `payoutsAreSet` is detected. Include retries, duplicate suppression, and escalation logging so partners see proactive ops.

- **On-chain event mirroring**
  Stream `MarketCreated`, `RakeConfigured`, and guardian events into the shared database to keep rake economics and addresses perfectly aligned between API and contracts.

- **Horizen ZEN testnet switch**
  Ship configuration + tooling so regulated partners can trial the stack on the ZEN testnet before moving capital, reducing onboarding friction.

- **LLM retraining hooks**
  Capture failed/low‑confidence AI summary attempts (empty descriptions, repeated fallbacks, low word counts) and feed them into a feedback queue so NLP engineers can retrain prompts/models without digging through logs. Investors expect explainability around AI‑modified content.

## Pillar 2 – Liquidity Automation & Revenue Capture (Medium Priority)

- **Service heartbeats / liveness dashboards**
  Expand the `/health/heartbeats` telemetry into user-facing dashboards (Docs or admin UI) and publish SLO thresholds so ops teams can spot drift instantly.

- **Granular cache invalidation / schema versioning**
  Now that worker invalidations run through tag reports, extend the same versioning to API cache helpers (e.g., schema revision bumps) so stale keys never bleed across deployments.

- **Summary enrichment sidecar scaling**
  Provide a reference deployment (Celery/Queue, autoscaling rules) for the AI summary worker so heavy news cycles don’t backlog jobs. Include dead-letter metrics, alerting hooks, and the ability to reprocess stale queues via CLI.


- **API request governance**
  Add rate limiting/throttling guards to preserve performance as marketing funnels drive more investor traffic toward the metrics endpoints.

- **Custom rake + fee analytics**
  Extend `/markets/stats` with rake scatter plots (min/max/avg per category) and optional timeline snapshots so BD teams can quantify fee exposure when negotiating liquidity partnerships.

- **Historical market snapshots**
  Store daily aggregates (open interest, price ranges, status transitions) for each market. This unlocks cohort analysis for LPs and gives the frontend the ability to show historical depth charts without recomputing from raw data.

Focus execution on Pillar 1 items first—they are the clearest signal to potential investors that Reveal Market operates with the discipline of a regulated venue.
