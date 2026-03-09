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
