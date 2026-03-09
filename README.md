# How Reveal Market Works

**Predict. Prove. Get paid. No trust required.**

Reveal Market is a prediction market platform where every payout is mathematically verified on-chain using zero-knowledge proofs. No operator can rig the outcome. No middleman holds your funds. Just transparent, provably fair markets.

---

## The User Journey

### 1. Place Your Bet (Commit)

You pick a side — **Yes** or **No** — and stake your ZEN tokens. Behind the scenes, your bet is sealed using [Poseidon hashing](https://www.poseidon-hash.info/) — a cryptographic commitment scheme purpose-built for zero-knowledge circuits. Think of it as putting your answer in a tamper-proof envelope that only math can open.

Your commitment is recorded on-chain. Nobody — not even us — can see or change it. The amount you stake goes into a shared escrow smart contract, not a company wallet.

### 2. Market Closes (Lock)

When the deadline hits, the market locks. All bets are frozen on-chain. No more entries, no edits, no takebacks.

Commitments are organized into batches and sealed with a **Merkle root** — a single cryptographic fingerprint that represents every bet in the batch. This root is stored on-chain, creating an immutable snapshot of the entire market state.

### 3. Result Posted (Resolution)

The real-world outcome is resolved. Did the event happen or not? An oracle posts the answer directly to the smart contract for everyone to see and verify.

The result is final and transparent — written to the blockchain, not decided behind closed doors.

### 4. Zero-Knowledge Proof (Verification)

This is where Reveal Market is fundamentally different.

A **Groth16 zero-knowledge proof** is generated — a mathematical guarantee that every payout was calculated correctly. The proof is generated off-chain using the full bet data, but it can be verified on-chain in a single, cheap transaction. It proves:

- Every bet in the Merkle tree was included and counted
- The winning and losing pools were tallied correctly
- Every individual payout follows the exact pari-mutuel rules
- The rake was applied fairly and consistently
- Nothing was added, removed, or tampered with

**The smart contract verifies this proof on-chain.** If even a single number is off — one wei, one bet, one rounding error — the proof fails and the settlement is rejected. No human judgment, no appeals process, no trust assumptions. Just math.

### 5. Settlement

Once the proof passes on-chain verification, the smart contract transitions to **Settled**. The market outcome is now cryptographically finalized. Funds are unlocked and ready to distribute.

This happens automatically. No manual review. No waiting period. No operator approval.

### 6. Claim Your Winnings (Payout)

Winners receive their payout automatically. The relayer submits the claim transaction on your behalf — you don't need to pay gas, sign anything, or even be online. Your winnings land in your escrow balance, ready to withdraw or stake on the next market.

Losers? Their stake goes to the winners. That's how prediction markets work.

---

## Why It Matters

| | Traditional Platforms | Reveal Market |
|---|---|---|
| **Trust** | Trust the operator to pay you | Smart contract guarantees payout |
| **Transparency** | Opaque payout calculations | ZK proof verifies every calculation on-chain |
| **Speed** | Can take days to settle | Settles in minutes after resolution |
| **Cost** | You pay gas to claim | Relayer claims for you, gasless |
| **Custody** | Platform holds and controls funds | Funds locked in smart contract, not a company wallet |
| **Fairness** | "Trust us" | Mathematically proven, publicly verifiable |

---

## The Technical Edge

Reveal Market combines three cryptographic primitives into a single, seamless user experience:

- **Poseidon Hash Commitments** — Bets are committed using ZK-friendly hashing, enabling private inputs with public verifiability.
- **Merkle Tree Batching** — Hundreds of bets are compressed into a single on-chain root, making the system scalable without sacrificing verifiability.
- **Groth16 ZK-SNARKs** — Settlement proofs are generated off-chain and verified on-chain in constant time, regardless of how many bets were placed.

The result: a prediction market where the entire payout calculation is provably correct, settlement is automatic, and no single party — including us — can manipulate the outcome.

---

**In one sentence:** You bet, the market closes, a zero-knowledge proof mathematically guarantees every payout is correct, and winners get paid automatically — no trust required.

---

# Reveal Market — Developer Reference

Reveal Market is a commit-and-reveal prediction market platform with on-chain settlement, off-chain ingestion, ZK proof generation, and a Next.js frontend.

## Services

| Service | Language | Role |
|---------|----------|------|
| [`backend/api`](backend/api/README.md) | Python/FastAPI | Market data REST API, pricing quotes, trade commit/claim, internal ingestion |
| [`backend/worker`](backend/worker/README.md) | Python/asyncio | Polymarket ingestion, settlement orchestration, proof queue, cache hydration |
| [`backend/shared`](backend/README.md) | Python | SQLAlchemy models, Redis cache helpers, Poseidon hashing, on-chain utilities |
| [`streamer`](streamer/README.md) | Python/FastAPI | SSE/WebSocket server for Polymarket CLOB and Binance FX feeds |
| [`relayer`](relayer/README.md) | Python/FastAPI | On-chain transaction queue (commit/claim/lock batches) |
| [`hedger`](hedger/README.md) | Python/FastAPI | Exposure/risk tracking, treasury snapshots, settlement orchestration |
| [`frontend`](frontend/README.md) | Next.js 15/TS | Marketing site + app UI (App Router) |
| [`prover`](prover/README.md) | Go | Groth16 ZK proof generation using Circom artifacts and rapidsnark |
| [`contracts/zen`](contracts/zen/README.md) | Solidity/Foundry | RevealMarket, MarketFactory, ProtocolPool, RelayerEscrow, Verifier |
| [`contracts/polygon`](contracts/polygon/README.md) | Solidity/Foundry | BaseLpVault, HedgeStrategyExecutor |

## Quick Start

```bash
# Local dev stack (BuildKit cached)
./run_local.sh

# Production-like detached stack
./run_prod.sh

# Individual services via make
make api        # postgres + redis + API
make worker     # postgres + redis + worker
make stack      # postgres + redis + api + worker + frontend
make all        # all services
make down       # stop everything
```

## Settlement Architecture

Commitments use **Poseidon hashing** (BN254) with `BATCH_SIZE=256` and `MERKLE_DEPTH=8`. These constants must stay aligned across contracts, prover, backend, and relayer.

Flow: commit on-chain → worker builds batch Merkle root → `lockBatches` → prover generates Groth16 proof → `verifyAndSettleBatched` (or `verifyAndSettle` for single-batch markets) → relayer enqueues claim.

## Key Environment Variables

| Variable | Used by | Purpose |
|----------|---------|---------|
| `RM_DATABASE_URL` | api, worker | PostgreSQL connection (psycopg2, Alembic migrations) |
| `RM_DATABASE_ASYNC_URL` | api, worker | PostgreSQL async connection (asyncpg, runtime) |
| `RM_REDIS_URL` | api, worker | Redis connection |
| `RM_RPC_URL` | api, worker | EVM RPC endpoint (default: Horizen Testnet) |
| `RM_SETTLEMENT_SIGNER_PRIVATE_KEY` | worker | Oracle account for settlement transactions |
| `RM_PRICING_SIGNER_PRIVATE_KEY` | api | Signs QUOTE_V1 EIP-712 digests |
| `RM_INTERNAL_API_SECRET` | api | Required header `X-Internal-Secret` for `/internal/*` routes |
| `RM_RELAYER_BASE_URL` | api, worker | Relayer service URL |
| `RM_RELAYER_BEARER_TOKEN` | api, worker | Auth token for relayer writes |
| `RM_HEDGER_BASE_URL` | api | Hedger service URL for post-commit hedging |
| `RM_HEDGER_INTERNAL_SECRET` | api | Hedger admin endpoint secret |
| `RM_PROVER_BASE_URL` | worker | Prover service URL |
| `PROVER_CIRCUIT_HASH` | api, worker | 0x-prefixed 32-byte circuit hash (required at startup) |
| `STREAMER_ACCESS_TOKEN` | streamer | Optional bearer token for streamer private access |
| `NEXT_PUBLIC_API_BASE_URL` | frontend | Backend API base URL |
| `NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID` | frontend | WalletConnect project ID |

See `.env.example` (500+ lines) for the full list.

## Public vs Internal Endpoints

- Internal hooks live under `/internal/*` and require `X-Internal-Secret`.
- The Caddy edge blocks `/internal/*` by default.
- Services communicate with each other on the Docker network using internal hostnames.

## Tests

```bash
make format          # ruff + mypy + gofmt + forge gas snapshots
make test            # full sequential suite (all services)
make test-backend    # backend/run_tests.sh (API + shared + worker + mypy)
```

## Repository Layout

| Directory | Description |
|-----------|-------------|
| [`backend/`](backend/README.md) | API + worker + shared models + migrations |
| [`streamer/`](streamer/README.md) | Price/data streamer |
| [`relayer/`](relayer/README.md) | On-chain transaction submitter |
| [`hedger/`](hedger/README.md) | Exposure/risk service |
| [`frontend/`](frontend/README.md) | Next.js marketing and app UI |
| [`contracts/`](contracts/README.md) | Foundry workspaces (zen, polygon) |
| [`prover/`](prover/README.md) | Go Groth16 prover |
| `scripts/` | E2E and utility scripts |

## Infrastructure Notes

**Default chain:** Horizen Testnet, chain ID `2651420`, RPC `https://horizen-testnet.rpc.caldera.xyz/http`

**IPv6 (production Docker):** The prod compose enables IPv6 on the `reveal-market-prod` bridge. Host requirements: Docker daemon IPv6 enabled, IPv6 forwarding/proxy NDP sysctls, and `ndppd` proxying the Docker IPv6 subnet to `eth0`.

**Database drivers:** `RM_DATABASE_URL` (psycopg2, Alembic) and `RM_DATABASE_ASYNC_URL` (asyncpg, runtime). The API runs migrations on startup when `RM_RUN_MIGRATIONS_ON_STARTUP=true`.

**Security headers:** Both the API (`app/security.py`) and frontend (`next.config.mjs`) enforce CSP, HSTS, COOP, CORP, Referrer-Policy, and Permissions-Policy. Whitelist new external domains in both places before referencing them.

**Post-commit hedging:** After a commit tx is mined, the relayer pushes to `POST /internal/commitments/sync`. The API records the commitment and dispatches a hedger call. Hedge failures are logged and queued for retry via `hedger_queue_loop`.
