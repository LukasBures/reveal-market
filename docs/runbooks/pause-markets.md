# Runbook: Pause All Markets

Use when a critical bug is detected that requires halting all trading activity.

## When to use

- Smart contract exploit or unexpected behaviour discovered
- Oracle manipulation detected
- Settlement producing wrong outcomes
- Any situation where new commitments must stop immediately

## Prerequisites

- Access to the deployer EOA private key (or Gnosis Safe with required signers)
- Foundry (`cast`) installed locally
- RPC endpoint access (`TESTNET_RPC_URL` or mainnet RPC)

## Steps

### 1. Pause the contract

```bash
# Set variables
export RPC_URL="https://horizen.calderachain.xyz/http"
export CONTRACT_ADDRESS="<REVEAL_MARKET_ADDRESS>"
export DEPLOYER_KEY="<DEPLOYER_PRIVATE_KEY>"

# Pause
cast send \
  --rpc-url "${RPC_URL}" \
  --private-key "${DEPLOYER_KEY}" \
  "${CONTRACT_ADDRESS}" \
  "pause()"
```

If using Gnosis Safe: propose the `pause()` call via the Safe UI and collect required signatures.

### 2. Verify pause state

```bash
cast call \
  --rpc-url "${RPC_URL}" \
  "${CONTRACT_ADDRESS}" \
  "paused()(bool)"
# Expected output: true
```

### 3. Stop the relayer from submitting new transactions

```bash
# On the prod server — stop accepting new commits
docker compose -f docker-compose.yml --env-file .env.production \
  stop relayer
```

Or set `RM_RELAYER_BASE_URL=` (empty) in the API environment and restart the API
to return 503 on new commit attempts without touching the relayer queue.

### 4. Communicate to users

- Post a status update on Discord / Twitter
- Frontend should show a maintenance banner (set `NEXT_PUBLIC_MAINTENANCE_MODE=true` if implemented)

## What happens to in-flight commitments

- Commitments already submitted on-chain before the pause are safe — they can be claimed after unpause
- Commitments in the relayer queue will fail to submit (contract is paused) and go to dead-letter
- The proof queue continues generating proofs but settlement submissions will revert

## Unpausing

Only unpause after the root cause is understood and fixed.

```bash
cast send \
  --rpc-url "${RPC_URL}" \
  --private-key "${DEPLOYER_KEY}" \
  "${CONTRACT_ADDRESS}" \
  "unpause()"
```

Verify: `cast call ... "paused()(bool)"` must return `false`.

After unpausing: restart the relayer and replay any dead-letter jobs if they are safe to retry.
