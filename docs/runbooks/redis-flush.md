# Runbook: Redis Flush

Use only when Redis state is known to be corrupt or in a stuck state that cannot
be resolved by targeted key deletion.

## What Redis holds — risk by key category

| Key pattern | Safe to flush? | Impact if flushed |
|---|---|---|
| `reveal_market:cache:*` | Yes | API cache miss on next request; auto-rehydrated |
| `reveal_market:rate_limit:*` | Yes | Rate limit buckets reset; abuse window until repopulated |
| `commit_nonce:*` | **No** (during active trading) | Nonce replay window opens until TTL expires naturally |
| `reveal_market:lock_batches:*` | **No** (if worker running) | Lock lease lost; concurrent lock-batch submissions possible |
| `reveal_market:worker:proof_queue:*` | **No** | Proof job queue lost; proof generation silently stops |
| `reveal_market:worker:heartbeat` | Yes | Stale heartbeat; worker re-registers on next tick |
| `reveal_market:bet_cap:*` | Caution | Per-user stake caps reset; temporarily allows overstaking |

**Never flush Redis while the proof queue has active jobs or while markets are accepting commits.**

## Safe flush procedure

### 1. Confirm it is safe to flush

```bash
# Verify proof queue is empty
curl -sf -H "X-Internal-Secret: ${RM_INTERNAL_API_SECRET}" \
  http://localhost:8000/internal/settlement/queue | jq '.pending_count'
# Must be 0

# Verify no markets are in active commitment window
# (check manually or via API that no open markets have recent commits)
```

### 2. Stop services that write to Redis

```bash
docker compose -f docker-compose.yml --env-file .env.production \
  stop worker relayer
```

### 3. Flush the database

```bash
# Connect to the Redis container
docker compose -f docker-compose.yml --env-file .env.production \
  exec redis redis-cli FLUSHDB

# Confirm empty
docker compose -f docker-compose.yml --env-file .env.production \
  exec redis redis-cli DBSIZE
# Expected: 0
```

### 4. Restart services

```bash
docker compose -f docker-compose.yml --env-file .env.production \
  up -d --no-deps worker relayer api
```

### 5. Verify recovery

```bash
# API should rehydrate its cache automatically
curl -sf https://api.revealmarket.xyz/healthz | jq '.redis'

# Worker heartbeat should reappear within 30s
curl -sf -H "X-Internal-Secret: ${RM_INTERNAL_API_SECRET}" \
  https://api.revealmarket.xyz/healthz/heartbeats | jq .
```

## Targeted key deletion (preferred over full flush)

If only specific keys are problematic, delete them individually:

```bash
docker compose exec redis redis-cli DEL "reveal_market:lock_batches:lease"
docker compose exec redis redis-cli DEL "reveal_market:cache:markets:list"

# Delete all keys matching a pattern (use with care)
docker compose exec redis redis-cli --scan --pattern "reveal_market:rate_limit:*" \
  | xargs docker compose exec redis redis-cli DEL
```
