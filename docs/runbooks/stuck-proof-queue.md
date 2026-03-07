# Runbook: Stuck Proof Queue

Use when proof or settlement jobs are stuck in `PROCESSING` state and not progressing.

## Symptoms

- `worker_markets_pending_settlement_total > 0` alert firing
- `ProofQueueDepthCritical` or `SettlementQueueBacklog` alert firing
- Users reporting they cannot claim resolved markets
- Worker logs show repeated `proof/settlement task still running` warnings

## Diagnosis

### 1. Check current queue state

```bash
# Internal API — get settlement queue state
curl -sf -H "X-Internal-Secret: ${RM_INTERNAL_API_SECRET}" \
  http://localhost:8000/internal/settlement/queue | jq .
```

### 2. Check prover health

```bash
curl -sf http://localhost:8085/healthz | jq .
# Look for: artifacts_ok, queue_depth, last_proof_at
```

### 3. Check worker logs for the stuck job

```bash
docker compose logs worker --tail=200 | grep -i "settlement\|proof\|processing\|stale"
```

### 4. Check if it is a signer/RPC issue

```bash
# Try an RPC call manually
cast block-number --rpc-url "${RM_RPC_URL}"
```

If the RPC is unresponsive, the settlement loop will keep retrying. Fix the RPC issue first.

## Recovery: replay stale PROCESSING jobs

Jobs stuck in `PROCESSING` for longer than `settlement_submission_processing_stale_seconds`
(default: 300s) are automatically re-queued by the worker's recovery loop. If the loop is
also stuck, trigger it manually via the internal API:

```bash
curl -sf -X POST \
  -H "X-Internal-Secret: ${RM_INTERNAL_API_SECRET}" \
  http://localhost:8000/internal/settlement/run
```

## Recovery: move jobs to dead-letter

If jobs are safe to discard (e.g. market already settled on-chain, or proof was
generated for wrong data):

```bash
# Check the internal dead-letter endpoint for failed jobs
curl -sf -H "X-Internal-Secret: ${RM_INTERNAL_API_SECRET}" \
  http://localhost:8000/internal/settlement/dead-letter | jq .
```

Do NOT discard jobs unless you have confirmed the market is either:
- Already settled on-chain (`cast call ... "getMarket()(tuple)"` shows settled=true)
- The proof is provably invalid (wrong batch root, wrong circuit)

## Recovery: restart the worker

If the worker is in a bad state (goroutine/async task leak):

```bash
docker compose -f docker-compose.yml --env-file .env.production \
  up -d --no-deps --force-recreate worker
```

The settlement recovery loop runs on startup and will pick up any `PROCESSING` jobs
older than the stale threshold.

## Prevention

- Ensure `RM_RPC_URL` is a reliable, low-latency endpoint (not a public rate-limited RPC)
- Ensure `PROVER_CIRCUIT_HASH` matches the deployed verifier (circuit hash alignment check in CI)
- Monitor `ProofQueueDepthCritical` to catch backlogs before they become stuck
