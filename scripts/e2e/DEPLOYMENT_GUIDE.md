# Production Deployment Guide

This document captures all issues discovered during E2E testing on Horizen Testnet (chain 2651420) and provides a checklist for deploying to mainnet. Written from the debugging session on 2026-03-06.

---

## Table of Contents

1. [Contract Addresses & Keys](#1-contract-addresses--keys)
2. [Pre-Deployment Checklist](#2-pre-deployment-checklist)
3. [RelayerEscrow Ownership Transfer](#3-relayerescrow-ownership-transfer)
4. [Commit Authorization Flow (BLOCKER)](#4-commit-authorization-flow-blocker)
5. [API Configuration Gotchas](#5-api-configuration-gotchas)
6. [Event Groups vs Sub-Markets](#6-event-groups-vs-sub-markets)
7. [Streamer & CLOB Data](#7-streamer--clob-data)
8. [Relayer Log Bug](#8-relayer-log-bug)
9. [Dashboard Position Filtering](#9-dashboard-position-filtering)
10. [E2E Test Script Usage](#10-e2e-test-script-usage)
11. [Docker Compose Notes](#11-docker-compose-notes)
12. [Verifier Approval in Factory](#12-verifier-approval-in-factory-blocker)

---

## 1. Contract Addresses & Keys

### Testnet Contracts (Chain 2651420)

| Contract | Address |
|----------|---------|
| ZEN Token | `0x070040A826B586b58569750ED43cb5979b171e8d` |
| RelayerEscrow | `0x5b0fA47675D07b018E2151d49d4aECc71b47E47D` |
| MarketFactory | `0x07e13179E5231B3823f26ECBA2750834cBAfC9d3` |
| ProtocolPool | `0x314E44e894DeFDDb4c7337F7031901Ef7Bbab2E2` |
| Verifier | `0xC319CC9576dAc33440ab2b7013D067CbD88aBd07` |
| RevealMarket (impl) | `0xbcED5F91eFDf98Cde4bAaAd7F00585c32189317F` |

### Key Roles

| Role | Description | Env Var |
|------|-------------|---------|
| **Deployer** | Deploys contracts, initial factory owner | `DEPLOYER_KEY` |
| **Relayer** | Submits on-chain txs (commit/claim/lock) | `RELAYER_PRIVATE_KEY` |
| **Auth Signer** | Signs commit auth digests (API-side) | `RM_PRICING_SIGNER_PRIVATE_KEY` |
| **Oracle** | Posts results, locks batches | `RM_ORACLE_PRIVATE_KEY` |

### Critical Requirement

The **RelayerEscrow owner** MUST be the relayer wallet address.
This is the wallet derived from `RELAYER_PRIVATE_KEY` — NOT the deployer.

---

## 2. Pre-Deployment Checklist

- [ ] Verify `RELAYER_PRIVATE_KEY` wallet has gas (native token) for transactions
- [ ] Verify `DEPLOYER_KEY` wallet has gas for contract deployment
- [ ] Verify ZEN token is deployed and funded to test wallets
- [ ] Deploy contracts (MarketFactory, RelayerEscrow, ProtocolPool, Verifier)
- [ ] **Transfer RelayerEscrow ownership to relayer wallet** (see Section 3)
- [ ] **Approve verifier in factory** via `setVerifierApproval` (see Section 12)
- [ ] **Redeploy contracts** (commit authorization gate removed — see Section 4)
- [ ] Configure `.env.production` with correct addresses and keys
- [ ] Start services with `--env-file .env.production`
- [ ] Verify API health: `curl https://<api-domain>/healthz` (NOT `/health`)
- [ ] Verify streamer is receiving CLOB data: check for `missing_market_id` warnings (some are normal)
- [ ] Run `api_commit_test.py` to validate full flow

---

## 3. RelayerEscrow Ownership Transfer

### Problem

`RelayerEscrow.commitOnBehalf()` has an `onlyOwner` modifier. After deployment, the owner is the deployer wallet. The relayer wallet (which actually calls `commitOnBehalf`) is different, causing `OwnableUnauthorizedAccount(relayerAddress)` reverts.

### Error Signature

```
Error selector: 0x118cdaa7
Decoded: OwnableUnauthorizedAccount(address)
```

### Fix (2-Step — OpenZeppelin Ownable2Step)

The escrow uses `Ownable2Step`, which requires both `transferOwnership` and `acceptOwnership`:

**Step 1: Transfer (from deployer)**
```python
from web3 import Web3
from eth_account import Account

w3 = Web3(Web3.HTTPProvider("https://horizen-testnet.rpc.caldera.xyz/http"))
deployer = Account.from_key(DEPLOYER_KEY)
relayer_address = Account.from_key(RELAYER_KEY).address

escrow = w3.eth.contract(address=ESCROW_ADDRESS, abi=[{
    "inputs": [{"name": "newOwner", "type": "address"}],
    "name": "transferOwnership",
    "outputs": [],
    "stateMutability": "nonpayable",
    "type": "function"
}])

tx = escrow.functions.transferOwnership(relayer_address).build_transaction({
    "from": deployer.address,
    "nonce": w3.eth.get_transaction_count(deployer.address),
    "gas": 100_000,
    "gasPrice": w3.eth.gas_price,
    "chainId": 2651420,
})
signed = deployer.sign_transaction(tx)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
w3.eth.wait_for_transaction_receipt(tx_hash)
```

**Step 2: Accept (from relayer)**
```python
relayer = Account.from_key(RELAYER_KEY)

escrow_accept = w3.eth.contract(address=ESCROW_ADDRESS, abi=[{
    "inputs": [],
    "name": "acceptOwnership",
    "outputs": [],
    "stateMutability": "nonpayable",
    "type": "function"
}])

tx = escrow_accept.functions.acceptOwnership().build_transaction({
    "from": relayer.address,
    "nonce": w3.eth.get_transaction_count(relayer.address),
    "gas": 100_000,
    "gasPrice": w3.eth.gas_price,
    "chainId": 2651420,
})
signed = relayer.sign_transaction(tx)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
w3.eth.wait_for_transaction_receipt(tx_hash)
```

**Verification:**
```python
owner_abi = [{"inputs":[],"name":"owner","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"}]
escrow_view = w3.eth.contract(address=ESCROW_ADDRESS, abi=owner_abi)
assert escrow_view.functions.owner().call() == relayer_address
```

### Testnet Status

Completed on testnet (2026-03-06, second deployment):
- `transferOwnership` TX: `0xbcbd1e25...` (block 11230282)
- `acceptOwnership` TX: `0x2e56fa09...` (block 11230292)

---

## 4. Commit Authorization Flow (RESOLVED)

### Resolution

The `approveCommitAuthorization` gate has been **removed from the contract**. The commit flow is now single-step:

1. User deposits collateral to escrow
2. API builds `CommitAuth` struct + signature
3. Relayer calls `commitOnBehalf(user, market, auth, signature)` on-chain

The commit is protected by:
- `onlyOwner` — only the relayer wallet can call `commitOnBehalf`
- `commitWithAuthorization` signature verification on the market contract (signed by `RM_PRICING_SIGNER_PRIVATE_KEY`)
- Wallet signature verified by the API (`X-Wallet-Signature` header)

### Action Required

**Contract must be redeployed** on testnet (and later mainnet) for this fix to take effect on-chain.

---

## 5. API Configuration Gotchas

### Health Endpoint

The API health endpoint is `/healthz`, NOT `/health`. Scripts and monitoring should use:
```
GET https://<api-domain>/healthz
```

### Internal API Secret

Routes under `/internal/*` require the `X-Internal-Secret` header:
```
X-Internal-Secret: <value of RM_INTERNAL_API_SECRET>
```

### Pricing Chain ID

`RM_PRICING_CHAIN_ID` must match the deployed chain. A mismatch causes `quote_chain_mismatch` errors.

### Streamer FX Endpoint

The pricing engine fetches FX rates from the streamer at:
```
http://streamer:8100/fx/zen-usd
```
If the streamer is down or unreachable, `/pricing/quote` returns `503 pricing_unavailable`.

---

## 6. Event Groups vs Sub-Markets

### Problem

The `/events` API returns **event groups**, not individual tradeable markets. Each event group has a `markets[]` array containing sub-markets.

```json
{
  "id": "6fb8dcf1-...",           // event group ID
  "title": "Will X happen?",
  "markets": [
    {
      "event_id": "abc123-...",    // sub-market ID (use this for pricing!)
      "condition_id": "0x...",     // needed for CLOB price lookups
      "title": "Sub-market title"
    }
  ]
}
```

### Key Rules

- **For pricing quotes**: Use `markets[].event_id` as `market_id`, NOT the top-level group `id`
- **For CLOB data**: The streamer caches prices by `condition_id`. Only sub-markets with a `condition_id` can get live pricing.
- **For display**: Use the top-level group for event titles and the sub-market for trading.

### Common Error

Using the top-level event group ID in `/pricing/quote`:
```
503: pricing_unavailable — no CLOB data found
```

The API's `_resolve_outcome_price()` at `backend/api/app/routes/pricing.py:149` tries `condition_id` from the market DB record, falling back to `market_id`. If neither matches streamer cache keys, pricing fails.

---

## 7. Streamer & CLOB Data

### Normal Warnings

The streamer logs `missing_market_id` warnings for ~5% of markets. This is expected — some Polymarket conditions don't have corresponding RevealMarket markets.

### Validation

Check streamer health:
```bash
curl http://streamer:8100/health
```

Check if FX data is available:
```bash
curl http://streamer:8100/fx/zen-usd
```

Check if a specific condition has CLOB data:
```bash
curl http://streamer:8100/clob/<condition_id>
```

---

## 8. Relayer Log Bug

### Problem

In `relayer/src/relayer/service.py:599-600`, the log labels for the `auth` tuple are wrong:

```python
logger.info(
    "relayer.commit.prepare",
    nonce=auth[2],   # Actually prints user_addr (auth tuple index 2)
    expiry=auth[3],  # Actually prints nonce value (auth tuple index 3)
    ...
)
```

The `auth` tuple is `(commitment, ticket_id, user_addr, nonce, expiry, ticket_value)`, so:
- `auth[2]` = `user_addr` (logged as "nonce")
- `auth[3]` = `nonce` (logged as "expiry")

### Fix

```python
nonce=auth[3],    # auth[3] is the actual nonce
expiry=auth[4],   # auth[4] is the actual expiry
user=auth[2],     # auth[2] is the user address
```

This is cosmetic and doesn't affect functionality.

---

## 9. Dashboard Position Filtering

### Problem

The `/positions` endpoint returned ALL commitments, including ones where:
- The relayer job hadn't succeeded yet
- The `tx_hash` field contained a relayer job ID instead of a real on-chain hash

This showed phantom positions on the user dashboard.

### Fix Applied

In `backend/api/app/routes/trade.py:2037-2039`:

```python
if tx_hash_value and not _is_hex_tx(tx_hash_value):
    tx_hash_value = None
if not tx_hash_value:     # <-- NEW: skip unconfirmed
    continue              # <-- positions entirely
```

### Behavior

- Positions with a valid `0x` + 64-char hex tx hash: shown
- Positions with a relayer job ID that resolved to a valid tx hash: shown
- Positions with no confirmed tx hash: hidden

---

## 10. E2E Test Script Usage

### Script: `scripts/e2e/api_commit_test.py`

This script mimics the frontend's exact commit flow against the production API.

### Required Environment Variables

```bash
export API_URL="https://api.revealmarket.xyz"   # or http://localhost:8000
export TEST_WALLET_KEY="0x..."                   # Private key for test wallet
export RM_INTERNAL_API_SECRET=<REDACTED>
```

### Steps Executed

| Step | Description |
|------|-------------|
| 1 | Health check (`/healthz`) |
| 2 | Check wallet ZEN balance + escrow balance |
| 3 | Deposit 0.1 ZEN to escrow (approve + deposit) |
| 4 | Find active sub-market with `condition_id` and `closes_at > now` |
| 5 | Request pricing quote (`/pricing/quote`) |
| 6 | Build & sign commit message (mirrors `frontend/lib/signature-messages.ts`) |
| 7 | Submit commit (`/trade/commit`) |
| 8 | Poll relayer status (`/trade/status`) |
| 9 | Verify position on dashboard (`/positions`) |

### Note

After contract redeployment, the full flow should complete without authorization errors.

### Running

```bash
cd scripts/e2e
python api_commit_test.py
```

---

## 11. Docker Compose Notes

### Environment File

Production deployments MUST use `--env-file`:
```bash
docker compose --env-file .env.production up -d
```

Without `--env-file`, services start with empty/default env vars and fail silently.

### Service Health Checks

```bash
# API
curl https://<domain>/healthz

# All services
docker compose ps

# Service logs
docker compose logs api --tail 200
docker compose logs relayer --tail 200
docker compose logs streamer --tail 200
```

### Rebuilding

```bash
# Full rebuild
docker compose --env-file .env.production up -d --build

# Single service rebuild
docker compose --env-file .env.production up -d --build api
```

---

## 12. Verifier Approval in Factory (BLOCKER)

### Problem

After redeploying all contracts, `createMarket` reverts with no error data. The factory's `_validateVerifier()` checks `approvedVerifier[verifier]`, which is an empty mapping on a fresh factory deployment.

The factory performs 6 validation checks on the verifier:
1. Non-zero address
2. **`approvedVerifier` mapping** (this is the blocker)
3. Verifier `owner()` matches factory `owner()`
4. `expectedInputs()` returns 10
5. `circuitHash()` matches the provided hash
6. Codehash and verifying key hash match pinned values

### Error Signature

The `createMarket` call reverts with empty error data (`0x`), which maps to `VerifierNotApproved()`.

### Fix

The factory owner must call `setVerifierApproval(verifier, true)`:

```python
from web3 import Web3
from eth_account import Account

w3 = Web3(Web3.HTTPProvider("https://horizen-testnet.rpc.caldera.xyz/http"))
deployer = Account.from_key(DEPLOYER_KEY)

FACTORY = "0x07e13179E5231B3823f26ECBA2750834cBAfC9d3"
VERIFIER = "0xC319CC9576dAc33440ab2b7013D067CbD88aBd07"

approve_abi = [{
    "inputs": [
        {"name": "verifier", "type": "address"},
        {"name": "approved", "type": "bool"}
    ],
    "name": "setVerifierApproval",
    "outputs": [],
    "stateMutability": "nonpayable",
    "type": "function"
}]

factory = w3.eth.contract(address=FACTORY, abi=approve_abi)

tx = factory.functions.setVerifierApproval(VERIFIER, True).build_transaction({
    "from": deployer.address,
    "nonce": w3.eth.get_transaction_count(deployer.address),
    "gas": 200_000,
    "gasPrice": w3.eth.gas_price,
    "chainId": 2651420,
})
signed = deployer.sign_transaction(tx)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
assert receipt.status == 1
```

### Prerequisites

Before `setVerifierApproval` succeeds, the verifier must:
- Have `owner()` matching the factory owner (deployer)
- Return `expectedInputs() == 10`
- Have valid `codehash` and `verifyingKeyHash()`

### Verification

```python
check_abi = [{"inputs":[{"name":"","type":"address"}],"name":"approvedVerifier","outputs":[{"name":"","type":"bool"}],"stateMutability":"view","type":"function"}]
factory_check = w3.eth.contract(address=FACTORY, abi=check_abi)
assert factory_check.functions.approvedVerifier(VERIFIER).call() == True
```

### Testnet Status

Completed on testnet:
- `setVerifierApproval` TX: `0x10f07d10...`

---

## 13. Events Endpoint Requires `status=commit`

### Problem

After a fresh deployment, calling `GET /events` without a status filter returns an empty list `[]`, even when 20k+ markets exist in the database with `status=commit`. This happens because:

1. The Redis cache was populated while the worker was still syncing (empty DB → cached empty list)
2. Even after flushing the cache, the default query path (no status filter) returns 0 results

### Fix

Always pass `status=commit` when querying tradeable markets:

```
GET /events?status=commit
```

The `status=commit` maps to `MarketStatusEnum.COMMIT` in `_apply_common_filters`, which is the on-chain "open for trading" state. This is also what `status=active` resolves to internally.

### E2E Test Impact

The `api_commit_test.py` was updated to use `/events?status=commit` instead of `/events`.

---

## 14. Commit Must Be Called Internally

### Problem

Calling `POST /trade/commit` via the external Cloudflare endpoint (`https://api.revealmarket.xyz`) returns `502 Bad Gateway`. The commit endpoint takes 5-13 seconds (market creation + relayer submission), which exceeds Cloudflare's default timeout.

### Fix

The E2E test must be run from **inside the prod server**, calling the API at `http://localhost:8000`:

```bash
# Copy test script to server
scp scripts/e2e/api_commit_test.py reveal-market-prod:/tmp/api_commit_test.py

# Copy into API container and run
ssh reveal-market-prod "docker cp /tmp/api_commit_test.py reveal-market-api:/tmp/api_commit_test.py"
ssh reveal-market-prod "docker exec -e API_URL=http://localhost:8000 -e TEST_WALLET_KEY=<key> reveal-market-api python /tmp/api_commit_test.py"
```

### Production Consideration

The frontend's commit flow also calls `/trade/commit`. If Cloudflare times out on real user traffic, consider:
- Increasing Cloudflare's proxy read timeout
- Making the commit endpoint async (return job ID immediately, client polls)

---

## 15. Redis "Too Many Connections" After Rebuild

### Problem

After container rebuild and full worker sync, Redis logs `Too many connections` errors on cache reads. This happens because the worker's initial sync creates many concurrent page-processing tasks that each need Redis connections.

### Impact

- Cache reads fail gracefully (API falls back to DB queries)
- Not a blocker, but increases API latency during initial sync

### Fix

Wait for the worker's initial sync to complete. Subsequent sync cycles are much smaller (14-day window).

---

## Summary of Issues Found

| Issue | Severity | Status | Section |
|-------|----------|--------|---------|
| Escrow owner != relayer wallet | Critical | Fixed (testnet) | 3 |
| `approveCommitAuthorization` gate removed | Critical | **RESOLVED** (redeploy needed) | 4 |
| Health endpoint is `/healthz` not `/health` | Low | Fixed in scripts | 5 |
| Event group ID vs sub-market ID confusion | Medium | Fixed in scripts | 6 |
| Relayer log field mismatch | Low | Known, cosmetic | 8 |
| Dashboard shows phantom positions | Medium | Fixed | 9 |
| Verifier not approved in factory | Critical | Fixed (testnet) | 12 |
| `/events` requires `status=commit` | Medium | Fixed in scripts | 13 |
| Commit 502 via Cloudflare | Medium | Run internally | 14 |
| Redis too many connections on rebuild | Low | Transient | 15 |
