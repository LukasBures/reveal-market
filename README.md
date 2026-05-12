# Reveal Market

## The Problem with Prediction Markets

Prediction markets are one of the most powerful tools for aggregating information and forecasting real-world outcomes — from election results and sports scores to macroeconomic indicators and crypto prices. The idea is simple: let anyone bet on what they believe will happen, and the market's collective intelligence surfaces the most accurate probability. The problem has always been trust. Traditional prediction market platforms are centralized businesses: they hold your funds, calculate your payouts, and decide when — or whether — to pay you. Even the most reputable platforms can freeze withdrawals, manipulate resolution, quietly adjust payout rules, or simply go insolvent. Decentralized alternatives have tried to solve this through governance tokens and community arbitration, but these approaches introduce new attack surfaces: oracle manipulation, governance capture, and slow dispute resolution that leaves users in limbo for days. Reveal Market takes a fundamentally different approach. When you place a bet, your funds go directly into a non-custodial smart contract deployed on the Horizen blockchain — not into a company wallet, not into a multisig controlled by the team, but into immutable on-chain code that no one can modify or access without following the exact rules encoded at deployment. The platform operates in a pari-mutuel model: all stakes on a given market are pooled together, and winners split the losing pool proportionally to their stake. There is no house edge in the traditional sense — the protocol takes only a transparent, pre-disclosed rake that is provably applied to every settlement. From the moment you commit a bet to the moment you claim your winnings, every step is governed by cryptographic rules enforced by code, not by a company's good intentions.

## Zero-Knowledge Proof Settlement — Trustless by Mathematics

What truly sets Reveal Market apart — and what makes it technically unprecedented among deployed prediction market platforms — is its use of zero-knowledge proofs at the settlement layer. When a market closes, all bets are organized into batches of up to 256 commitments each, compressed into a Merkle tree, and a single 32-byte Merkle root — a cryptographic fingerprint of every bet in the batch — is written to the smart contract. When the real-world outcome is known and posted on-chain by an oracle, a Groth16 ZK-SNARK proof is generated off-chain using the full plaintext bet data. This proof is a compact mathematical certificate — less than a kilobyte — that encodes an irrefutable guarantee: every commitment in the Merkle tree was opened correctly, every bet was assigned to the right outcome bucket, the winning pool and losing pool were tallied with exact arithmetic, pari-mutuel payouts were calculated correctly for every single participant, the protocol rake was applied uniformly, and the total liability matches the total payout claimed. Critically, generating this proof requires knowing every individual bet — but verifying it on-chain costs a fixed, cheap amount of gas regardless of how many bets were in the market. The smart contract's Verifier contract checks this proof in a single on-chain transaction: if the proof is valid, the market transitions to Settled and funds are unlocked; if even a single wei is miscalculated, if even one bet is omitted, the proof cryptographically fails and settlement is rejected entirely. There is no manual review step, no appeals process, no admin override. A flawed settlement is mathematically impossible to finalize — not just against the rules, but provably unacceptable to the chain itself. This is what "trustless" actually means in practice: not "we promise we're honest," but "dishonesty is computationally infeasible."

## Privacy by Design, Scalability by Architecture

The privacy architecture is equally deliberate. In a naive on-chain prediction market, every bet is publicly visible the moment it is placed — which means sophisticated actors can monitor the orderbook, spot large positions, and place opposing bets to exploit the information asymmetry. Reveal Market solves this with a commit-and-reveal scheme powered by Poseidon hashing, a hash function specifically designed to be efficient inside zero-knowledge circuits. When you place a bet, your outcome choice, stake amount, and a secret salt are combined and hashed using Poseidon — the resulting hash is all that is recorded on-chain at commit time. Your actual position is invisible to everyone, including the platform, until after the market locks. After the deadline passes, no new bets can be added, and the reveal phase begins: the full bet data is used to generate the ZK proof, but this data never needs to appear on-chain in plaintext. The Merkle tree batching layer adds scalability on top of this privacy: hundreds of individual private commitments are compressed into a single on-chain root, keeping L2 storage costs minimal while preserving full verifiability. The entire stack — Poseidon commitments, Merkle batching, and Groth16 settlement proofs — is deployed on Horizen's EVM-compatible Layer 2, which offers Ethereum-level security guarantees at a fraction of the gas cost, making the platform accessible to everyday users rather than only to whales who can absorb high transaction fees. For investors evaluating the space, Reveal Market represents a rare combination: a live, deployed system with genuinely novel cryptographic infrastructure, a non-custodial model that removes counterparty risk entirely, and a user experience that abstracts all of this complexity behind a clean interface where you simply predict, wait, and claim.

---

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

Winners claim their payout through the dashboard. Click "Prepare to claim" to load your Merkle proof data, then click "Claim" to submit the on-chain transaction. Your winnings are sent directly to your wallet as a ZEN token transfer — no intermediary, no escrow, no withdrawal step.

Losers? Their stake goes to the winners. That's how prediction markets work.

---

## Why It Matters

| | Traditional Platforms | Reveal Market |
|---|---|---|
| **Trust** | Trust the operator to pay you | Smart contract guarantees payout |
| **Transparency** | Opaque payout calculations | ZK proof verifies every calculation on-chain |
| **Speed** | Can take days to settle | Settles in minutes after resolution |
| **Cost** | High L1 gas fees | Low gas on Horizen L2 |
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

**In one sentence:** You bet, the market closes, a zero-knowledge proof mathematically guarantees every payout is correct, and winners claim their payout directly to their wallet — no trust required.

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

Flow: commit on-chain → worker builds batch Merkle root → `lockBatches` → prover generates Groth16 proof → `verifyAndSettleBatched` (or `verifyAndSettle` for single-batch markets) → user claims payout via dashboard.

## Key Environment Variables

| Variable | Used by | Purpose |
|----------|---------|---------|
| `RM_DATABASE_URL` | api, worker | PostgreSQL connection (psycopg2, Alembic migrations) |
| `RM_DATABASE_ASYNC_URL` | api, worker | PostgreSQL async connection (asyncpg, runtime) |
| `RM_REDIS_URL` | api, worker | Redis connection |
| `RM_RPC_URL` | api, worker | EVM RPC endpoint (default: Horizen Mainnet) |
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

**Default chain:** Horizen Mainnet, chain ID `26514`, RPC `https://horizen.calderachain.xyz/http`

**IPv6 (production Docker):** The prod compose enables IPv6 on the `reveal-market-prod` bridge. Host requirements: Docker daemon IPv6 enabled, IPv6 forwarding/proxy NDP sysctls, and `ndppd` proxying the Docker IPv6 subnet to `eth0`.

**Database drivers:** `RM_DATABASE_URL` (psycopg2, Alembic) and `RM_DATABASE_ASYNC_URL` (asyncpg, runtime). The API runs migrations on startup when `RM_RUN_MIGRATIONS_ON_STARTUP=true`.

**Security headers:** Both the API (`app/security.py`) and frontend (`next.config.mjs`) enforce CSP, HSTS, COOP, CORP, Referrer-Policy, and Permissions-Policy. Whitelist new external domains in both places before referencing them.

**Post-commit hedging:** After a commit tx is mined, the relayer pushes to `POST /internal/commitments/sync`. The API records the commitment and dispatches a hedger call. Hedge failures are logged and queued for retry via `hedger_queue_loop`.
