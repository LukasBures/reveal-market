# Horizen Mainnet Migration Plan

> **From**: Horizen Testnet (Chain ID `2651420`, Base Sepolia settlement)
> **To**: Horizen Mainnet (Chain ID `26514`, Base settlement)

---

## Table of Contents

1. [Reference: Testnet vs Mainnet](#1-reference-testnet-vs-mainnet)
2. [Phase 1: Generate Fresh Mainnet Wallets](#2-phase-1-generate-fresh-mainnet-wallets)
3. [Phase 2: Fund Mainnet Wallets](#3-phase-2-fund-mainnet-wallets)
4. [Phase 3: Deploy ZEN ERC-20 Token](#4-phase-3-deploy-zen-erc-20-token)
5. [Phase 4: Build & Upload ZK Artifacts](#5-phase-4-build--upload-zk-artifacts)
6. [Phase 5: Deploy Contracts to Mainnet](#6-phase-5-deploy-contracts-to-mainnet)
7. [Phase 6: Update Environment Files](#7-phase-6-update-environment-files)
8. [Phase 7: Update Hardcoded Defaults in Code](#8-phase-7-update-hardcoded-defaults-in-code)
9. [Phase 8: Update Frontend](#9-phase-8-update-frontend)
10. [Phase 9: Update Infrastructure](#10-phase-9-update-infrastructure)
11. [Phase 10: Update Tests](#11-phase-10-update-tests)
12. [Phase 11: Database & State](#12-phase-11-database--state)
13. [Phase 12: Pre-Launch Validation](#13-phase-12-pre-launch-validation)
14. [Phase 13: Go-Live Checklist](#14-phase-13-go-live-checklist)
15. [Phase 14: Post-Launch Monitoring](#15-phase-14-post-launch-monitoring)
16. [Appendix A: Rollback Plan](#appendix-a-rollback-plan)
17. [Appendix B: Testnet Preservation](#appendix-b-testnet-preservation)
18. [Appendix C: EIP-712 Domain Separator Impact](#appendix-c-eip-712-domain-separator-impact)
19. [Appendix D: Docker Resource Limits Review](#appendix-d-docker-resource-limits-review)
20. [Appendix E: Files to Change (Complete)](#appendix-e-files-to-change-complete)
21. [Appendix F: Address Inventory](#appendix-f-address-inventory)
22. [Appendix G: Risk Matrix](#appendix-g-risk-matrix)

---

## 1. Reference: Testnet vs Mainnet

| Property | Testnet (current) | Mainnet (target) |
|---|---|---|
| **Chain ID** | `2651420` | `26514` |
| **RPC (HTTP)** | `https://horizen-testnet.rpc.caldera.xyz/http` | `https://horizen.calderachain.xyz/http` |
| **RPC (WS)** | `wss://horizen-testnet.rpc.caldera.xyz/ws` | `wss://horizen.calderachain.xyz/ws` |
| **Explorer** | `https://horizen-testnet.explorer.caldera.xyz` | `https://horizen.explorer.caldera.xyz` (confirm from hub) |
| **Bridge** | `https://horizen-testnet.hub.caldera.xyz/` | `https://hub.horizen.io/` |
| **Settlement Layer** | Base Sepolia (`84532`) | Base (`8453`) |
| **Native Token** | ETH (testnet) | ETH (real) |
| **Rollup Stack** | OP Stack / Bedrock | OP Stack / Bedrock |
| **Hub / Dashboard** | `https://horizen-testnet.hub.caldera.xyz/` | `https://hub.horizen.io/` |
| **Faucet** | Available (testnet) | N/A (real money) |

---

## 2. Phase 1: Generate Fresh Mainnet Wallets

> **CRITICAL: Never reuse testnet private keys on mainnet.** Generate all-new keys and store them in a password manager / hardware wallet / KMS.

### Wallets to Generate

You need **7 distinct EOA wallets** for mainnet (6 on Horizen + 1 on Polygon if using hedger). Each serves a specific role:

| # | Role | Chain | Env Variable(s) | Purpose |
|---|------|-------|-----------------|---------|
| 1 | **Deployer / Owner** | Horizen | `DEPLOYER_KEY`, `RM_WALLET_PRIVATE_KEY` | Deploys contracts, owns Factory/Pool/Escrow. Must retain ownership. |
| 2 | **Oracle** | Horizen | `ORACLE_ADDRESS` (address only) | Resolves markets. Backend calls this to submit outcomes. |
| 3 | **Authorization Signer** | Horizen | `RM_AUTHORIZATION_SIGNER_PRIVATE_KEY`, `RM_PRICING_SIGNER_PRIVATE_KEY`, `AUTHORIZATION_SIGNER` | Signs commit-auth messages + pricing quotes. Used by API service. |
| 4 | **Relayer** | Horizen | `RM_RELAYER_PRIVATE_KEY` | Submits on-chain commit/claim/lock transactions. Needs ETH for gas. |
| 5 | **Settlement Signer** | Horizen | `RM_SETTLEMENT_SIGNER_PRIVATE_KEY` | Signs settlement batches. Used by worker service. |
| 6 | **Funding / Treasury** | Horizen | (manual, not in env) | Holds reserve ETH + ZEN tokens. Seeds other wallets. |
| 7 | **Hedger Vault Signer** | Polygon | `HEDGER_VAULT_PRIVATE_KEY`, `HEDGER_VAULT_SENDER_ADDRESS` | Signs Polygon vault txns (LP deposits/withdrawals). Only needed if hedger is active. |

### How to Generate

```bash
# Using existing gen_address.py script (from repo root):
cd scripts

# Generate 7 random addresses (one per role):
uv run gen_address.py --mode random --count 7

# Or for vanity prefixes (optional, slower):
uv run gen_address.py --mode vanity --prefix "0xdead" --count 1

# Results saved to scripts/generated/random_<timestamp>.txt
```

**IMPORTANT**: After generation:
- [ ] Record each address ↔ role mapping in a secure vault (1Password, Bitwarden, etc.)
- [ ] **Never commit mainnet private keys to git** — only put them in `.env.production` on the server
- [ ] Consider using a hardware wallet (Ledger/Trezor) for the Deployer/Owner and Treasury keys
- [ ] Derive the public address from each private key and record both
- [ ] Delete the generated plaintext file from `scripts/generated/` after recording in vault

### Quick Address Derivation Check

```bash
# Verify address matches key (using cast from Foundry):
cast wallet address --private-key 0x<your-new-private-key>
```

### Generate Fresh Secrets

Also generate new service-to-service secrets (do **not** reuse testnet values):

```bash
# Bearer tokens (hex):
python3 -c "import secrets; print(secrets.token_hex(24))"

# UUIDs (for internal API secrets):
python3 -c "import uuid; print(uuid.uuid4())"

# Strong Redis password:
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

You need fresh values for: `RELAYER_BEARER_TOKEN`, `RELAYER_API_BEARER_TOKEN`, `RM_INTERNAL_API_SECRET`, `RM_PROVER_SHARED_SECRET`, `RELAYER_API_INTERNAL_SECRET`, `REDIS_PASSWORD`, `HEDGER_ADMIN_INTERNAL_SECRET`, `HEDGER_PROVER_SHARED_SECRET`.

> **`RELAYER_BEARER_TOKEN` vs `RELAYER_API_BEARER_TOKEN`**: These are two distinct tokens. `RELAYER_BEARER_TOKEN` authenticates external callers **to** the relayer (e.g., the API/worker calling the relayer to submit transactions). `RELAYER_API_BEARER_TOKEN` authenticates the relayer when it calls **out** to the backend API. Both should be set for mainnet.

---

## 3. Phase 2: Fund Mainnet Wallets

### Step 1: Acquire ETH on Base

You need real ETH on **Base** (chain ID 8453) to bridge to Horizen Mainnet. Options:
- Buy ETH on Coinbase → withdraw to Base
- Bridge from Ethereum L1 to Base via [bridge.base.org](https://bridge.base.org)
- Transfer from existing Base wallet

### Step 2: Bridge ETH from Base → Horizen Mainnet

1. Go to **https://hub.horizen.io/**
2. Connect wallet containing Base ETH
3. Select **Base → Horizen Mainnet**
4. Bridge ETH in separate transactions to each wallet that needs gas:

| Wallet | Recommended Initial Funding | Reason |
|--------|---------------------------|--------|
| Deployer/Owner | **0.5 ETH** | Contract deployments are gas-heavy (5 contracts + setup txns) |
| Relayer | **0.3 ETH** | Frequent on-chain txns (commits, claims, locks). Top up regularly. |
| Settlement Signer | **0.1 ETH** | Periodic settlement batch submissions |
| Oracle | **0.05 ETH** | Market resolution txns (infrequent) |
| Auth Signer | **0.0 ETH** | Off-chain only (signs EIP-712 messages, no gas needed) |
| Funding / Treasury | **1.0+ ETH** | Reserve for topping up other wallets + protocol pool seeding |

**Total estimated initial funding: ~2.0 ETH minimum**

### Step 3: Verify Balances

```bash
# Check each wallet balance on Horizen Mainnet:
cast balance <ADDRESS> --rpc-url https://horizen.calderachain.xyz/http
```

---

## 4. Phase 3: Deploy ZEN ERC-20 Token

> The ZEN token (`0x070040A826B586b58569750ED43cb5979b171e8d`) on testnet is a custom ERC-20. You need a mainnet instance.

### Option A: Deploy New ZEN Token (if you own the token contract)

If you have the ZEN token source code:

```bash
# Deploy ZEN token to Horizen Mainnet
forge create src/ZenToken.sol:ZenToken \
  --rpc-url https://horizen.calderachain.xyz/http \
  --private-key $DEPLOYER_KEY \
  --chain-id 26514 \
  --broadcast
```

Record the deployed address → this becomes `ZEN_TOKEN_ADDRESS` / `NEXT_PUBLIC_ZEN_TOKEN_ADDRESS`.

### Option B: Use Existing Mainnet Token

If ZEN is already deployed on Horizen Mainnet by another party, get the address from them and verify it:

```bash
# Verify it's a valid ERC-20:
cast call <ZEN_ADDRESS> "name()(string)" --rpc-url https://horizen.calderachain.xyz/http
cast call <ZEN_ADDRESS> "symbol()(string)" --rpc-url https://horizen.calderachain.xyz/http
cast call <ZEN_ADDRESS> "decimals()(uint8)" --rpc-url https://horizen.calderachain.xyz/http
```

### Step 4: Mint/Transfer Initial ZEN Supply

Mint or transfer ZEN tokens to:
- **Protocol Pool** (will be funded after contract deployment)
- **Treasury wallet** (reserve)
- **Test wallets** (for initial testing)

---

## 5. Phase 4: Build & Upload ZK Artifacts

> The Groth16 circuit + keys are **chain-agnostic**. The same `settlement.circom` circuit, proving key, and verification key work on any EVM chain. No rebuild is needed unless you want to change circuit parameters.

### Do I Need to Rebuild?

| Scenario | Rebuild Required? |
|----------|------------------|
| Same BATCH_SIZE=256, MERKLE_DEPTH=8 | **No** — reuse existing artifacts |
| Changing circuit parameters | **Yes** — full ceremony needed |
| Upgrading circom/snarkjs version | **Yes** — regenerate all keys |
| Same circuit, different chain | **No** — artifacts are chain-agnostic |

### If Reusing Existing Artifacts (Recommended)

1. **Verify current artifacts are intact**:
```bash
cd prover
./check_artifacts.sh
```

2. **Confirm circuit hash matches**:
```bash
cat circuits/build/settlement_hashes.json
# Should show circuitHash = 0x181e1866c82c6c72f18cd61723f1f61cd0a02224250b988af5a3f32863f2b157
```

3. **Upload artifacts to production server** (if not already there):
```bash
# On prod server, ensure artifacts are synced:
cd ~/apps/reveal-market/prover
git submodule update --init --recursive
git -C artifacts lfs pull
./circuits/import_from_artifacts.sh
```

4. **Update artifact hosting URL** (if using PROVER_ARTIFACTS_URL):
   - Upload tarball to Caddy's `/srv/artifacts/` on the prod server
   - Update `PROVER_ARTIFACTS_URL` and `PROVER_ARTIFACTS_SHA256` in `.env.production`

### If Rebuilding (Only If Needed)

```bash
cd prover/circuits
./generate_keys.sh
# This takes 10-30 minutes and requires:
#   - circom 2.1.5
#   - snarkjs 0.7.4
#   - Powers of Tau PTAU file
#   - Node.js

# After generation:
./export_artifacts.sh  # Copies to prover/artifacts/ and contracts/cache/
```

---

## 6. Phase 5: Deploy Contracts to Mainnet

### Pre-Deployment Checklist

- [ ] Deployer wallet funded with ≥0.5 ETH on Horizen Mainnet
- [ ] ZEN token deployed and address known
- [ ] Oracle address generated (Phase 1, wallet #2)
- [ ] Authorization Signer address generated (Phase 1, wallet #3)
- [ ] Verification key JSON available at `contracts/cache/settlement-vk.json`
- [ ] Circuit hash known from `settlement_hashes.json`
- [ ] `EXPECTED_VERIFIER_KEY_HASH` computed (from `settlement_hashes.json`)

### Step 1: Configure Contracts .env

```bash
# contracts/zen/.env (for mainnet deploy)
RPC_URL=https://horizen.calderachain.xyz/http
CHAIN_ID=26514
PRIVATE_KEY=<REDACTED>
ZEN_TOKEN_ADDRESS=0x<MAINNET_ZEN_TOKEN_ADDRESS>
ORACLE_ADDRESS=0x<MAINNET_ORACLE_ADDRESS>
AUTHORIZATION_SIGNER=0x<MAINNET_AUTH_SIGNER_ADDRESS>
CIRCUIT_HASH=0x181e1866c82c6c72f18cd61723f1f61cd0a02224250b988af5a3f32863f2b157
SETTLEMENT_VK_PATH=../../prover/circuits/build/settlement_deploy.json
USE_STUB_VERIFIER=0
EXPECTED_CHAIN_ID=26514
```

### Step 2: Run Deployment

```bash
cd contracts/zen
./run_deploy.sh
```

The script will:
1. Validate all required env vars
2. Check RPC chain ID matches `EXPECTED_CHAIN_ID` (26514)
3. Deploy: **ProtocolPool**, **RelayerEscrow**, **RevealMarket** (implementation), **Verifier**, **MarketFactory**
4. Wire Factory ↔ Pool ↔ Escrow permissions
5. Print all deployed addresses

### Step 3: Record Deployed Addresses

After deployment, the script prints addresses like:
```
Deployer:                    0x...
Collateral token:            0x...
ProtocolPool:                0x...
RelayerEscrow:               0x...
RevealMarket implementation: 0x...
Verifier:                    0x...
MarketFactory:               0x...
```

**Record every address.** These go into environment files in Phase 6.

Broadcast artifacts will be saved to:
```
contracts/zen/broadcast/Deploy.s.sol/26514/
```

### Step 4: Verify Contracts on Explorer

```bash
# If the explorer supports verification (Blockscout/Etherscan API):
forge verify-contract <ADDRESS> src/MarketFactory.sol:MarketFactory \
  --rpc-url https://horizen.calderachain.xyz/http \
  --chain-id 26514 \
  --constructor-args $(cast abi-encode "constructor(address,address,address,address,address)" ...)
```

### Step 5: Seed Protocol Pool

> **Note**: At this point, `scripts/send_erc20.py` still has testnet defaults (updated in Phase 7). Use explicit `--rpc-url` and `--token` flags as shown below.

```bash
# Transfer initial ZEN to the Protocol Pool for liquidity:
python scripts/send_erc20.py \
  --token <ZEN_ADDRESS> \
  --to <PROTOCOL_POOL_ADDRESS> \
  --amount <INITIAL_LIQUIDITY> \
  --rpc-url https://horizen.calderachain.xyz/http \
  --private-key <FUNDING_WALLET_KEY>
```

### Step 6: Deploy Polygon Vault Contracts (If Using Hedger)

> **Skip this step** if the hedger service is not active at launch.

If using the hedger for off-chain hedging on Polymarket, you also need `BaseLpVault` and `HedgeStrategyExecutor` deployed on **Polygon mainnet** (chain ID 137):

```bash
cd contracts/polygon

# Configure .env for Polygon:
# RPC_URL=https://polygon-rpc.com
# CHAIN_ID=137
# PRIVATE_KEY=0x<HEDGER_VAULT_KEY or DEPLOYER_KEY>

forge script script/Deploy.s.sol --rpc-url https://polygon-rpc.com --broadcast --private-key $PRIVATE_KEY
```

Record the `BaseLpVault` address → this becomes `HEDGER_LP_VAULT_ADDRESS`.

### Step 7: Post-Deploy Circuit Hash Validation

```bash
# Validate the deployed Verifier's circuit hash matches your local artifacts:
cd contracts/zen
VERIFIER_ADDRESS=0x<NEW_VERIFIER> \
  RPC_URL=https://horizen.calderachain.xyz/http \
  EXPECTED_CHAIN_ID=26514 \
  ./scripts/check_circuit_hash.sh
```

### Step 8: Configure First Market Creation

Update `contracts/zen/.env` with the new deployment addresses so `create_market.sh` works:

```bash
# Add to contracts/zen/.env after deployment:
FACTORY_ADDRESS=0x<NEW_FACTORY>
VERIFIER_ADDRESS=0x<NEW_VERIFIER>
# ORACLE_ADDRESS, AUTHORIZATION_SIGNER, CIRCUIT_HASH already set from deploy step
```

---

## 7. Phase 6: Update Environment Files

### `.env.production` (on prod server)

Update **all** chain-related and address-related variables:

```bash
# ──── Chain Configuration ────
RM_ENVIRONMENT=prod
NEXT_PUBLIC_CHAIN_ID=26514
NEXT_PUBLIC_CHAIN_NAME="Horizen Mainnet"
NEXT_PUBLIC_RPC_URL=https://horizen.calderachain.xyz/http
NEXT_PUBLIC_BLOCK_EXPLORER_URL=https://horizen.explorer.caldera.xyz
RM_RPC_URL=https://horizen.calderachain.xyz/http
RM_PRICING_CHAIN_ID=26514

# ──── Relayer ────
# NOTE: The relayer uses env_prefix="RM_" (see relayer/src/relayer/config.py line 38),
# so RM_RPC_URL and RM_CHAIN_ID (set above) are already read by the relayer.
# RM_RELAYER_PRIVATE_KEY is set in the "Signer Keys" section below.
# No additional relayer-specific env vars are needed here.

# ──── Contract Addresses (from Phase 5 deployment) ────
RM_FACTORY_ADDRESS=0x<NEW_FACTORY>
RM_PROTOCOL_POOL_ADDRESS=0x<NEW_POOL>
RM_MARKET_IMPLEMENTATION_ADDRESS=0x<NEW_IMPLEMENTATION>
RM_VERIFIER_ADDRESS=0x<NEW_VERIFIER>
RM_ORACLE_ADDRESS=0x<NEW_ORACLE_ADDRESS>
ZEN_TOKEN_ADDRESS=0x<NEW_ZEN_TOKEN>
NEXT_PUBLIC_ZEN_TOKEN_ADDRESS=0x<NEW_ZEN_TOKEN>

# ──── Escrow Address (TWO env vars, same value) ────
# The relayer uses env_prefix="RM_" so it reads RM_RELAYER_ESCROW_ADDRESS (not bare RELAYER_ESCROW_ADDRESS).
# The backend (API + worker) also reads RM_RELAYER_ESCROW_ADDRESS.
# The frontend reads NEXT_PUBLIC_RELAYER_ESCROW_ADDRESS.
# NOTE: .env.production currently has a DUPLICATE RM_RELAYER_ESCROW_ADDRESS (lines 419 & 440) — clean this up.
RM_RELAYER_ESCROW_ADDRESS=0x<NEW_ESCROW>
NEXT_PUBLIC_RELAYER_ESCROW_ADDRESS=0x<NEW_ESCROW>

# ──── Signer Keys (NEW mainnet keys) ────
RM_RELAYER_PRIVATE_KEY=<REDACTED>
RM_PRICING_SIGNER_PRIVATE_KEY=<REDACTED>
RM_AUTHORIZATION_SIGNER_PRIVATE_KEY=<REDACTED>
RM_AUTHORIZATION_SIGNER=0x<NEW_MAINNET_AUTH_ADDRESS>
RM_WALLET_PRIVATE_KEY=<REDACTED>
RM_WALLET_ADDRESS=0x<NEW_MAINNET_DEPLOYER_ADDRESS>
RM_SETTLEMENT_SIGNER_PRIVATE_KEY=<REDACTED>
DEPLOYER_KEY=0x<NEW_MAINNET_DEPLOYER_KEY>

# ──── Database (fresh mainnet DB — see Phase 11) ────
RM_DATABASE_URL=postgresql+psycopg2://market_admin_mainnet:<DB_PASSWORD>@postgres:5432/reveal_market_mainnet
# RM_DATABASE_ASYNC_URL is auto-derived by converting psycopg2 → asyncpg driver.
# Only set explicitly if you need a different host/port for async connections:
# RM_DATABASE_ASYNC_URL=postgresql+asyncpg://market_admin_mainnet:<DB_PASSWORD>@postgres:5432/reveal_market_mainnet

# ──── Secrets (regenerate for mainnet) ────
RELAYER_BEARER_TOKEN=<generate-new-random-token>
RELAYER_API_BEARER_TOKEN=<generate-new-random-token>
RM_INTERNAL_API_SECRET=<generate-new-uuid>
RM_PROVER_SHARED_SECRET=<generate-new-uuid>
RELAYER_API_INTERNAL_SECRET=<generate-new-uuid>
REDIS_PASSWORD=<generate-new-password>

# ──── Circuit (unchanged if reusing) ────
PROVER_CIRCUIT_HASH=0x181e1866c82c6c72f18cd61723f1f61cd0a02224250b988af5a3f32863f2b157

# ──── Relayer Safety (set non-zero for mainnet!) ────
# Default is 0 (no check). Set to prevent relayer from running empty.
RELAYER_MIN_BALANCE_WEI=50000000000000000  # 0.05 ETH minimum

# ──── Hedger (if using Polygon vault on mainnet) ────
HEDGER_VAULT_CHAIN_ID=137
HEDGER_VAULT_RPC_URL=https://polygon-rpc.com
HEDGER_VAULT_PRIVATE_KEY=<REDACTED>
HEDGER_VAULT_SENDER_ADDRESS=0x<NEW_HEDGER_VAULT_ADDRESS>
HEDGER_LP_VAULT_ADDRESS=0x<POLYGON_LP_VAULT_ADDRESS>
HEDGER_VAULT_GAS_PRICE_GWEI=40

# ──── EIP-712 Pricing Verifying Contract ────
# Defaults to zero address; for mainnet, set to MarketFactory address
# so EIP-712 quote signatures bind to a specific contract.
RM_PRICING_VERIFYING_CONTRACT=0x<NEW_FACTORY>
```

> **Note on `.env.example` bug**: Line 330 currently sets `HEDGER_VAULT_RPC_URL` to `https://horizen-testnet.rpc.caldera.xyz/http`, but this should be a **Polygon** RPC URL since the vault is on Polygon chain. Fix this regardless of mainnet migration.

### Gas & RPC Tuning for Mainnet

On testnet, gas settings default to `None` (use node suggestion) and timeouts are generous. For mainnet with real value at stake, consider explicit configuration:

```bash
# ──── Worker: Settlement Submission ────
# If mainnet gas is volatile, set explicit gas price overrides:
RM_SETTLEMENT_GAS_PRICE_GWEI=0.001          # Horizen L3 typically has very low gas
RM_SETTLEMENT_MAX_PRIORITY_FEE_GWEI=0.001
# Optional: dedicated RPC for settlement (separate from general RM_RPC_URL for reliability):
# RM_SETTLEMENT_RPC_URL=https://horizen.calderachain.xyz/http

# ──── Worker: Lock Batches ────
RM_LOCK_BATCHES_GAS_LIMIT=800000            # Default; increase if lockBatches reverts with out-of-gas
RM_LOCK_BATCHES_GAS_PRICE_GWEI=0.001
RM_LOCK_BATCHES_MAX_PRIORITY_FEE_GWEI=0.001
# Route lockBatches through relayer instead of direct RPC (reduces key exposure):
# RM_LOCK_BATCHES_USE_RELAYER=true

# ──── Relayer: Gas & Retry Tuning ────
RELAYER_FEE_BUMP_PERCENT=0.15               # 15% fee bump on retry (default; may need tuning)
RELAYER_TX_TIMEOUT_SECONDS=120              # Default; mainnet block times may differ
RELAYER_MAX_RETRIES=3                       # Increase if mainnet is congested

# ──── RPC Client Timeout ────
RM_RPC_HTTP_TIMEOUT_SECONDS=10              # Default; increase for slow RPCs

# ──── Relayer Circuit Breaker ────
# These protect against cascading RPC failures; defaults are reasonable but review:
RELAYER_RPC_CIRCUIT_THRESHOLD=5             # Failures before tripping
RELAYER_RPC_CIRCUIT_WINDOW_SECONDS=30       # Window to count failures
RELAYER_RPC_CIRCUIT_COOLDOWN_SECONDS=30     # Cooldown before retrying
```

> **Note on `RM_LOCK_BATCHES_USE_RELAYER`**: When `false` (default), the worker submits `lockBatches` directly via RPC using the settlement signer key. When `true`, it routes through the relayer API. Using the relayer reduces key exposure (only the relayer holds the signing key) but adds a dependency. For mainnet, evaluate whether the added reliability of the relayer queue is worth the extra hop.

### Hedger: Polygon Defaults Already Correct

The hedger's `hedger/app/config.py` hardcoded defaults are already targeting **Polygon mainnet**:
- `polygon_chain_id=137` (correct)
- `polygon_rpc_url="https://polygon-rpc.com"` (correct)
- `usdc_address="0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"` (bridged USDC on Polygon, correct)
- `polymarket_exchange="0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"` (Polymarket CTF exchange, correct)

No code changes needed for the hedger — only set the env vars in `.env.production` (done above). The only bug is in `.env.example` where `HEDGER_VAULT_RPC_URL` incorrectly defaults to the Horizen testnet RPC (see note below).

### `.env.example` (update defaults for documentation)

Update all default values from testnet → mainnet so new developers see the correct chain.

### `contracts/zen/.env` (update for mainnet)

```bash
RPC_URL=https://horizen.calderachain.xyz/http
CHAIN_ID=26514
PRIVATE_KEY=<REDACTED>
ZEN_TOKEN_ADDRESS=0x<MAINNET_ZEN_TOKEN>
ORACLE_ADDRESS=0x<MAINNET_ORACLE>
AUTHORIZATION_SIGNER=0x<MAINNET_AUTH_SIGNER_ADDRESS>
CIRCUIT_HASH=0x181e1866c82c6c72f18cd61723f1f61cd0a02224250b988af5a3f32863f2b157
SETTLEMENT_VK_PATH=../../prover/circuits/build/settlement_deploy.json
USE_STUB_VERIFIER=0
```

### `frontend/.env.local` / `frontend/.env.production`

```bash
NEXT_PUBLIC_CHAIN_ID=26514
NEXT_PUBLIC_CHAIN_NAME="Horizen Mainnet"
NEXT_PUBLIC_RPC_URL=https://horizen.calderachain.xyz/http
NEXT_PUBLIC_BLOCK_EXPLORER_URL=https://horizen.explorer.caldera.xyz
NEXT_PUBLIC_ZEN_TOKEN_ADDRESS=0x<MAINNET_ZEN_TOKEN>
NEXT_PUBLIC_RELAYER_ESCROW_ADDRESS=0x<MAINNET_ESCROW>
```

---

## 8. Phase 7: Update Hardcoded Defaults in Code

These files have **hardcoded** testnet values as fallbacks. They must be updated:

### Backend

**`backend/api/app/config.py`** (lines 123, 211):
```python
# Line 123: Change default RPC URL
rpc_url: AnyUrl | None = Field(default=AnyUrl("https://horizen.calderachain.xyz/http"))

# Line 211: Change default chain ID
pricing_chain_id: int | None = Field(default=26514, ge=1, description="Chain id used for quote signatures")
```

### Frontend

**`frontend/lib/wagmi.ts`** (lines 17-20):
```typescript
const EXPECTED_CHAIN_ID = 26514;
const FALLBACK_CHAIN_NAME = "Horizen Mainnet";
const FALLBACK_RPC_URL = "https://horizen.calderachain.xyz/http";
const FALLBACK_EXPLORER = "https://horizen.explorer.caldera.xyz";
```

**`frontend/next.config.mjs`** (line ~11):
```javascript
const DEFAULT_RPC_URL = "https://horizen.calderachain.xyz/http";
```

**`frontend/components/proofs/ProofReceiptList.tsx`** (line 12):
```typescript
const explorerBase = process.env.NEXT_PUBLIC_BLOCK_EXPLORER_URL ?? "https://horizen.explorer.caldera.xyz";
```

**`frontend/components/markets/MarketDetailSidebar.tsx`** (line 99):
```typescript
process.env.NEXT_PUBLIC_BLOCK_EXPLORER_URL ?? "https://horizen.explorer.caldera.xyz"
```

### Contracts Monitoring

**`contracts/scripts/monitoring_report.py`** (line 11):
```python
RPC_URL = "https://horizen.calderachain.xyz/http"
```

### Helper Scripts

**`scripts/send_erc20.py`** (lines 34-35, 38):
```python
# Update hardcoded defaults:
DEFAULT_RPC_URL = os.getenv("NEXT_PUBLIC_RPC_URL", "https://horizen.calderachain.xyz/http")
DEFAULT_EXPLORER_URL = os.getenv("NEXT_PUBLIC_BLOCK_EXPLORER_URL", "https://horizen.explorer.caldera.xyz")
DEFAULT_TOKEN_ADDRESS = "0x<MAINNET_ZEN_TOKEN>"  # was testnet ZEN
```

**`scripts/send_to_protocol_pool.py`** (lines 36-40):
```python
# Update hardcoded defaults:
DEFAULT_RPC_URL = os.getenv("NEXT_PUBLIC_RPC_URL", "https://horizen.calderachain.xyz/http")
DEFAULT_EXPLORER_URL = os.getenv("NEXT_PUBLIC_BLOCK_EXPLORER_URL", "https://horizen.explorer.caldera.xyz")
DEFAULT_TOKEN_ADDRESS = "0x<MAINNET_ZEN_TOKEN>"  # was testnet ZEN
DEFAULT_POOL_ADDRESS = os.getenv("RM_PROTOCOL_POOL_ADDRESS", "0x<MAINNET_POOL>")  # was testnet pool
```

**`scripts/send_eth.py`** (lines 32-34):
```python
# Line 32-33 default to Base mainnet (for bridging), NOT Horizen. Update if you want
# this script to default to Horizen Mainnet for gas top-ups:
DEFAULT_RPC_URL = os.getenv("NEXT_PUBLIC_RPC_URL", "https://horizen.calderachain.xyz/http")
DEFAULT_EXPLORER_URL = os.getenv("NEXT_PUBLIC_BLOCK_EXPLORER_URL", "https://horizen.explorer.caldera.xyz")

# Line 34 references a testnet keyfile — update or remove:
DEFAULT_KEYFILE = Path(__file__).resolve().parent / "generated" / "<mainnet_funding_wallet>.txt"
```

> **Note**: `send_eth.py` currently defaults to `https://mainnet.base.org` (Base chain), which is intentional if used for Base ETH transfers. If you want it to default to Horizen Mainnet for relayer gas top-ups (referenced in Phase 14), update the defaults above. Alternatively, always pass `--rpc-url` explicitly.

**`scripts/generate_env.sh`** (lines 80, 85):
```bash
# Line 80: Change default chain ID fallback
RM_CHAIN_ID="${RM_CHAIN_ID:-26514}"

# Line 85: Change default explorer URL fallback
NEXT_PUBLIC_BLOCK_EXPLORER_URL="${NEXT_PUBLIC_BLOCK_EXPLORER_URL:-https://horizen.explorer.caldera.xyz}"
```

### E2E Test Scripts

These scripts have **hardcoded** testnet values with no env fallback. Update or parameterize them:

| File | Line(s) | Hardcoded Value |
|------|---------|-----------------|
| `scripts/e2e/lock_and_post.py` | 18-19 | RPC URL + `CHAIN_ID = 2651420` (no env override) |
| `scripts/e2e/prove_settle_claim.py` | 23-24 | RPC URL + `CHAIN_ID = 2651420` (no env override) |
| `scripts/e2e/prod_e2e_test.py` | 27 | `CHAIN_ID = 2651420` (no env override) |
| `scripts/e2e/prod_e2e_test.py` | 30-36 | Hardcoded contract addresses (no env override) |
| `scripts/e2e/utils.py` | 33-35 | RPC URL, chain ID, explorer URL (has env fallbacks) |
| `scripts/e2e/api_commit_test.py` | 52 | RPC URL (has env fallback) |

> **Note**: `lock_and_post.py` and `prove_settle_claim.py` have fully hardcoded values (no `os.getenv`). Either update the constants or refactor to use `scripts/e2e/utils.py` shared config.

**`scripts/zen_testnet_faucet.py`** — This script is **testnet-only**. Do not use on mainnet. Consider adding a guard:
```python
# At top of file:
# WARNING: TESTNET ONLY — do not use on mainnet. Will waste real ETH.
```

---

## 9. Phase 8: Update Frontend

### Native Currency Display

**`frontend/lib/wagmi.ts`** (line 56):
```typescript
// Current:
nativeCurrency: { name: "Zen", symbol: "ZEN", decimals: 18 },

// The mainnet native token is ETH (per the hub page). Update if needed:
nativeCurrency: { name: "Ether", symbol: "ETH", decimals: 18 },
```

> **Decision needed**: Horizen Mainnet's native token is ETH according to the hub. If ZEN is the collateral ERC-20 (not native), this is correct. Verify whether the native gas token should display as "Ether" or "Zen".

### CSP Headers

**`frontend/next.config.mjs`** — CSP `connect-src` RPC origins are **auto-derived** (lines 71-86) from both `NEXT_PUBLIC_RPC_URL` and `DEFAULT_RPC_URL`. Updating these two values automatically fixes CSP. **No manual CSP editing needed** as long as:
1. `DEFAULT_RPC_URL` (line 11) is updated to mainnet RPC
2. `NEXT_PUBLIC_RPC_URL` env var is set to mainnet RPC

The code extracts the origin with `new URL(rawUrl).origin` and adds it to `connect-src`. The WebSocket variant is also auto-derived via `.replace(/^http/i, "ws")` on the streamer URL.

### MetaMask "Add to Wallet" / Chain Switching

Wallet connectors will automatically use the `defineChain()` config from `wagmi.ts`. Once the chain ID and RPC are updated, MetaMask will prompt users to add the new network.

### Explorer URL Inconsistency

> **Note**: Two components use `NEXT_PUBLIC_EXPLORER_BASE_URL` instead of `NEXT_PUBLIC_BLOCK_EXPLORER_URL`:
> - `frontend/components/dashboard/DashboardClient.tsx` (line 349)
> - `frontend/components/markets/StakeQuoteCard.tsx` (line 129)
>
> Both fall back to `defaultChain.blockExplorers` from `wagmi.ts`, so updating `wagmi.ts` is sufficient — no code change needed. But be aware of the inconsistent env var name if you set `NEXT_PUBLIC_EXPLORER_BASE_URL` separately.

### WalletConnect

No changes needed — WalletConnect uses the chain config from wagmi.

---

## 10. Phase 9: Update Infrastructure

### Docker Compose

**`docker-compose.yml`** (lines 343-346) — Update **all four** hardcoded testnet defaults in frontend build args:

```yaml
# Frontend build args — ALL of these have testnet fallbacks:
args:
  NEXT_PUBLIC_CHAIN_ID: ${NEXT_PUBLIC_CHAIN_ID:-26514}
  NEXT_PUBLIC_CHAIN_NAME: ${NEXT_PUBLIC_CHAIN_NAME:-Horizen Mainnet}
  NEXT_PUBLIC_RPC_URL: ${NEXT_PUBLIC_RPC_URL:-https://horizen.calderachain.xyz/http}
  NEXT_PUBLIC_BLOCK_EXPLORER_URL: ${NEXT_PUBLIC_BLOCK_EXPLORER_URL:-https://horizen.explorer.caldera.xyz}
```

> These build args are baked into the Docker image at build time. If `.env.production` is set correctly they'll be overridden, but the fallback defaults should still be mainnet to prevent accidents.

### Docker Bake

**`docker-bake.hcl`** (lines 42-45) — Update **all four** hardcoded testnet defaults in frontend build variables:

```hcl
variable "NEXT_PUBLIC_CHAIN_ID" { default = "26514" }
variable "NEXT_PUBLIC_CHAIN_NAME" { default = "Horizen Mainnet" }
variable "NEXT_PUBLIC_RPC_URL" { default = "https://horizen.calderachain.xyz/http" }
variable "NEXT_PUBLIC_BLOCK_EXPLORER_URL" { default = "https://horizen.explorer.caldera.xyz" }
```

### Caddyfile

**`docker/caddy/Caddyfile`** — No changes needed for the Caddy config itself (domains stay `revealmarket.xyz`, `api.revealmarket.xyz`, `stream.revealmarket.xyz`).

However, verify:
- [ ] CSP headers in Caddy (if any) allow the new RPC domain
- [ ] Health check endpoints still work with the new chain

### CI/CD

**`.github/workflows/cicd.yml`** — The workflow reads **20+ GitHub repo variables** (Settings > Secrets and variables > Actions > Variables) that contain chain config and contract addresses. These must be updated for mainnet:

**Variables to update in GitHub repo settings:**
| Variable | New Value |
|----------|-----------|
| `RM_RPC_URL` | `https://horizen.calderachain.xyz/http` |
| `RM_CHAIN_ID` | `26514` |
| `RM_FACTORY_ADDRESS` | `0x<NEW_FACTORY>` |
| `RM_PROTOCOL_POOL_ADDRESS` | `0x<NEW_POOL>` |
| `RM_RELAYER_ESCROW_ADDRESS` | `0x<NEW_ESCROW>` |
| `RM_MARKET_IMPLEMENTATION_ADDRESS` | `0x<NEW_IMPLEMENTATION>` |
| `RM_VERIFIER_ADDRESS` | `0x<NEW_VERIFIER>` |
| `RM_AUTHORIZATION_SIGNER` | `0x<NEW_AUTH_SIGNER_ADDRESS>` |
| `RM_ORACLE_ADDRESS` | `0x<NEW_ORACLE_ADDRESS>` |
| `ZEN_TOKEN_ADDRESS` | `0x<NEW_ZEN_TOKEN>` |
| `RM_WALLET_ADDRESS` | `0x<NEW_DEPLOYER_ADDRESS>` |
| `PROVER_CIRCUIT_HASH` | `0x181e1866...` (unchanged if reusing artifacts) |
| `PRICING_SIGNER_ADDRESS` | `0x<NEW_PRICING_SIGNER_ADDRESS>` |
| `NEXT_PUBLIC_CHAIN_ID` | `26514` |
| `NEXT_PUBLIC_RPC_URL` | `https://horizen.calderachain.xyz/http` |
| `NEXT_PUBLIC_BLOCK_EXPLORER_URL` | `https://horizen.explorer.caldera.xyz` |

These variables are used by the circuit hash check job (lines 442-443) and the deploy job (lines 544-563).

**Recommendation**: Also add a manual approval step or environment protection rule in GitHub for mainnet deploys.

### Streamer

**`streamer/.env.example`** — Update CORS if the frontend domain changes (unlikely). Current CORS allows `revealmarket.xyz` which is fine.

### Production Server

On `159.69.29.255`:
- [ ] Update `~/apps/reveal-market/.env.production` with all mainnet values
- [ ] Ensure `~/apps/reveal-market/frontend/.env.production` is updated
- [ ] Ensure prover artifacts are synced (they don't change for mainnet)

---

## 11. Phase 10: Update Tests

Tests hardcode chain ID `2651420` for mocking. They should continue using a test chain ID, but some tests validate the actual default config.

### Files with Hardcoded `2651420` in Tests

| File | Lines | Action |
|------|-------|--------|
| `backend/api/tests/test_schema_snapshots.py` | ~190 | Update snapshot |
| `backend/api/tests/test_integration_pricing_cache.py` | 17, 63, 112 | Update mock chain ID |
| `backend/api/tests/test_pricing_submit_locking.py` | 14 | Update mock chain ID |
| `backend/api/tests/test_pricing_submit_fx_drift.py` | 22, 66 | Update mock chain ID |
| `backend/api/tests/test_pricing_endpoint.py` | 115, 142, 161, 212, 246, 286, 328, 370, 413 | Update mock chain ID |
| `backend/api/tests/test_trade_routes.py` | 60, 96, 128 | Update mock chain ID |
| `frontend/vitest.setup.tsx` | 122 | Update mock chain ID |
| `frontend/tests/wagmi-config.test.ts` | 59, 81 | Update expected chain ID |
| `frontend/tests/trade-status.test.tsx` | 8, 24 | Update mock chain ID |
| `frontend/tests/components/TradeSubmission.test.tsx` | 24, 158 | Update mock chain ID |
| `frontend/tests/components/QuoteDisplay.test.tsx` | 19 | Update mock chain ID |
| `frontend/tests/dashboard-client.test.tsx` | 10, 84 | Update mock chain ID |
| `frontend/tests/escrow-actions.test.tsx` | 9, 68 | Update mock chain ID |
| `frontend/tests/connect-wallet-button.test.tsx` | 52 | Update mock chain ID |

### Strategy

Global find-and-replace in test files:
- `2651420` → `26514`
- `horizen-testnet.rpc.caldera.xyz` → `horizen.calderachain.xyz`
- `horizen-testnet.explorer.caldera.xyz` → `horizen.explorer.caldera.xyz`

Then run full test suite to verify:
```bash
make test
```

### OpenAPI Snapshot

The OpenAPI snapshot test (`backend/api/tests/test_openapi_snapshot.py`) will need regeneration:
```bash
cd backend/api && uv run --project . --extra dev pytest tests/test_openapi_snapshot.py --snapshot-update
```

---

## 12. Phase 11: Database & State

### Fresh Database (Recommended for Mainnet Launch)

Mainnet should start with a **clean database**. Testnet data (markets, commitments, settlements) is not valid on mainnet.

1. Keep testnet DB as-is (for reference / testnet operation)
2. Create a new PostgreSQL database for mainnet:
```sql
CREATE DATABASE reveal_market_mainnet;
CREATE USER market_admin_mainnet WITH PASSWORD '<strong-password>';
GRANT ALL PRIVILEGES ON DATABASE reveal_market_mainnet TO market_admin_mainnet;
```
3. Update `RM_DATABASE_URL` in `.env.production`:
```bash
RM_DATABASE_URL=postgresql+psycopg2://market_admin_mainnet:<password>@postgres:5432/reveal_market_mainnet
```
4. `RM_DATABASE_ASYNC_URL` is **auto-derived** — the API and worker convert `psycopg2` → `asyncpg` automatically. Only set it explicitly if you need a different host/port for async connections.
5. Migrations run automatically on API startup (`RM_RUN_MIGRATIONS_ON_STARTUP=true`)

### Shared Database Architecture

All services sharing the database use `RM_DATABASE_URL`:

| Service | How it reads DB URL | Notes |
|---------|-------------------|-------|
| API | `RM_DATABASE_URL` (sync for Alembic) + auto-derived async | Runs migrations on startup |
| Worker | `RM_DATABASE_URL` + auto-derived async | Also runs migrations on startup |
| Hedger | `RM_DATABASE_URL` (alias) or `HEDGER_DATABASE_URL` (override) | Stores hedger tables in same DB |
| Relayer | `RM_DATABASE_URL` → `_queue_dsn()` strips `+psycopg2` | Uses it for PostgreSQL-backed queue |

Since all services share the same `RM_DATABASE_URL`, pointing it to the fresh mainnet database gives every service a clean slate — including the relayer's queue tables.

### Relayer Queue

The relayer queue can run on **PostgreSQL** (shared via `RM_DATABASE_URL`) or **SQLite** (fallback to `relayer_queue.db`):
- If `RM_DATABASE_URL` is set → relayer uses it for the queue (recommended for mainnet)
- If not set → falls back to local SQLite at `RELAYER_QUEUE_DB_PATH` (default: `relayer_queue.db`)
- If migrating and using SQLite: **delete the old `relayer_queue.db`** to avoid processing stale testnet transactions

### Redis

Redis cache will be repopulated automatically. No migration needed.
- Consider flushing Redis on mainnet launch to avoid stale testnet cache keys
- Update `REDIS_PASSWORD` to a new strong password
- Redis streams (e.g., `horizen_commits` used by hedger) will start empty after flush

---

## 13. Phase 12: Pre-Launch Validation

Run through this checklist **before** going live:

### Contract Verification
- [ ] All 5 contracts deployed and verified on explorer
- [ ] `MarketFactory.owner()` returns deployer address
- [ ] `ProtocolPool.marketFactory()` returns factory address
- [ ] `RelayerEscrow.marketFactory()` returns factory address
- [ ] `Verifier.circuitHash()` matches `PROVER_CIRCUIT_HASH`
- [ ] `Verifier.expectedInputs()` returns `10`
- [ ] `check_circuit_hash.sh` passes with mainnet RPC
- [ ] Protocol Pool has initial ZEN liquidity
- [ ] `RelayerEscrow` token allowance set for relayer address (if required by flow)

### End-to-End Smoke Test
- [ ] Create a test market via `create_market.sh` or backend API
- [ ] Submit a commitment (requires frontend + relayer)
- [ ] Verify commitment appears on-chain
- [ ] Resolve the market (oracle)
- [ ] Generate proof (prover)
- [ ] Submit settlement batch
- [ ] Verify payout/claim works

### Service Health
- [ ] `curl https://api.revealmarket.xyz/health` returns 200
- [ ] `curl https://stream.revealmarket.xyz/healthz` returns 200
- [ ] `curl https://revealmarket.xyz` returns 200
- [ ] API `/metrics` endpoint works
- [ ] Worker heartbeats visible in Redis
- [ ] Prover responds to proof requests

### Wallet Balances
- [ ] Relayer has sufficient ETH for gas (check: `cast balance <RELAYER> --rpc-url https://horizen.calderachain.xyz/http`)
- [ ] Settlement signer has sufficient ETH
- [ ] Oracle has sufficient ETH
- [ ] Protocol Pool has ZEN liquidity (`cast call <ZEN_TOKEN> "balanceOf(address)(uint256)" <POOL> --rpc-url ...`)
- [ ] RelayerEscrow has ZEN token allowance set (if required by commit flow)
- [ ] Hedger vault signer has MATIC/POL on Polygon (if hedger active): `cast balance <HEDGER_VAULT_ADDR> --rpc-url https://polygon-rpc.com`

---

## 14. Phase 13: Go-Live Checklist

### Deployment Order

Execute in this exact order:

1. **Backup testnet config**: `cp ~/.env.production ~/.env.production.testnet` (for rollback)
2. **Tag testnet commit**: `git tag testnet-final`
3. **Stop all services**: `make down`
4. **Flush Redis**: `docker exec reveal-market-redis redis-cli -a $REDIS_PASSWORD FLUSHALL`
   - This clears all cache, streams (`horizen_commits`), and queue data
5. **Update `.env.production`** with all mainnet values (including new secrets)
6. **Pull latest code** (with all hardcoded updates merged to `main`)
7. **Sync prover artifacts**: `git submodule update --init --recursive && git -C prover/artifacts lfs pull`
8. **Start services**: `./run_prod.sh`
9. **Verify health endpoints** (all services)
10. **Run smoke test** (create market → commit → resolve → settle)
11. **Purge Cloudflare cache**: The prod deploy script does this automatically
12. **Monitor logs** for 30+ minutes

### Pre-Cutover Verification Script

Run this on the prod server **after updating env but before starting services** to catch misconfigurations:

```bash
#!/bin/bash
set -euo pipefail

source .env.production

echo "=== Environment Validation ==="

# 1. Check for leftover testnet values
grep -c "2651420" .env.production && echo "FAIL: testnet chain ID found!" || echo "OK: no testnet chain ID"
grep -c "horizen-testnet" .env.production && echo "FAIL: testnet RPC found!" || echo "OK: no testnet RPC"

# 2. Verify both escrow address vars match
[ "$RM_RELAYER_ESCROW_ADDRESS" = "$NEXT_PUBLIC_RELAYER_ESCROW_ADDRESS" ] && \
  echo "OK: escrow addresses match" || echo "FAIL: escrow address mismatch! RM=$RM_RELAYER_ESCROW_ADDRESS vs NEXT_PUBLIC=$NEXT_PUBLIC_RELAYER_ESCROW_ADDRESS"

# 3. Verify chain ID consistency
[ "$NEXT_PUBLIC_CHAIN_ID" = "26514" ] && echo "OK: frontend chain ID" || echo "FAIL: frontend chain ID = $NEXT_PUBLIC_CHAIN_ID"
[ "$RM_CHAIN_ID" = "26514" ] && echo "OK: relayer chain ID (RM_CHAIN_ID)" || echo "FAIL: relayer chain ID = $RM_CHAIN_ID"
[ "$RM_PRICING_CHAIN_ID" = "26514" ] && echo "OK: pricing chain ID" || echo "FAIL: pricing chain ID = $RM_PRICING_CHAIN_ID"

# 3b. Verify database URL points to mainnet database
echo "$RM_DATABASE_URL" | grep -q "reveal_market_mainnet" && \
  echo "OK: database URL targets mainnet DB" || echo "WARN: database URL may point to testnet DB ($RM_DATABASE_URL)"

echo ""
echo "=== On-Chain Validation ==="

RPC="https://horizen.calderachain.xyz/http"

# 4. Verify RPC is reachable and returns expected chain ID
ACTUAL_CHAIN_ID=$(cast chain-id --rpc-url "$RPC" 2>/dev/null)
[ "$ACTUAL_CHAIN_ID" = "26514" ] && echo "OK: RPC chain ID = 26514" || echo "FAIL: RPC chain ID = $ACTUAL_CHAIN_ID"

# 5. Verify contracts exist on-chain (non-zero code)
for LABEL_ADDR in "MarketFactory:$RM_FACTORY_ADDRESS" "ProtocolPool:$RM_PROTOCOL_POOL_ADDRESS" \
  "RelayerEscrow:$RM_RELAYER_ESCROW_ADDRESS" "Verifier:$RM_VERIFIER_ADDRESS"; do
  LABEL="${LABEL_ADDR%%:*}"
  ADDR="${LABEL_ADDR##*:}"
  CODE=$(cast code "$ADDR" --rpc-url "$RPC" 2>/dev/null)
  [ "$CODE" != "0x" ] && echo "OK: $LABEL has code at $ADDR" || echo "FAIL: $LABEL has no code at $ADDR"
done

# 6. Verify wallet balances
for LABEL_KEY in "Relayer:RELAYER_PRIVATE_KEY" "Settlement:RM_SETTLEMENT_SIGNER_PRIVATE_KEY"; do
  LABEL="${LABEL_KEY%%:*}"
  KEY="${LABEL_KEY##*:}"
  ADDR=$(cast wallet address --private-key "${!KEY}" 2>/dev/null)
  BAL=$(cast balance "$ADDR" --rpc-url "$RPC" 2>/dev/null)
  echo "INFO: $LABEL ($ADDR) balance = $BAL wei"
done

# 7. Verify circuit hash matches
ONCHAIN_HASH=$(cast call "$RM_VERIFIER_ADDRESS" "circuitHash()(bytes32)" --rpc-url "$RPC" 2>/dev/null)
[ "$ONCHAIN_HASH" = "$PROVER_CIRCUIT_HASH" ] && echo "OK: circuit hash matches" || echo "FAIL: circuit hash mismatch ($ONCHAIN_HASH vs $PROVER_CIRCUIT_HASH)"

echo ""
echo "=== Verification Complete ==="
```

### DNS / Domain

No DNS changes needed — `revealmarket.xyz` and subdomains stay the same. The chain underneath just changes from testnet to mainnet.

### Communication

- [ ] Update any public docs that mention "testnet"
- [ ] Update `MVP.md`, `AGENTS.md`, `MVP.md` references to chain ID / RPC
- [ ] Remove or update `CLAUDE.md` "Default chain" line:
  ```
  - **Default chain**: Horizen Mainnet, chain ID `26514`, RPC `https://horizen.calderachain.xyz/http`
  ```

---

## 15. Phase 14: Post-Launch Monitoring

### First 24 Hours
- [ ] Monitor relayer wallet ETH balance (alert if < 0.05 ETH): `cast balance <RELAYER> --rpc-url https://horizen.calderachain.xyz/http`
- [ ] Monitor settlement signer ETH balance
- [ ] Check for failed transactions on explorer
- [ ] Monitor API error rates via `/metrics`
- [ ] Monitor Redis memory usage
- [ ] Check worker batch processing logs
- [ ] Verify `RELAYER_MIN_BALANCE_WEI` is triggering warnings (check relayer logs)
- [ ] Confirm no services are logging testnet RPC URLs (grep docker logs)
- [ ] Check Docker container memory usage against limits: `docker stats`

### Ongoing
- [ ] Set up balance monitoring alerts (Prometheus + Grafana or simple cron script)
- [ ] Set up transaction failure alerts
- [ ] Implement automatic gas top-up for relayer (via funding wallet + `scripts/send_eth.py --rpc-url https://horizen.calderachain.xyz/http`)
- [ ] Regular ZEN liquidity monitoring for Protocol Pool
- [ ] Monitor hedger Polygon wallet balance (if hedger active)
- [ ] Weekly review of Docker resource utilization — scale up if hitting limits

---

## Appendix A: Rollback Plan

If mainnet launch encounters critical issues, you can revert to testnet operation:

### Quick Rollback (< 5 minutes)

1. On prod server, swap `.env.production` back to testnet values (keep a backup copy):
   ```bash
   cp ~/apps/reveal-market/.env.production ~/apps/reveal-market/.env.production.mainnet
   cp ~/apps/reveal-market/.env.production.testnet ~/apps/reveal-market/.env.production
   ```
2. Restart services: `./run_prod.sh`
3. Purge Cloudflare cache

### Code Rollback

If hardcoded defaults were already merged to `main`:
```bash
git revert <mainnet-migration-commit>
# or
git checkout <last-testnet-commit> -- backend/api/app/config.py frontend/lib/wagmi.ts frontend/next.config.mjs ...
```

### Preparation Before Go-Live

- [ ] Save a copy of `.env.production` as `.env.production.testnet` before updating
- [ ] Tag the last testnet commit: `git tag testnet-final`
- [ ] Keep the testnet database intact (don't drop it)

---

## Appendix B: Testnet Preservation

### Option 1: Kill Testnet (Simple)

Testnet contracts stay deployed on-chain forever but services stop serving testnet data. Simplest approach.

### Option 2: Parallel Testnet (For Continued Development)

If you want to keep testnet running alongside mainnet for staging/QA:

1. **Separate server** or **separate Docker Compose project** with testnet `.env`
2. Separate database (the current one)
3. Separate Redis instance
4. Different subdomains (e.g., `testnet.revealmarket.xyz`, `testnet-api.revealmarket.xyz`)
5. Separate Caddy config with separate TLS

This is significant infrastructure work. **Recommendation**: Use testnet for CI/CD integration tests only (not as a public service).

---

## Appendix C: EIP-712 Domain Separator Impact

Changing the chain ID from `2651420` to `26514` **invalidates all existing EIP-712 signatures**. This affects:

- **Pricing quotes**: `QUOTE_V1` signatures include `chainId` in the EIP-712 domain. All in-flight quotes become invalid at cutover. This is fine — new quotes are signed with the new chain ID.
- **Commit authorizations**: Same EIP-712 domain dependency. Any pending commit-auth signatures become invalid.
- **Frontend**: Users must reconnect their wallets. MetaMask will prompt to add the new chain.

**No migration needed** — this is a clean break. But schedule the cutover during low-traffic hours to minimize disruption to active users.

---

## Appendix D: Docker Resource Limits Review

Current docker-compose resource limits are tuned for testnet traffic. Review for mainnet:

| Service | Current Limit | Mainnet Recommendation | Notes |
|---------|--------------|----------------------|-------|
| API | 1 CPU, 512M | 2 CPU, 1G | Higher request volume |
| Worker | 2 CPU, 4G | 2 CPU, 4G | Already generous (proof building) |
| Frontend | 1 CPU, 256M | 1 CPU, 512M | SSR under load |
| Relayer | 0.5 CPU, 384M | 1 CPU, 512M | Burst transaction volume |
| Hedger | 1 CPU, 512M | 1 CPU, 512M | OK as-is |
| Prover | 4 CPU, 8G | 4 CPU, 8G | CPU-bound proof generation |
| Streamer | — | — | Standalone compose |
| Postgres | — | — | Consider dedicated instance |

Adjust in `docker-compose.yml` and/or `docker-compose.prod.yml` `deploy.resources` blocks.

---

## Appendix E: Files to Change (Complete)

### Source Code (hardcoded defaults)

| File | What to Change |
|------|---------------|
| `backend/api/app/config.py` | Default RPC URL (line 123), default chain ID (line 211), `pricing_verifying_contract` zero addr (line 212) |
| `frontend/lib/wagmi.ts` | `EXPECTED_CHAIN_ID`, `FALLBACK_CHAIN_NAME`, `FALLBACK_RPC_URL`, `FALLBACK_EXPLORER`, `nativeCurrency` |
| `frontend/next.config.mjs` | `DEFAULT_RPC_URL` (line 11) |
| `frontend/components/proofs/ProofReceiptList.tsx` | Explorer fallback URL (line 12) |
| `frontend/components/markets/MarketDetailSidebar.tsx` | Explorer fallback URL (line 99) |
| `contracts/scripts/monitoring_report.py` | Hardcoded RPC URL (line 11) |
| `scripts/send_erc20.py` | Default RPC URL, explorer URL, token address (lines 34-38) |
| `scripts/send_to_protocol_pool.py` | Default RPC URL, explorer URL, token address, pool address (lines 36-40) |
| `scripts/send_eth.py` | Default RPC URL, explorer URL, keyfile path (lines 32-34) — currently defaults to Base mainnet; update if used for Horizen gas top-ups |
| `scripts/generate_env.sh` | Default chain ID fallback (line 80), default explorer URL fallback (line 85) |
| `scripts/e2e/lock_and_post.py` | Hardcoded RPC URL + chain ID (lines 18-19, no env override) |
| `scripts/e2e/prove_settle_claim.py` | Hardcoded RPC URL + chain ID (lines 23-24, no env override) |
| `scripts/e2e/prod_e2e_test.py` | Hardcoded chain ID (line 27) + contract addresses (lines 30-36, no env override) |
| `scripts/e2e/utils.py` | RPC URL, chain ID, explorer URL defaults (lines 33-35, has env fallbacks) |

### Environment Files

| File | What to Change |
|------|---------------|
| `.env.production` | All chain, address, key, secret, and **database** values (`RM_DATABASE_URL`) |
| `.env.example` | Default chain ID, RPC, explorer, contract addresses |
| `.env.local` | All chain, address, key values (for local dev against mainnet) |
| `contracts/zen/.env` | RPC, chain ID, deployer key, token address, oracle, signer |
| `contracts/zen/.env.example` | Default RPC and chain ID |
| `frontend/.env.local` | Chain ID, RPC, explorer, token addresses |
| `frontend/.env.production` | Chain ID, RPC, explorer, token addresses |
| `streamer/.env.example` | CORS origins (if domain changes) |

### Docker / Infra

| File | What to Change |
|------|---------------|
| `docker-compose.yml` | Default `NEXT_PUBLIC_CHAIN_ID`, `NEXT_PUBLIC_CHAIN_NAME`, `NEXT_PUBLIC_RPC_URL`, `NEXT_PUBLIC_BLOCK_EXPLORER_URL` build args (lines 343-346) |
| `docker-bake.hcl` | Default `NEXT_PUBLIC_CHAIN_ID`, `NEXT_PUBLIC_CHAIN_NAME`, `NEXT_PUBLIC_RPC_URL`, `NEXT_PUBLIC_BLOCK_EXPLORER_URL` variables (lines 42-45) |
| `docker-compose.yml` | Review `deploy.resources` limits for mainnet traffic (see Appendix D) |

### Tests (chain ID + RPC mocks)

| File | What to Change |
|------|---------------|
| `backend/api/tests/test_schema_snapshots.py` | Snapshot chain ID |
| `backend/api/tests/test_integration_pricing_cache.py` | Mock chain ID |
| `backend/api/tests/test_pricing_submit_locking.py` | Mock chain ID |
| `backend/api/tests/test_pricing_submit_fx_drift.py` | Mock chain ID |
| `backend/api/tests/test_pricing_endpoint.py` | Mock chain ID (9 occurrences) |
| `backend/api/tests/test_trade_routes.py` | Mock chain ID |
| `frontend/vitest.setup.tsx` | Mock chain ID |
| `frontend/tests/wagmi-config.test.ts` | Expected chain ID + URLs |
| `frontend/tests/trade-status.test.tsx` | Mock chain ID + URLs |
| `frontend/tests/components/TradeSubmission.test.tsx` | Mock chain ID + URLs |
| `frontend/tests/components/QuoteDisplay.test.tsx` | Mock chain ID |
| `frontend/tests/dashboard-client.test.tsx` | Mock chain ID + URLs |
| `frontend/tests/escrow-actions.test.tsx` | Mock chain ID + URLs |
| `frontend/tests/connect-wallet-button.test.tsx` | Mock chain ID |

### Documentation

| File | What to Change |
|------|---------------|
| `CLAUDE.md` | Default chain reference |
| `MVP.md` | Chain ID + RPC references |
| `AGENTS.md` | Chain ID reference |
| `MVP.md` | Chain ID + RPC references |
| `scripts/e2e/DEPLOYMENT_GUIDE.md` | Testnet chain ID, RPC URLs, contract addresses throughout |

---

## Appendix F: Address Inventory

### Testnet Addresses (RETIRING)

| Role | Address | Status |
|------|---------|--------|
| Deployer/Owner | `0x65CeDe1252B614ae9fb05e5620EBCbC471DF1627` | Retire |
| Oracle | `0x0F3d0f9274fA6AAEEbc493EdD44d2979BD75F369` | Retire |
| Auth Signer | `0x38C57472479fe7bB4C87e7A4BB23c7AAf10595Fd` | Retire |
| Relayer | `0xdAdEbecf077cdA5f86F60a91f76B238F675204f9` | Retire |
| Settlement Signer | (derived from key) | Retire |
| ZEN Token | `0x070040A826B586b58569750ED43cb5979b171e8d` | Retire |
| Market Factory | `0x5163c0CB206e7b69fFB15D9E9b52f24B4B189F77` | Retire (latest deploy 2026-03-03) |
| Protocol Pool | `0xcBa9935a4E529883e5577ab525Bc4B7B4066f84C` | Retire (latest deploy 2026-03-03) |
| Relayer Escrow | `0x494464c34AaC52E48461D5926C8CeE608f4e3ad8` | Retire (latest deploy 2026-03-03) |
| Market Implementation | `0x1b4e51854A2124B9C2965B1f32A140a06D5A467e` | Retire (latest deploy 2026-03-03) |
| Verifier | `0x590730be9D051994dCc8A91B42E92D5770e7B8f6` | Retire (latest deploy 2026-03-03) |

### Mainnet Addresses (TO BE GENERATED)

| Role | Chain | Address | Private Key Location |
|------|-------|---------|---------------------|
| Deployer/Owner | Horizen | `0x________________` | Secure vault / hardware wallet |
| Oracle | Horizen | `0x________________` | Secure vault |
| Auth Signer | Horizen | `0x________________` | `.env.production` on server |
| Relayer | Horizen | `0x________________` | `.env.production` on server |
| Settlement Signer | Horizen | `0x________________` | `.env.production` on server |
| Funding / Treasury | Horizen | `0x________________` | Hardware wallet (cold storage) |
| Hedger Vault Signer | Polygon | `0x________________` | `.env.production` on server |
| ZEN Token | Horizen | `0x________________` | N/A (contract address) |
| Market Factory | Horizen | `0x________________` | N/A (contract address) |
| Protocol Pool | Horizen | `0x________________` | N/A (contract address) |
| Relayer Escrow | Horizen | `0x________________` | N/A (contract address) |
| Market Implementation | Horizen | `0x________________` | N/A (contract address) |
| Verifier | Horizen | `0x________________` | N/A (contract address) |
| BaseLpVault | Polygon | `0x________________` | N/A (contract address, if hedger active) |

---

## Appendix G: Risk Matrix

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Reusing testnet private keys | **Critical** — keys may be compromised from testnet exposure | Generate all-new keys (Phase 1) |
| Wrong chain ID in config | **High** — transactions go to wrong chain | `Deploy.s.sol` validates `EXPECTED_CHAIN_ID` at deploy time |
| Insufficient gas funding | **High** — relayer/settlement txns fail silently | Fund generously; set `RELAYER_MIN_BALANCE_WEI`; set up balance alerts |
| Circuit hash mismatch | **Critical** — proofs rejected on-chain | `Deploy.s.sol` validates circuit hash match; run `check_circuit_hash.sh` post-deploy |
| Stale testnet data in DB | **Medium** — confusing UI, broken references | Use fresh database for mainnet |
| Stale Redis cache | **Low** — stale prices shown briefly | Flush Redis on launch |
| CSP blocks new RPC domain | **Medium** — frontend can't connect to chain | CSP auto-derived from `DEFAULT_RPC_URL` + `NEXT_PUBLIC_RPC_URL` (no manual edit) |
| Explorer URL wrong | **Low** — broken "view on explorer" links | Verify explorer URL from hub.horizen.io |
| Hardcoded testnet value missed | **Medium** — one service talks to testnet | Full `grep -r "2651420"` and `grep -r "horizen-testnet"` before launch |
| Bridge delay / failure | **Medium** — funding wallets takes time | Bridge funds well in advance of launch |
| Escrow address mismatch | **High** — relayer can't interact with escrow | Set both `RM_RELAYER_ESCROW_ADDRESS` and `NEXT_PUBLIC_RELAYER_ESCROW_ADDRESS` to the same value. **Pre-existing bug**: `.env.production` currently has mismatched values (`0x5b0fA476...` vs `0x494464c3...`) — fix before migration. Also clean up duplicate `RM_RELAYER_ESCROW_ADDRESS` entries (lines 419 & 440). |
| EIP-712 signature replay | **Low** — old testnet quotes replayed on mainnet | Chain ID in domain separator prevents cross-chain replay (see Appendix C) |
| `HEDGER_VAULT_RPC_URL` bug | **Medium** — hedger sends Polygon txns to Horizen RPC | Fix `.env.example` line 330 to use Polygon RPC (pre-existing bug) |
| Docker resource exhaustion | **Medium** — OOM kills under mainnet load | Review and bump resource limits (see Appendix D) |
| No rollback plan | **High** — stuck on broken mainnet config | Prepare `.env.production.testnet` backup before cutover (see Appendix A) |
| Secrets reused from testnet | **Medium** — bearer tokens/API secrets exposed | Regenerate all service-to-service secrets (Phase 1 secret generation) |
| Gas settings untuned | **Medium** — settlement/lock txns fail or overpay | Review and set explicit gas prices in `.env.production` (Phase 6 gas tuning section) |
| `send_eth.py` defaults to Base | **Low** — gas top-up script hits wrong chain | Pass `--rpc-url` explicitly or update defaults (Phase 7) |
| Settlement RPC single-point-of-failure | **Medium** — one RPC outage blocks all settlements | Consider `RM_SETTLEMENT_RPC_URL` with a separate provider |
| Stale relayer SQLite queue | **Low** — relayer replays testnet txns | Delete `relayer_queue.db` if using SQLite fallback (N/A if using PostgreSQL) |

---

## Summary: Execution Order

```
Phase 1  → Generate 7 mainnet wallets + secrets     (30 min)
Phase 2  → Bridge ~2 ETH to Horizen Mainnet         (1-2 hours, bridge confirmation time)
Phase 3  → Deploy ZEN token (if needed)              (30 min)
Phase 4  → Verify ZK artifacts (no rebuild needed)   (15 min)
Phase 5  → Deploy contracts to mainnet               (1 hour)
           ├── 5 contracts on Horizen
           ├── Polygon vault contracts (if hedger)
           ├── Run check_circuit_hash.sh
           └── Configure create_market.sh
Phase 6  → Update all .env files                     (1 hour)
Phase 7  → Update hardcoded defaults in code         (1 hour)
           ├── 2 backend files
           ├── 4 frontend files
           ├── 1 contracts monitoring script
           └── 3 helper scripts (send_erc20, send_to_protocol_pool, send_eth)
Phase 8  → Update frontend chain config              (30 min)
Phase 9  → Update infrastructure configs             (30 min)
           └── docker-compose.yml (4 build arg defaults)
Phase 10 → Update tests + run full suite             (1-2 hours)
Phase 11 → Fresh database setup                      (30 min)
Phase 12 → Pre-launch validation                     (2 hours)
Phase 13 → Go live                                   (1 hour)
           ├── Backup testnet config
           ├── Tag testnet-final
           ├── Flush Redis
           ├── Swap env + start services
           └── Run verification script
Phase 14 → Post-launch monitoring                    (ongoing)
```
