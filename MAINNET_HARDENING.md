# Mainnet Hardening Checklist

Date: 2026-03-07
Status: In progress

This document tracks all 13 identified gaps before mainnet production launch.
Each item includes: current code state, exact risk, what to build, and acceptance criteria.

---

## Implementation Plan

| Phase | Items | Status |
|-------|-------|--------|
| **Now** | 2, 3, 4, 6, 7, 8, 9, 10, 11 | Pending |
| **Deferred** | 1, 5, 12, 13 | Before significant TVL |

---

## Item 1 — Relayer private key in env var

**Status:** Deferred (before significant TVL)

### Current state

`relayer/src/relayer/main.py:32`:
```python
account = web3.eth.account.from_key(cfg.relayer_private_key)
```

`relayer/src/relayer/config.py:188`:
```python
relayer_private_key=_require_env("RELAYER_PRIVATE_KEY"),
```

Same pattern applies to:
- `RM_SETTLEMENT_SIGNER_PRIVATE_KEY` (worker — signs `verifyAndSettleBatched` transactions)
- `RM_PRICING_SIGNER_PRIVATE_KEY` (API — signs quote digests)

### Risk

- `docker inspect <container>` dumps all environment variables to anyone with Docker socket access (effectively root-equivalent on the host).
- Any unhandled exception that prints locals, any debug endpoint reflecting config, any accidental `model_dump()` without redaction, any `ps aux` with env visible — all leak the key.
- Server compromise = key is immediately available, no additional steps required.

### What to build

**Minimum for mainnet:** Switch to file-based secrets (Docker secrets mounted as files).

1. Change `_require_env("RELAYER_PRIVATE_KEY")` to read from `RELAYER_PRIVATE_KEY_FILE` path:
   ```python
   def _read_secret(env_var: str) -> str:
       path = os.environ.get(f"{env_var}_FILE")
       if path:
           return Path(path).read_text().strip()
       return _require_env(env_var)
   ```
2. Mount secret in `docker-compose.yml` via Docker secrets or bind mount with `0400` permissions.
3. Same change for `RM_SETTLEMENT_SIGNER_PRIVATE_KEY` and `RM_PRICING_SIGNER_PRIVATE_KEY`.

**Longer term:** AWS KMS / GCP Cloud HSM — application sends digest, receives signature; raw key never leaves HSM.

### Acceptance criteria

- `docker inspect reveal-market-relayer` shows no `RELAYER_PRIVATE_KEY` in environment.
- Key file is owned by the service user, mode `0400`, not readable by other containers.

---

## Item 2 — Relayer webhook secret is optional

**Status:** Pending

### Current state

`backend/api/app/routes/trade.py:2701`:
```python
if settings.relayer_webhook_secret:
    if not hmac.compare_digest(secret_header or "", settings.relayer_webhook_secret):
        raise HTTPException(status_code=403)
```

`backend/api/app/config.py:251`:
```python
relayer_webhook_secret: str | None = Field(default=None, ...)
```

If `RM_RELAYER_WEBHOOK_SECRET` is not set, the outer `if` is falsy and the HMAC check is skipped entirely — any caller can POST to the webhook endpoint.

### Risk

The relayer webhook is how the relayer notifies the API that a transaction succeeded or failed. An unauthenticated attacker who can reach the API endpoint can POST fabricated settlement confirmations, causing the backend to mark commitments as claimed or settled without the actual on-chain transaction having occurred.

### What to build

Add `relayer_webhook_secret` to `backend/api/app/services/startup_validation.py` alongside `RM_INTERNAL_API_SECRET`:

```python
if not settings.relayer_webhook_secret:
    missing.append("RM_RELAYER_WEBHOOK_SECRET")
```

Ensure it is guarded by `RM_ENVIRONMENT=prod` check, same pattern as existing validations.

### Acceptance criteria

- API startup fails with a clear error when `RM_RELAYER_WEBHOOK_SECRET` is absent in prod.
- A POST to the webhook endpoint with a wrong or missing secret returns 403.
- Existing tests updated to supply the secret in test settings.

---

## Item 3 — Rate limiting off by default

**Status:** Pending

### Current state

`backend/api/app/config.py:150`:
```python
rate_limit_enabled: bool = Field(
    default_factory=lambda: bool(PRESET.get("rate_limit_enabled", False))
)
```

The default falls back to `False` unless the preset explicitly sets it. The prod preset does not guarantee `True`. The `RM_RATE_LIMIT_ENABLED` env var must be explicitly set, but it is not enforced at startup.

`backend/api/app/rate_limit.py:184`:
```python
if not self.settings.rate_limit_enabled:
    return  # silently skips all limiting
```

### Risk

- `/pricing/quote` generates a signed quote valid for N seconds. Unlimited calls allow systematic study of the pricing model and exploitation of pricing lag between FX updates.
- `/trade/commit` without rate limiting allows commit spam — fills the proof queue, exhausts relayer gas balance, forces legitimate users into the dead-letter queue.
- The prover (Groth16) is CPU-bound and cannot generate proofs faster than the hardware allows. A flood faster than proof generation rate backs up the queue indefinitely.

### What to build

1. Change the prod preset to set `rate_limit_enabled: true` by default.
2. Add to `startup_validation.py`: warn (or fail) if `rate_limit_enabled` is `False` in prod.
3. Ensure `rate_limit_trusted_proxies` is configured to include Caddy's internal container IP so `X-Forwarded-For` is trusted for per-IP rate limiting.

`backend/api/app/services/startup_validation.py` addition:
```python
if not settings.rate_limit_enabled:
    warnings.append("RM_RATE_LIMIT_ENABLED is False in production — commit/quote endpoints are unprotected")
```

### Acceptance criteria

- `RM_ENVIRONMENT=prod` without explicit `RM_RATE_LIMIT_ENABLED=true` logs a startup warning.
- Exceeding the rate limit returns 429 with a `Retry-After` header.
- Requests behind Caddy are rate-limited per real client IP, not per proxy IP.

---

## Item 4 — Redis no persistence and nonce dedup bypass

**Status:** Pending

Two distinct problems that compound each other.

### Current state

**Problem A — No persistence:**

`docker/redis/redis.conf:1-3`:
```
save ""
stop-writes-on-bgsave-error no
appendonly no
```

Redis is purely in-memory. Everything disappears on restart: rate limit buckets, worker heartbeats, Redis-backed relayer job queues, `lock_batches` lease token, proof queue locks, commit nonce dedup keys.

**Problem B — Nonce dedup silently bypasses on Redis failure:**

`backend/api/app/routes/trade.py:993-997`:
```python
except RedisError:
    logger.warning(
        event="trade.commit.nonce_cache_unavailable",
        message="redis unavailable; commit nonce dedup skipped",
        nonce=nonce,
    )
    return  # continues without dedup
```

When Redis is down or just restarted, nonce deduplication is silently skipped. The on-chain contract rejects true duplicates at the Solidity level, but the API will accept and queue duplicates, wasting relayer gas and creating noise in the settlement queue.

### Risk

- After any Redis restart, rate limit buckets reset (abuse window opens), nonce dedup is bypassed (replay window opens), and worker heartbeat state is lost.
- Redis restarts on a healthy system are rare but not impossible: OOM kill, Docker container restart, host reboot, deploy cycle.

### What to build

**A — Enable AOF persistence in `docker/redis/redis.conf`:**
```
appendonly yes
appendfsync everysec
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 64mb
```
AOF with `everysec` means at most 1 second of data loss on crash with minimal performance overhead.

**B — Change nonce bypass to return 503 instead of silently continuing:**

`backend/api/app/routes/trade.py` — change the `except RedisError` block in `_record_commit_nonce`:
```python
except RedisError:
    logger.error(
        event="trade.commit.nonce_cache_unavailable",
        message="redis unavailable; rejecting commit to prevent nonce replay window",
        nonce=nonce,
    )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="cache_unavailable_retry",
    )
```

### Acceptance criteria

- After `docker compose restart redis`, nonce dedup keys from before the restart survive (AOF replay).
- A commit attempt while Redis is down returns 503, not 200.
- `appendonly yes` confirmed in running Redis via `redis-cli CONFIG GET appendonly`.

---

## Item 5 — Contracts not on multisig

**Status:** Deferred (before significant TVL)

### Current state

`MarketFactory`, `RelayerEscrow`, `ProtocolPool`, and the `Ownable2Step` upgrade paths are owned by the single deployer EOA that ran `forge script`. No multisig is in place.

### Risk

One compromised key (phishing, laptop theft, clipboard hijack) allows an attacker to:
- Change the oracle address → markets never resolve.
- Change the authorization signer → all new commits fail signature verification.
- Change the circuit hash → settlement breaks for every active market.
- Update `globalRakeBps` to 100% → steal all user stakes.
- Drain `ProtocolPool` rake balances.
- Pause all markets indefinitely.

None of these require exploiting a smart contract bug — only the deployer key.

### What to build

1. Deploy a Gnosis Safe with 2-of-3 threshold (deployer + second trusted party + hardware wallet).
2. Write ownership transfer scripts using Foundry:
   ```solidity
   // script/TransferOwnership.s.sol
   factory.transferOwnership(safeAddress);     // proposes
   relayerEscrow.transferOwnership(safeAddress);
   protocolPool.transferOwnership(safeAddress);
   // Then: Safe must call acceptOwnership() on each contract
   ```
3. Test the full transfer + accept flow on testnet before mainnet.
4. Store the Safe address in `CLAUDE.md` and deployment docs.

### Acceptance criteria

- `factory.owner()` returns the Gnosis Safe address on mainnet.
- Any admin action (oracle change, signer rotation, rake update) requires 2-of-3 Safe signatures.
- Transfer + accept scripts are tested and committed to `contracts/zen/script/`.

---

## Item 6 — No database backup strategy

**Status:** Done

### Current state

No `pg_dump`, no WAL archiving, no managed backup configuration anywhere in the project. The Postgres volume is a named Docker volume (`postgres_data`) with no snapshot or export mechanism.

### Risk

The database holds: commitments (user salts and leaf indices), settlement receipts (required for claims), quote ledger (audit trail), all market state ingested from Polymarket. Without this data, even if the contracts are intact on-chain, the off-chain system cannot reconstruct which proofs to generate for settlement.

A disk failure, accidental `docker compose down -v`, or corrupted volume = total data loss with no recovery path.

### What was built

**Daily pg_dump to local disk on the production server** (no external storage dependency):

- `scripts/backup_db_local.sh` — runs on the server via cron at 02:00 UTC, dumps the DB to `/var/backups/reveal-market/`, retains 14 days.
- `prod_db_backups/pull_backup.sh` — local script to pull the latest (or a specific) backup from the server via rsync.
- Restore runbook updated at `docs/runbooks/db-restore.md`.

**Server setup (one-time, after deploy):**
```bash
# Create backup directory on server
ssh reveal-market-prod "sudo mkdir -p /var/backups/reveal-market && sudo chown reveal:reveal /var/backups/reveal-market"

# Deploy backup script
scp scripts/backup_db_local.sh reveal-market-prod:/opt/reveal-market/scripts/backup_db.sh
ssh reveal-market-prod "chmod +x /opt/reveal-market/scripts/backup_db.sh"

# Install cron job (as reveal user)
ssh reveal-market-prod "crontab -l 2>/dev/null | { cat; echo '0 2 * * * /opt/reveal-market/scripts/backup_db.sh >> /var/log/db-backup.log 2>&1'; } | crontab -"
```

**Longer term:** Enable Postgres WAL archiving for point-in-time recovery, or add a second offsite copy via rsync to a separate machine.

### Acceptance criteria

- Daily backup script runs on prod server via cron. ✓
- Restore procedure has been tested end-to-end at least once before mainnet.
- Backups are retained for 14 days minimum. ✓
- A Discord alert fires (via Alertmanager or directly) if the backup cron does not produce a new file within 26 hours.

---

## Item 7 — No alert for unresolved markets post-deadline

**Status:** Pending

### Current state

Settlement is wired: `backend/worker/app/settlement.py:636` implements `_submit_verify_and_settle_batched` which calls `contract.functions.verifyAndSettleBatched(...)` directly. The worker runs `run_settlement_jobs` on its loop (`service.py:1704`) and spawns `run_settlement_queue_worker` as a background task (`service.py:2307`).

However, there is no alert or monitoring for the end-state gap: a market that has `resolved=True` on-chain but has no `settlement_tx_hash` recorded in the database after a reasonable time window. The existing `SettlementQueueBacklog` alert (`worker_settlement_queue_depth > 50`) covers queue depth but not zero-queue silent stalls.

### Risk

If the worker crashes mid-settlement, the receipt stays in `PROCESSING` state. The recovery loop (`service.py:2108`) handles this, but it can fail silently if the prover is down, the RPC is unresponsive, or the `RM_SETTLEMENT_SIGNER_PRIVATE_KEY` is wrong. Users whose markets resolved can never claim because the on-chain settlement transaction was never submitted. There is currently no signal that this has happened.

### What to build

**Add a Prometheus alert in `docker/prometheus/alerts/trading_alerts.yml`:**

This requires a metric from the worker tracking markets in resolved state without a settlement tx. Add to `backend/worker/app/metrics.py`:
```python
worker_markets_pending_settlement = Gauge(
    "worker_markets_pending_settlement_total",
    "Markets resolved but without a confirmed settlement transaction",
)
```

Populate it in the worker's metrics loop by querying:
```sql
SELECT COUNT(*) FROM markets
WHERE resolved = true
  AND settlement_tx_hash IS NULL
  AND resolved_at < NOW() - INTERVAL '4 hours'
```

Then add alert rule:
```yaml
- alert: MarketsPendingSettlementStale
  expr: worker_markets_pending_settlement_total > 0
  for: 30m
  labels:
    severity: critical
  annotations:
    summary: "Markets resolved but not settled on-chain"
    description: "{{ $value }} markets have been resolved for >4h with no settlement tx."
```

### Acceptance criteria

- Metric `worker_markets_pending_settlement_total` is scraped by Prometheus.
- Alert fires within 30 minutes of a market being stuck in resolved-but-unsettled state.
- Alert resolves automatically when the settlement transaction is confirmed.

---

## Item 8 — Circuit hash not validated in CI

**Status:** Pending

### Current state

`backend/api/app/tasks.py:748` calls `validate_verifier_circuit_hash(settings)` at API startup and aborts if mismatched — this is good. But this only runs when the service starts in the deployment environment with `PROVER_CIRCUIT_HASH` set.

In CI, tests run with mocked/fixture circuit hashes. There is no CI step that validates the prover artifacts baked into the Docker image match the `circuitHash` stored in the deployed `RevealMarket` contract before a build is promoted to production.

### Risk

A workflow that upgrades prover artifacts (new circuit version, new `zkey`) without also updating the on-chain verifier — or vice versa — will pass all tests, pass CI, and deploy successfully. The mismatch is detected only at API startup in production, which aborts the service. Worse: if `PROVER_CIRCUIT_HASH` is not set in the deploy environment, the startup check is skipped entirely and the first `verifyAndSettleBatched` call on-chain fails, breaking settlement for all active markets.

### What to build

Add a CI job step in `.github/workflows/cicd.yml` that runs after image builds but before deploy:

```yaml
- name: Verify circuit hash alignment
  run: |
    # Read hash from prover artifact manifest
    ARTIFACT_HASH=$(cat prover/artifacts/settlement_hashes.json | jq -r '.circuit_hash')

    # Read hash from deployed contract on testnet
    ONCHAIN_HASH=$(cast call \
      --rpc-url "$TESTNET_RPC_URL" \
      "$REVEAL_MARKET_ADDRESS" \
      "circuitHash()(bytes32)")

    if [ "$ARTIFACT_HASH" != "$ONCHAIN_HASH" ]; then
      echo "CIRCUIT HASH MISMATCH"
      echo "  Artifact: $ARTIFACT_HASH"
      echo "  On-chain: $ONCHAIN_HASH"
      exit 1
    fi
    echo "Circuit hash aligned: $ARTIFACT_HASH"
```

Add required secrets to CI: `TESTNET_RPC_URL`, `REVEAL_MARKET_ADDRESS`.

This job must gate the deploy step — it should be a dependency, not run in parallel.

### Acceptance criteria

- CI fails with a clear message when artifact hash and on-chain hash diverge.
- The check runs on every push to `main` and on every PR targeting `main`.
- `PROVER_CIRCUIT_HASH` is required (not optional) in the prod deploy environment, enforced by `startup_validation.py`.

---

## Item 9 — Internal service ports not firewall-verified

**Status:** Pending

### Current state

Services bind to `0.0.0.0` inside the Docker network but `docker-compose.yml` does not map host ports for internal services (relayer `:8088`, hedger `:8090`, prover `:8085`, streamer `:8100`, Prometheus `:9090`, Postgres `:5432`, Redis `:6379`). Caddy is the only intended ingress. This is the correct design.

**The gap:** Docker's networking model creates iptables rules in the `DOCKER` chain that can bypass `ufw` INPUT rules. A VPS with `ufw deny 8090` may still have port 8090 reachable externally because Docker's `DOCKER` iptables chain accepts traffic before the `INPUT` chain rules run. This is a well-documented Docker-specific footgun.

### Risk

If internal ports are publicly reachable:
- Hedger `/admin/*` routes are accessible without auth (auth is only enforced in non-local envs, but the network should not be the only protection layer).
- Prometheus `:9090` exposes all metrics, alert rules, and scrape targets.
- Redis `:6379` is accessible for direct reads/writes (only `protected-mode yes` as guard).
- Postgres `:5432` is accessible for direct connection attempts.

### What to build

**Verification script** (`scripts/verify_firewall.sh`):
```bash
#!/usr/bin/env bash
set -euo pipefail
SERVER="${1:?Usage: verify_firewall.sh <server-ip>}"
BLOCKED_PORTS=(8085 8088 8090 8100 9090 5432 6379 9187 9121)

echo "Checking blocked ports on $SERVER..."
for port in "${BLOCKED_PORTS[@]}"; do
  if nc -z -w3 "$SERVER" "$port" 2>/dev/null; then
    echo "FAIL: port $port is REACHABLE from outside"
    EXIT_CODE=1
  else
    echo "OK:   port $port is blocked"
  fi
done

exit "${EXIT_CODE:-0}"
```

**Cloud security group rules** (AWS/GCP/Hetzner): Set explicit DENY rules for all ports except 22, 80, 443 at the cloud provider level — these rules run before the instance's iptables and cannot be bypassed by Docker.

Do not rely solely on `ufw` for Docker containers — use cloud-level firewall rules.

### Acceptance criteria

- `scripts/verify_firewall.sh <prod-server-ip>` exits 0 (all internal ports blocked).
- Cloud security group shows explicit allow rules only for 22, 80, 443.
- Script added to pre-launch checklist and post-deploy verification steps.

---

## Item 10 — Alertmanager not configured (alerts fire but go nowhere)

**Status:** Pending

### Current state

`docker/prometheus/prometheus.yml` has no `alerting:` section. Three well-written alert rule files exist:
- `docker/prometheus/alerts/trading_alerts.yml` — FX staleness, prover down, relayer circuit breaker, risk breaches, settlement backlog, chain head lag.
- `docker/prometheus/alerts/service_alerts.yml` — service down, high error rate, high p95 latency, worker sync stale, proof queue depth.
- `docker/prometheus/alerts/infrastructure_alerts.yml` — Postgres connections, deadlocks, Redis memory, evictions.

All of these fire internally in Prometheus and are visible in the Prometheus UI, but **no notification is delivered anywhere**. No Alertmanager container exists in `docker-compose.yml`.

### What to build

**1. Add Alertmanager to `docker-compose.yml`:**
```yaml
alertmanager:
  image: prom/alertmanager:v0.27.0
  container_name: reveal-market-alertmanager
  restart: unless-stopped
  volumes:
    - ./docker/alertmanager/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro
  command:
    - "--config.file=/etc/alertmanager/alertmanager.yml"
    - "--storage.path=/alertmanager"
    - "--web.listen-address=0.0.0.0:9093"
  healthcheck:
    test: ["CMD-SHELL", "wget -qO- http://127.0.0.1:9093/-/healthy || exit 1"]
    interval: 15s
    timeout: 5s
    retries: 3
    start_period: 10s
```

**2. Add `alerting:` section to `docker/prometheus/prometheus.yml`:**
```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets: ["alertmanager:9093"]
```

**3. Create `docker/alertmanager/alertmanager.yml`:**
```yaml
global:
  resolve_timeout: 5m

route:
  group_by: ["alertname", "severity"]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: discord-warnings
  routes:
    - match:
        severity: critical
      receiver: discord-critical
      repeat_interval: 1h

receivers:
  - name: discord-warnings
    webhook_configs:
      - url: "${DISCORD_ALERT_WEBHOOK_URL}"
        send_resolved: true
        http_config:
          follow_redirects: true
        title: '[{{ .Status | toUpper }}] {{ .GroupLabels.alertname }}'
        text: |
          {{ range .Alerts }}
          **{{ .Annotations.summary }}**
          {{ .Annotations.description }}
          {{ end }}

  - name: discord-critical
    webhook_configs:
      - url: "${DISCORD_ALERT_WEBHOOK_URL}"
        send_resolved: true
        title: ':red_circle: CRITICAL: {{ .GroupLabels.alertname }}'
        text: |
          {{ range .Alerts }}
          **{{ .Annotations.summary }}**
          {{ .Annotations.description }}
          Labels: {{ range .Labels.SortedPairs }}{{ .Name }}={{ .Value }} {{ end }}
          {{ end }}

inhibit_rules:
  - source_match:
      severity: critical
    target_match:
      severity: warning
    equal: ["alertname"]
```

Add to `.env.example`:
```
DISCORD_ALERT_WEBHOOK_URL=<REDACTED>
```

### Acceptance criteria

- `amtool alert query` returns active alerts from the Alertmanager container.
- A test alert (`amtool alert add alertname=TestAlert severity=warning`) delivers a Discord message within 2 minutes.
- Critical alerts post with a distinct format (red circle prefix) vs warnings.
- Resolved alerts send a follow-up "resolved" message to Discord.

---

## Item 11 — No emergency runbooks

**Status:** Pending

### Current state

No documented emergency procedures exist for any of the following scenarios. During an incident, every step becomes an improvised investigation under time pressure.

### What to build

Create `docs/runbooks/` directory with the following files. Minimum viable content for each is described below.

---

**`docs/runbooks/pause-markets.md`**

Covers: how to pause all markets when a critical bug is detected.

Contents:
- Which key calls `RevealMarket.pause()` (deployer EOA or Safe).
- Foundry one-liner: `cast send --private-key $DEPLOYER_KEY $CONTRACT_ADDRESS "pause()"`.
- What happens to in-flight commitments when paused (they cannot claim until unpaused).
- How to verify pause state: `cast call $CONTRACT_ADDRESS "paused()(bool)"`.
- How to unpause and what checks to run first.

---

**`docs/runbooks/key-rotation.md`**

Covers: rotating the relayer signing key and the pricing signer key.

Contents:
- **Relayer key rotation:** Update `RELAYER_PRIVATE_KEY` in prod secrets → redeploy relayer container → verify new address is authorized in `RelayerEscrow` → update authorization if needed.
- **Pricing signer rotation:** Update `RM_PRICING_SIGNER_PRIVATE_KEY` → redeploy API → all outstanding signed quotes become invalid (they use the old signer address) → document the expiry window.
- Order of operations: new key live before old key removed.
- How to verify the new key is active: check `/healthz` signer presence field.

---

**`docs/runbooks/stuck-proof-queue.md`**

Covers: proof jobs stuck in `PROCESSING` state.

Contents:
- How to inspect queue state: `GET /internal/settlement/queue` with `X-Internal-Secret`.
- Safe replay: change status from `PROCESSING` back to `PENDING` for jobs older than 30 minutes.
- Discard path: move to dead-letter queue for jobs that have failed >3 times.
- How to confirm prover is healthy before replaying: `GET http://prover:8085/healthz`.
- What to check if all replays fail: circuit hash mismatch, artifacts missing, RPC unresponsive.

---

**`docs/runbooks/migration-rollback.md`**

Covers: rolling back a bad database migration.

Contents:
- List current revision: `cd backend/migrations && alembic current`.
- Roll back one step: `alembic downgrade -1`.
- Roll back to specific revision: `alembic downgrade <revision_id>`.
- Which migrations are data-destructive (review each migration file before rolling back).
- Always take a pg_dump before any migration in production.

---

**`docs/runbooks/redis-flush.md`**

Covers: when and how to flush Redis safely.

Contents:
- What Redis holds: rate limit buckets, nonce dedup keys (TTL), worker heartbeats, cache tags, batch proof queues, lock_batches lease.
- Safe to flush: rate limit buckets, cache tags (API rehydrates on next request).
- NOT safe to flush during active proof generation: proof queue keys, lock_batches lease.
- Procedure: verify worker is idle, verify no active proof jobs, run `redis-cli FLUSHDB`, monitor worker heartbeat recovery.

---

### Acceptance criteria

- `docs/runbooks/` directory contains all five files above.
- Each runbook has been reviewed and the commands have been tested on the staging/local environment.
- Runbook directory is linked from the main `README.md`.

---

## Item 12 — Prover artifacts unsigned

**Status:** Deferred (before scaling TVL)

### Current state

`run_prod.sh` and `run_local.sh` download prover artifacts and verify against SHA256 hashes in `prover/artifacts/settlement_hashes.json`. This prevents accidental corruption but not a targeted attack.

### Risk

The SHA256 hash and the artifacts are served from the same origin (`PROVER_ARTIFACTS_URL`). If that origin is compromised, an attacker can replace both the artifacts and the hash file simultaneously. The verification script would pass. Malicious WASM could generate proofs that pass the local witness generation step but produce invalid public signals, causing on-chain settlement failures or — in a more sophisticated attack — proofs that validate with wrong outcomes.

### What to build

1. Generate an Ed25519 signing keypair (offline, on a secure machine):
   ```bash
   openssl genpkey -algorithm ed25519 -out artifact-signing-key.pem
   openssl pkey -in artifact-signing-key.pem -pubout -out artifact-signing-key.pub
   ```
2. Sign the artifact manifest at release time:
   ```bash
   openssl pkeyutl -sign \
     -inkey artifact-signing-key.pem \
     -in prover/artifacts/settlement_hashes.json \
     -out prover/artifacts/settlement_hashes.json.sig
   ```
3. Hardcode the public key in the artifact download/verify script.
4. Verify signature before using artifacts:
   ```bash
   openssl pkeyutl -verify \
     -pubin -inkey artifact-signing-key.pub \
     -in prover/artifacts/settlement_hashes.json \
     -sigfile prover/artifacts/settlement_hashes.json.sig
   ```

The private signing key never leaves the secure release machine. Compromising the artifact server is no longer sufficient to serve malicious artifacts.

### Acceptance criteria

- Artifact download script fails loudly if signature verification fails.
- Signing key is stored offline (not on the server or in CI secrets).
- Public key is hardcoded in the verification script and committed to the repo.

---

## Item 13 — No load test

**Status:** Deferred (before public launch / marketing push)

### Current state

No load test scripts exist. The system has never been tested above single-user traffic. Three serialized bottlenecks exist that each fail differently under load.

### Risk

**Bottleneck 1 — Prover:** Groth16 proof generation is CPU-bound and single-threaded per job. 100 concurrent commits filling 256-commitment batches stacks up multiple proof jobs. Unknown: does the worker OOM at high queue depth? Does it reject new jobs or silently enqueue?

**Bottleneck 2 — Redis:** `maxclients 256` (5 services × ~20 pool connections + headroom). Under load, this may be exhausted, causing `RedisError` in rate limiting (falls back to allowing), nonce dedup (falls back to bypassing — see Item 4), and cache invalidation.

**Bottleneck 3 — Streamer:** `history_limit: 500` per outcome. Under 100 concurrent SSE subscribers, unknown whether the streamer event loop falls behind on FX updates, which would trigger the `FXStaleness` alert and break pricing.

### What to build

Create `scripts/load/load_test.js` (k6):
```javascript
import http from "k6/http";
import { check, sleep } from "k6";

export let options = {
  vus: 100,
  duration: "10m",
  thresholds: {
    http_req_duration: ["p(95)<2000"],  // 2s p95
    http_req_failed: ["rate<0.01"],     // <1% errors
  },
};

export default function () {
  // 1. Load market list
  const markets = http.get(`${__ENV.API_BASE}/markets`);
  check(markets, { "markets 200": (r) => r.status === 200 });

  // 2. Request quote
  const quote = http.post(`${__ENV.API_BASE}/pricing/quote`, JSON.stringify({
    market_id: __ENV.TEST_MARKET_ID,
    outcome: "yes",
    amount_zen: "1.0",
  }), { headers: { "Content-Type": "application/json" } });
  check(quote, { "quote 200": (r) => r.status === 200 });

  sleep(1);
}
```

Run against staging environment, observe:
- API p95 latency under load.
- Proof queue depth in Prometheus.
- Redis connection count.
- Streamer FX lag.
- Any OOM kills or container restarts.

### Acceptance criteria

- 100 concurrent users for 10 minutes with <2s p95 latency and <1% error rate.
- No container OOM kills during the test.
- Redis `connected_clients` stays below 200 (80% of `maxclients 256`).
- Streamer FX lag stays below the `FXStaleness` alert threshold (60s).
- All identified bottlenecks are documented and either fixed or explicitly accepted.

---

## Summary

| # | Item | Phase | Effort | Owner |
|---|------|-------|--------|-------|
| 1 | Relayer key via file/HSM | Deferred | 2–3 hrs | — |
| 2 | Webhook secret required in prod | Now | 30 min | — |
| 3 | Rate limiting on by default | Now | 30 min | — |
| 4 | Redis persistence + nonce 503 | Now | 1 hr | — |
| 5 | Contracts on multisig | Deferred | 2–3 days | — |
| 6 | DB backup + restore runbook | Now | 1 day | — |
| 7 | Alert for stale market settlement | Now | 2–3 hrs | — |
| 8 | Circuit hash check in CI | Now | 2–3 hrs | — |
| 9 | Firewall verification script | Now | 1 hr | — |
| 10 | Alertmanager + Discord delivery | Now | 2–3 hrs | — |
| 11 | Emergency runbooks | Now | 1–2 days | — |
| 12 | Signed prover artifacts | Deferred | 1 day | — |
| 13 | Load test | Deferred | 2–3 days | — |
