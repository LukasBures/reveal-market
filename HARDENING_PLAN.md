# Reveal Market Local Stack Hardening Plan

Date: 2026-02-28  
Author: Codex (execution + analysis)

## 1. Goal

Harden local stack reliability and observability after running `make local`, then:

- validating service startup and health
- observing runtime behavior for ~10 minutes
- browsing key pages/endpoints
- analyzing logs for actionable stability issues

This document captures:

- exactly what was tried
- what worked and what did not
- root-cause analysis from observed evidence
- a concrete hardening plan with implementation order and verification criteria

---

## 2. Scope Executed

The following was executed in `/Users/lukas/PycharmProjects/RevealMarket/reveal-market`:

- `make local` (multiple attempts)
- Docker compose lifecycle checks and cleanup
- container health inspection and endpoint checks
- 10-minute periodic service-state observation (30s interval)
- multi-service logs analysis
- targeted deep-dive into hedger healthcheck behavior

No source code was changed during this analysis phase.

---

## 3. Chronological Execution Log

## 3.1 Attempt #1: `make local` (failed on stale Docker resources)

Command:

```bash
make local
```

Observed:

- `run_local.sh` started correctly.
- frontend env seeded from `.env.local` to `frontend/.env.local`.
- prover artifacts synchronized and validated.
- Docker compose config validation passed.
- image builds started and succeeded (mixed cache hits/misses as expected).
- startup (`docker compose up --wait`) failed due existing resources from prior runs:
  - network conflict: `reveal-market_default already exists`
  - container name conflict: `"/reveal-market-redis" is already in use`

What worked:

- build pipeline itself
- env/prover preflight
- compose config validation

What failed:

- deterministic startup when stale project resources already existed

Interpretation:

- `run_local.sh` currently assumes the project network/container namespace is clean enough for `up --remove-orphans`.
- it does not automatically recover from this specific class of stale resource collisions.

---

## 3.2 Cleanup between attempts

Command executed:

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml --env-file .env.local down --remove-orphans
```

Observed:

- conflicting containers removed (`reveal-market-redis`, `reveal-market-postgres`, `reveal-market-prover`, `reveal-market-relayer`)
- `reveal-market_default` network removed cleanly

What worked:

- cleanup restored a clean project namespace

---

## 3.3 Attempt #2: `make local` (failed `--wait` on hedger health)

Command:

```bash
make local
```

Observed:

- images rebuilt from cache (fast path)
- most services reached healthy
- `make local` exited non-zero because `reveal-market-hedger` became unhealthy

What worked:

- stack booted
- all core services started

What failed:

- strict `up --wait` gate due hedger healthcheck flapping/timeout

---

## 3.4 State and endpoint verification after startup

`docker compose ps` showed all services up; hedger health intermittently moved between healthy/unhealthy.

Key HTTP checks (`200` unless noted):

- `http://localhost:3000/` -> 200
- `http://localhost:3000/docs` -> 200
- `http://localhost:3000/robots.txt` -> 200
- `http://localhost:3000/sitemap.xml` -> 200
- `http://localhost:8000/healthz` -> 200
- `http://localhost:8000/live` -> 200
- `http://localhost:8100/healthz` -> 200
- `http://localhost:8088/healthz` -> 200
- `http://localhost:8090/healthz` -> 200
- `http://localhost:8085/healthz` -> 200
- `http://localhost:8000/healthz/heartbeats` -> 401 (`invalid_internal_secret`) (expected for unauthenticated call)

Additional route probes:

- `http://localhost:3000/markets` -> 404
- `http://localhost:3000/docs/whitepaper` -> 404
- `http://localhost:3000/api/markets/suggest?q=btc` -> 200

Interpretation:

- core app and infra endpoints are functional
- some routes are intentionally absent or moved (404s), not necessarily regressions

---

## 3.5 10-minute runtime observation (30-second ticks)

Sampling window:

- 20 ticks over ~10 minutes
- service state parsed from compose `ps --format json`

Findings from sampled summary:

- 9/20 ticks had non-ideal state:
  - `reveal-market-hedger: state=running, health=unhealthy`
- all other services remained `running+healthy`
- restart count remained zero for all containers

Interpretation:

- no crash loops
- hedger health signal is unstable relative to current healthcheck timeout budget

---

## 3.6 Deep-dive: hedger healthcheck behavior

Relevant config:

- `docker-compose.yml:285` uses:
  - `test: ["CMD", "python", "-m", "app.healthcheck"]`
  - `timeout: 5s`
- `hedger/app/healthcheck.py:10-14`:
  - loads settings
  - constructs DB repository
  - performs async DB connectivity check (`select 1`)

Measured command durations inside container:

```text
run_1: 12.61s
run_2: 10.38s
run_3:  6.47s
```

Health inspector evidence:

- repeated `"Health check exceeded timeout (5s)"`
- failing streak grew while service still responded to `/healthz`

What worked:

- process/app stayed up
- `/healthz` endpoint remained responsive

What failed:

- container healthcheck command regularly exceeded 5s timeout

Conclusion:

- current healthcheck command is too heavy for a 5s timeout in this local profile.
- this creates false-negative health status and causes `make local` failure under `--wait`.

---

## 3.7 Deep-dive: streamer log noise

Hotspot:

- `streamer/app/data_streamer.py:441-445` emits warning per invalid market payload:
  - event: `clob.rest.invalid_payload`

Measured volume:

- last 30 minutes: `invalid_payload` count = **1615**
- during 10-min monitor: warnings/errors heavily dominated by streamer invalid payload lines

Behavioral note:

- no crash/restart followed these warnings
- service still healthy and serving `/healthz`

Interpretation:

- warning severity and per-item emission create high-noise logs
- observability signal-to-noise is degraded

---

## 3.8 Goldsky schema drift warning (intermittent)

Observed earlier in session logs:

- `Type Query has no field conditionResolutions`

Relevant query source:

- `backend/shared/indexers/goldsky.py:24-40` (`conditionResolutions` query)

Interpretation:

- upstream schema compatibility issue or endpoint-version mismatch can degrade resolution backfill paths
- not continuously present in last 30-minute slice, but remains a resilience risk

---

## 4. What Worked vs What Did Not

## 4.1 Worked

- build stages completed and cache reuse was effective
- most services reached and maintained healthy state
- no container restart loops
- frontend/API/streamer/relayer/prover endpoints all reachable
- manual cleanup fully resolved stale resource conflicts

## 4.2 Did Not Work / Fragile

- `make local` is not robust against stale compose network/container name collisions
- hedger healthcheck command and timeout mismatch produces false unhealthy state
- streamer invalid-payload warnings flood logs and hide useful signals
- external schema drift (Goldsky) can produce warning bursts and potential feature degradation

---

## 5. Root Cause Analysis Summary

## RCA-1: Hedger health false negatives

Primary cause:

- expensive healthcheck command (`python -m app.healthcheck`) with strict timeout (`5s`)

Evidence:

- measured 6.47s-12.61s execution times
- repeated timeout messages in Docker health logs
- app still serving `/healthz` during unhealthy state

Severity:

- High for developer UX and CI/local reliability

## RCA-2: Local startup brittle to stale compose resources

Primary cause:

- startup path does not include conflict remediation/retry for known Docker resource collisions

Severity:

- Medium-High (frequent local friction)

## RCA-3: Streamer warning storm

Primary cause:

- invalid payload warning emitted per-record without aggregation/throttling or reason bucketing

Severity:

- Medium (operational visibility degradation)

## RCA-4: Goldsky query schema coupling

Primary cause:

- hard dependency on `conditionResolutions` field without robust fallback strategy

Severity:

- Medium (data freshness/correctness risk when upstream schema changes)

---

## 6. Hardening Plan (Proposed Implementation)

Priority labels:

- P0 = immediate reliability blocker
- P1 = operational hardening
- P2 = resilience and maintainability

## 6.1 P0 - Fix hedger healthcheck reliability

### Proposal P0-A (recommended)

Replace hedger Docker healthcheck with lightweight HTTP liveness probe:

- File: `docker-compose.yml:285`
- From:
  - `["CMD", "python", "-m", "app.healthcheck"]`
- To:
  - `["CMD-SHELL", "curl -fsS http://127.0.0.1:8090/healthz || exit 1"]`

Tune timings:

- timeout: `10s`
- start_period: `45s`
- interval/retries can remain as-is initially

Why:

- healthcheck should verify process availability quickly and cheaply
- DB deep-check belongs to readiness/deep-health route, not frequent Docker liveness

### Proposal P0-B (optional alternative if DB gate is required)

Keep Python healthcheck but tune for reality:

- timeout >= `15s`
- start_period >= `60s`

Tradeoff:

- slower failure detection, still expensive and noisy vs simple HTTP probe

Acceptance criteria:

- `make local` succeeds repeatedly (>= 5 consecutive runs from clean state)
- hedger health does not flap under idle conditions for 15 min

---

## 6.2 P0 - Harden `run_local.sh` against stale Docker resource conflicts

Target:

- `run_local.sh:485-496` (`compose up` invocation)

Add conflict-aware recovery:

1. Run `compose up` as today.
2. If output contains known conflict patterns:
   - `already exists`
   - `is already in use`
   then run:
   - `docker compose ... down --remove-orphans`
3. Retry `compose up` once.
4. If second failure, exit non-zero with clear remediation message.

Optional:

- add `--auto-clean` flag to control this behavior explicitly.

Acceptance criteria:

- stale network/container collisions no longer require manual intervention
- failure mode remains explicit and safe (max one automated retry)

---

## 6.3 P1 - Reduce streamer log noise while preserving metrics

Target:

- `streamer/app/data_streamer.py:94` (`_validate_rest_market`)
- `streamer/app/data_streamer.py:441-445` warning emission

Changes:

1. Make validator return `(is_valid, reason_code)` instead of bool only.
2. Aggregate invalid payload stats per poll cycle:
   - total invalid
   - counts per reason
   - optional one sample market id per reason
3. Emit one warning per poll cycle (or rate-limited warnings), not one per market.
4. Keep existing metric counters (`record_drop`, `record_ingest_drop`), optionally add reason labels.

Acceptance criteria:

- warning line count reduced by >90% under same market feed
- retained ability to diagnose payload quality via summary/reason metrics

---

## 6.4 P1 - Clarify local service profile expectations

Current observed behavior:

- hedger logs `missing_wallet` and runs read-only in local env (expected)

Proposal:

- explicitly document this in startup summary and local docs:
  - read-only mode expected when private key absent
  - which endpoints remain valid

Acceptance criteria:

- no ambiguity between expected read-only mode and true startup faults

---

## 6.5 P2 - Goldsky schema-resilient fallback

Target:

- `backend/shared/indexers/goldsky.py:24-40` and batch query path

Changes:

1. Detect GraphQL schema errors (`no field conditionResolutions`).
2. Fallback to alternate query strategy:
   - query `condition` only where possible
   - or feature-flag endpoint/version-specific query forms
3. Add explicit event type for schema mismatch and degrade gracefully.

Acceptance criteria:

- no repeated warning storm when schema field is missing
- resolution pipeline continues with best-effort fallback

---

## 6.6 P2 - Add one-command local smoke verification

Add script (example: `scripts/local_smoke.sh`) to verify:

- compose services healthy
- key endpoints return expected status codes
- optional warnings threshold checks

This becomes a post-`make local` fast confidence check.

Acceptance criteria:

- script exits 0 on healthy baseline
- script emits concise actionable failures

---

## 7. Proposed Delivery Sequence

1. **P0-A** hedger healthcheck simplification + timeout/start-period tuning  
2. **P0** run_local conflict auto-recovery  
3. **P1** streamer log aggregation/rate-limiting  
4. **P2** Goldsky fallback and schema mismatch handling  
5. **P2** local smoke checker script

Rationale:

- first two items eliminate immediate developer friction and false negatives
- next items improve operational visibility and external dependency resilience

---

## 8. Verification Plan After Hardening

Run from project root:

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml --env-file .env.local down --remove-orphans
make local
docker compose -f docker-compose.yml -f docker-compose.override.yml --env-file .env.local ps
```

Stability observation:

```bash
# 10-minute observation window
for i in $(seq 1 20); do
  docker compose -f docker-compose.yml -f docker-compose.override.yml --env-file .env.local ps --format json
  sleep 30
done
```

Expected after hardening:

- no manual cleanup required for stale resource conflicts
- hedger remains healthy (or at least does not flap due timeout false negatives)
- streamer warning volume materially reduced while metrics remain intact

---

## 9. Key Evidence References (Code/Config)

- Hedger compose healthcheck: `docker-compose.yml:285`
- Hedger healthcheck implementation: `hedger/app/healthcheck.py:10`
- Local startup `up` invocation: `run_local.sh:485`
- Streamer validation logic: `streamer/app/data_streamer.py:94`
- Streamer per-market warning emission: `streamer/app/data_streamer.py:441`
- Goldsky `conditionResolutions` query: `backend/shared/indexers/goldsky.py:24`

---

## 10. Final Assessment

The stack is broadly functional, but local reliability is currently constrained by:

1. overly strict/expensive hedger healthcheck configuration
2. lack of automatic stale-resource remediation in `make local`
3. high-noise streamer warning behavior

Addressing these in the proposed order should significantly improve:

- `make local` success rate
- confidence in health signals
- log usability for real issue detection
- resilience to upstream schema changes

