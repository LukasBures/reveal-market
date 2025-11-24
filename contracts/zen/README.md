# Reveal Market – ZEN Contracts

Native ZEN commit/reveal markets with liability-aware accounting, house float, and ZK-settlement hooks. This folder contains only the Horizen (ZEN-native) deployment flow.

## Contracts
- `RevealMarket.sol`
  - Phases: Commit → Locked → Settled/Cancelled.
  - Native ZEN only (no ERC20).
  - Tracks user escrow vs house float; max liability must be covered by escrow + float (post-rake).
  - Payout multipliers (capped at 5x) baked into proof/public signals; rake deducted via `RakeManager`.
  - `commitWithQuote` verifies backend-signed pricing quotes: `keccak256("QUOTE_V1", chainid, address(this), expectedUser, outcomeId, stakeZen, zenUsd, expiry, quoteId)` (wrapped in `toEthSignedMessageHash`), recovered signer must match `pricingSigner`, `expectedUser == msg.sender`, and `usedQuoteIds` prevents replay.
  - Settlement validates: outcome hash, total/gross pool, rake, payout multiplier, market address, nonce, commitments root, winning commitments root, circuit version.
  - Commitments root currently a rolling hash; Merkle proofs are wired but should be replaced with a real Merkle accumulator (see TODO).
  - Claims require inclusion in winning commitments root, correct reveal, and solvency.
  - NonReentrant on commit/settle/claim; pause/guardian controls enforced.
- `MarketFactory.sol`
  - Deploys markets via EIP-1167 clones.
  - Enforces per-market/global liability/size caps; tracks float allocation and liability.
  - Guardian/owner controls: global commit/claim pauses, per-market pauses/guardian update.
- `RakeManager.sol`
  - Holds rake bps (max 2%) and treasury; computes net pools.
- `Verifier.sol` / `VerifierStub.sol`
  - Interface uses 12 public signals (liability, pool, rake, multiplier, outcome, version, nonce, market, float used, roots).

## Testing
`cd contracts/zen && forge test`
- Unit suites: market lifecycle, risk limits, rake, verifier shape.
- Invariants: liability coverage and pause enforcement (`test/RevealMarketInvariant.t.sol`).

## Deployment
- Native-only deployment; `script/Deploy.s.sol` uses 12-signal verifier and current `MarketFactory` ctor (implementation, rakeManager, treasury, verifier, pricingSigner).
- Set `PRICING_SIGNER_ADDRESS` before running the deploy script so markets inherit the expected signer for `commitWithQuote`.
- Update vk path/envs and `circuitHash` binding once circuits include hash in public signals (see TODO).

## Known Gaps (see TODO.md for details)
- Commitments root needs a real Merkle accumulator + circuit alignment.
- Circuit hash binding not yet enforced in public signals.
- Docs/runbooks need refresh for native-only + 12-signal flow.
