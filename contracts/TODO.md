# Contracts TODO & Future Work

The MVP contracts are functionally complete for Horizen EVM testnet, but several items remain to reach production readiness. They are grouped by priority and include rationale.

## High Priority

- **Integrate real ZK verifier + signal wiring**  
  The current `Verifier.sol` stub always returns `true`. Replace it with the generated Groth16/Noir verifier, document the `pubSignals` layout, and update `RevealMarket.verifyProof` to assert every relevant field (winning pool, outcome hash, circuit version). Without this, the protocol cannot trust settlements.

- **Additional settlement guards**  
  Enforce monotonic proof identifiers (e.g., proof nonce) and ensure `declaredWinningPool` cannot be inflated/deflated beyond expected circuit output. Consider storing a circuit hash/version so outdated proofs cannot be replayed.

- **Factory deployment tooling**  
  Extend `script/Deploy.s.sol` (or add a separate script) to optionally create a market post-deployment and emit JSON artifacts for front-end / backend consumption. This is needed for repeatable testnet deployments.

- **End-to-end rake override validation**  
  Expand Foundry tests to cover scenarios where different overrides are applied across multiple markets, and ensure events (`MarketCreated`, `RakeConfigured`) are indexed by indexers/backends. Run a mainnet-style integration test to assert override math during settlement.

- **Resolution eventing for indexers**  
  Emit explicit events (e.g., `MarketResolved`) with the final payout vector and UMA question IDs so off-chain services can subscribe without re-reading storage. Coordinate with the backend to agree on field ordering and versioning.

- **Invariants & fuzz coverage**  
  Add Foundry `InvariantTest` suites for sums like `claimedWinningStake <= winningPool`, `paidOut + treasury rake <= total pool`, and guardian/cancellation state machines. Invariants catch settlement regressions before audit.

- **Static analysis in CI**  
  Wire Slither + `forge fmt`/`forge fmt --check` + `solhint` into GitHub Actions to keep security linting automated. Currently only local scripts catch regressions.

## Medium Priority

- **Treasury transfer flexibility**  
  Evaluate whether rake should be streamed directly to `RakeManager` (pull vs push) or support multi-recipient splits. Capture the chosen model and adjust `_finalizeSettlement`.

- **Event indexing**  
  Ensure all emitted events index critical fields (`MarketCancelled`, `EmergencySettled`, metadata updates) so off-chain indexers can easily subscribe. Some events currently omit indexes for commonly queried values.

- **Factory metadata lifecycle**  
  `setMarketMetadata` writes opaque URIs; define a schema (e.g., JSON structure with version) and document it for front-end parity. Also consider emitting the previous value for diff tracking.

- **Guardian playbooks**  
  Document expected guardian responses (when to cancel vs. emergency settle). Codify timeouts as constants or config knobs if the operational process demands them.

## Nice-to-have

- **Upgradeable verifier hook**  
  Provide a circuit version registry on the factory so markets can be pinned to a verifier/circuit pair (useful during staged rollouts or audit findings).

- **Gas regression gates**  
  Agree on per-function gas ceilings (commit, claim, refund) and add assertions to the test suite (`forge snapshot --diff` checks plus custom asserts).

- **Cross-chain strategy**  
  If Reveal Market will expand beyond Horizen EVM, evaluate how factory registries and oracle addresses are managed across chains (may require bridging or multi-sig controls).

- **Backend-integrated settlement tooling**  
  Deliver a script or library function that accepts the backend’s Conditional Tokens snapshot and drives the on-chain `postResult/settle` flow end-to-end, so operators have a single command to synchronize markets.

Each item lists why it matters; address the high priority group before attempting a mainnet or public beta release.

Implement option to use Horizen ZEN testnet: https://docs.goldsky.com/chains/horizen
