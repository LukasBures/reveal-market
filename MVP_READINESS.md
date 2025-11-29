# MVP Readiness Runbook

This checklist closes the minimum gaps for a production-ready MVP. Use it before declaring “go” on any environment.

## 1) Test Matrix (must be green)
- Run `./scripts/mvp_check.sh` from repo root (backend tests → frontend lint/test/build → contracts full run → prover artifact verification when available).
- Frontend requires a reachable backend `/health` during tests/build; start the stack first or point to staging.

## 2) Monitoring & Alerts (minimum)
- Heartbeat staleness: alert if `RM_HEARTBEAT_KEY` older than `RM_HEARTBEAT_TTL_SECONDS`.
- Ingest errors: alert on `worker.fetch.error`/`worker.sync.skipped` spikes.
- Prover failures: alert on `worker.proof.failed` and HTTP 5xx from prover.
- Resolution gaps: alert on `worker.resolution.gaps` events.
- Cache priming: alert on `worker.cache.prime_failed` / `worker.cache.featured_failed`.
- Summary DLQ: alert on `worker.summary.dead_letter` count > 0.
- Dashboard: expose heartbeat metrics, ingest latency, cache invalidations, prover outcomes, summary DLQ depth, resolution gap counts.

## 3) Security Validation
- CORS/Allowed hosts/CSP match deployment domains (API + frontend).
- Rate limiting on public endpoints enabled (`RM_RATE_LIMIT_ENABLED=true` in prod-like envs).
- No secrets in logs; env secrets supplied via manager (no defaults in prod).
- TLS termination and redirects (HTTPS + HSTS) confirmed at the edge.

## 4) Proofs End-to-End
- Ingest real commitments/settlements into Postgres (commitment + settlement tables populated).
- Run worker with `RM_PROVER_ENABLED=true` and `RM_AUTO_SETTLEMENT_ENABLED=true`.
- Confirm proof receipts cached in Redis and settlement records carry proof metadata (request_id/hash/status).
- Verify prover health (`/healthz`) and sample proof generation succeeds with stored data.

## 5) Load / Chaos (smoke-level)
- Run a short load on worker ingest and API hot paths; watch DB/Redis pool utilization and error rates.
- Simulate Redis blips (restart or denylist) and confirm worker degrades gracefully (no crash).
- Simulate Polymarket fetch failures; confirm retries/backoff and heartbeat continue.

## 6) Deploy / Rollback
- Migrations reversible; keep `RM_RUN_MIGRATIONS_ON_STARTUP=true` but ensure Alembic downgrades exist.
- Prefer canary/blue-green deployment; validate health before promotion.
- Rollback plan: redeploy prior image/config; clear schema cache key if needed (`DEL RM_SCHEMA_VERSION_KEY`), invalidate `schema:*` tags.

## 7) Sign-off
- All tests green, alerts wired, security validated, proof path verified, load/chaos smoke passed, rollback rehearsed.
