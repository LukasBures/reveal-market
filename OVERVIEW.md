# Reveal Market — System Overview

Reveal Market is a decentralized prediction market where every bet is cryptographically sealed before any outcome is known. The core mechanism is commit-and-reveal: users submit a Poseidon hash of their prediction on-chain, then settle via a Groth16 zero-knowledge proof that validates up to 256 commitments in a single transaction. This makes front-running structurally impossible rather than just discouraged — the protocol's security model reduces to a math proof, not operator trust.

## Settlement Flow

The full lifecycle of a market spans five on-chain phases:

```
Commit → [deadline] → Lock Batches → Post Result → Verify & Settle → Claim
```

During the commit phase, users submit `Poseidon(outcomeId, amount, salt)` hashes. After the deadline, the worker batches commitments into groups of 256, builds Merkle roots, and the relayer calls `lockBatches` on-chain (oracle-authorized, relayer-escrow-signed). Once an oracle posts the winning outcome, the Go prover generates a Groth16 proof over the full commitment set and the relayer submits `verifyAndSettleBatched`. The on-chain verifier checks 10 public signals — merkle root, market ID, winning outcome, total escrow, total liability, rake, pool sizes, and circuit hash — against the proof. If it passes, winners can claim.

## Architecture

Nine services span Python, Go, TypeScript, and Solidity — each owning exactly one responsibility:

| Service | Language | Role |
|---------|----------|------|
| **API** | Python / FastAPI | Market data, pricing quotes, signed QUOTE\_V1 digests |
| **Worker** | Python / FastAPI | Polymarket ingestion, batch Poseidon hashing, settlement orchestration |
| **Relayer** | Python / FastAPI | On-chain transaction queue (commit / lock / claim) with dead-letter retry |
| **Streamer** | Python / FastAPI | Live Polymarket CLOB + Binance FX aggregation via SSE/WebSocket |
| **Hedger** | Python / FastAPI | Exposure tracking, cross-chain hedging via EIP-712 signed orders |
| **Prover** | Go | Groth16 proof generation using Circom artifacts + rapidsnark |
| **Frontend** | Next.js 15 / TS | App UI + marketing site (App Router) |
| **Contracts (Horizen)** | Solidity 0.8.33 | RevealMarket, MarketFactory, ProtocolPool, RelayerEscrow, Verifier |
| **Contracts (Base/Polygon)** | Solidity 0.8.33 | BaseLpVault, HedgeStrategyExecutor |

Redis is the coordination layer connecting everything — tagged cache invalidation, worker heartbeats, batch stats, pubsub fanout — and services degrade gracefully when it is unavailable.

## ZK Circuit

The settlement circuit (`settlement.circom`) is written in Circom 2.1.5 and compiled to a Groth16 proving system over BN254. It takes 256 commitment slots as private inputs (ticket ID, outcome, amount, payout, user address, salt) and proves that:

- Every commitment hash matches `Poseidon(user, outcomeId, amount, salt)`
- The Merkle root of all commitment hashes matches the locked on-chain root
- `totalLiability` equals the sum of payouts for winning commitments only
- `rakeBps` is within the protocol's allowed range (≤ 10 000 bps)
- The `circuitHash` embedded in the proof matches the deployed verifier's expected hash

The circuit produces 10 public outputs that the on-chain `Verifier` checks atomically. A single proof settles an entire batch of up to 256 bets in one transaction.

## Core Technical Challenges

**Cross-language consistency.** The batch size (256 commitments, Merkle depth 8) is a constant shared across the Circom circuit, the Solidity contracts, the Python proof builder, and the Go prover. The deployed `Verifier` contract is bound to a specific `circuitHash` — break that invariant during an upgrade and settlement halts entirely. The `MarketFactory` enforces this via an on-chain verifier approval policy before any new market can be created.

**ZK artifact management.** Groth16 proving keys are large and version-sensitive. They live in a git submodule (`prover/artifacts/`) pinned to a specific PTAU ceremony (`powersOfTau28_hez_final_21.ptau`, 2²¹ constraints). The prover refuses to start if artifacts are absent, making deployment a hard dependency on key availability.

**Multi-hop transaction pipeline.** A single user action fans out across five services before it lands on-chain. Each hop has its own failure domain: the relayer has dead-letter queuing and replay endpoints, the worker tracks batch state in Postgres, and the hedger monitors net exposure across all open markets in real time. Idempotency and exactly-once semantics are enforced at each boundary.

**Cross-chain risk management.** Protocol liquidity lives on Horizen EVM; hedging executes on Base/Polygon via the `HedgeStrategyExecutor` contract, which accepts EIP-712 signed orders from the hedger service. This decouples the on-chain settlement chain from the hedging infrastructure and allows the hedger to operate independently without custody over primary funds.

## Security Model

The protocol enforces defence-in-depth at every layer. CSP, HSTS, COOP, CORP, and Referrer-Policy headers are applied at both the Next.js edge and the FastAPI middleware. Caddy (the edge proxy) blocks all `/internal/*` routes before they reach the API. Internal service calls require a shared `X-Internal-Secret` header; pricing quotes are ECDSA-signed by a dedicated hot key. On-chain, `RevealMarket` uses `ReentrancyGuard`, `SafeERC20`, and a commitment deadline enforced at the contract level — users cannot commit after the market closes, regardless of what the API says.

The ZK layer is the final and strongest guarantee: settlement correctness is verifiable by anyone with the proof and public inputs, with no trust in the operator required.
