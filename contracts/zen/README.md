# Reveal Market – ZEN Contracts

Native ZEN commit/reveal markets with liability-aware accounting, house float, and ZK-settlement hooks. This folder contains only the Horizen (ZEN-native) deployment flow.

## Contracts
- `RevealMarket.sol`
  - Phases: Commit → Locked → Settled/Cancelled.
  - Native ZEN only (no ERC20).
  - Tracks user escrow vs house float; max liability must be covered by escrow + float (post-rake).
  - Payout multipliers (capped at 5x) enforced against settlement proofs; rake deducted via `RakeManager`.
  - `commitWithQuote` verifies backend-signed pricing quotes: `keccak256("QUOTE_V1", chainid, address(this), expectedUser, outcomeId, stakeZen, zenUsd, expiry, quoteId)` (wrapped in `toEthSignedMessageHash`), recovered signer must match `pricingSigner`, `expectedUser == msg.sender`, and `usedQuoteIds` prevents replay.
  - Settlement validates: commitments root, market id, winning outcome id, total/gross pool, rake, and circuit hash. Liability is bound to the market’s payout multiplier/winning pool before the proof is accepted.
  - Commitments root uses a keccak-based Merkle tree for claim proofs.
  - Claims require inclusion in winning commitments root, correct reveal, and solvency.
  - NonReentrant on commit/settle/claim; pause/guardian controls enforced.
- `MarketFactory.sol`
  - Deploys markets via EIP-1167 clones.
  - Enforces per-market/global liability/size caps; tracks float allocation and liability.
  - Guardian/owner controls: global commit/claim pauses, per-market pauses/guardian update.
- `RakeManager.sol`
  - Holds rake bps (max 2%) and treasury; computes net pools.
- `Verifier.sol` / `VerifierStub.sol`
  - Interface uses 10 public signals (commitments root, market id, winning outcome id, totalEscrow, totalLiability, rakeBps, poolTotalYes, poolTotalNo, circuitHash, padding=0) with `expectedInputs` enforced during market init.

## Testing
`cd contracts/zen && forge test`
- Unit suites: market lifecycle, risk limits, rake, verifier shape.
- Invariants: liability coverage and pause enforcement (`test/RevealMarketInvariant.t.sol`).
- Smoke: end-to-end deploy/commit/settle/claim (`test/Smoke.t.sol`).

## Deployment
- Native-only deployment; `script/Deploy.s.sol` uses the 10-signal verifier and current `MarketFactory` ctor (implementation, rakeManager, treasury, verifier, pricingSigner).
- Set `PRICING_SIGNER_ADDRESS` before running the deploy script so markets inherit the expected signer for `commitWithQuote`.
- Update vk path/envs and `circuitHash` binding when rotating circuits/keys.
- Env template lives at `contracts/zen/.env.example`. Required vars for `forge script script/Deploy.s.sol`: `DEPLOYER_KEY`, `ORACLE_ADDRESS`, `TREASURY_ADDRESS`, `RAKE_BPS`, `PRICING_SIGNER_ADDRESS`, and `SETTLEMENT_VK_PATH` (or `USE_STUB_VERIFIER=1` for dev only). Ensure the verifier JSON has `expectedInputs=10` and the circuitHash matches your prover artifacts.
- Common deploy tweaks:
  - `minCommitmentSize` must be >= 0.01 ZEN (on-chain floor) and is set per market via the factory params.
  - `maxCommitments` caps total tickets per market (default 4096, configurable per market), and `maxTicketsPerUser` throttles per-user spam; set these in `MarketFactory.CreateMarketParams`.
  - Keep `expectedInputs` and `circuitHash` in sync with the prover artifacts—circuits with a different public-signal layout will be rejected on init.

## Operational Notes
- Quotes: off-chain signer must match `PRICING_SIGNER_ADDRESS` and use `QUOTE_V1` digest `(chainid, market, user, outcome, stake, zenUsd, expiry, quoteId)`. Replay is blocked on-chain via `usedQuoteIds`.
- Proofs: verifier enforces 10 public signals and circuit hash. On-chain settlement recomputes liability from on-chain pools + payout multiplier, so fabricated pool totals/liability in proofs are rejected.
- Risk limits: `minCommitmentSize`, `maxTicketsPerUser`, `maxCommitments`, and `maxMarketSize` are all enforced on-chain; configure them per market at creation time via the factory.

## Known Gaps (see TODO.md for details)
- Settlement circuit remains minimal (range checks, no inclusion proofs) and should be upgraded alongside the Merkle accumulator if/when fuller proofs are needed.
- Docs/runbooks need refresh for native-only + 10-signal flow.
