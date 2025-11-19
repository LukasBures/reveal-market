# Contracts Growth Roadmap

Smart-contract credibility is the clearest signal that Reveal Market handles investor capital with institutional rigor. The objectives below prioritize features that harden settlement guarantees, grow treasury yield, and prepare the protocol for broader distribution.

### TL;DR priorities
1. **Finalize Groth16 production rollout** – Ship real keys, rotation tooling, and replay persistence so every zk receipt is audit-ready.
2. **Codify governance & ops** – Consume deployment manifests, add invariants/fuzzing, and rehearse ownership/guardian transfers so institutional partners can trust admin flows.
3. **Unlock treasury & expansion** – Implement rake overrides/flexible routing plus Horizen testnet + verifier registry work to unblock new venues and multi-chain pilots.

## Phase 1 – Credible Settlement Layer (Highest Leverage)

- **Groth16 verifier hardening**
  Finalize proving-key ceremony + audits, swap the placeholder `settlement-vk.json` with production keys, wire automated verifying-key rotation (with circuit hashes recorded on-chain), and document how zkVerify attestations mirror every on-chain receipt. Deliver a rotation runbook + monitoring alerts for mismatched hashes.

- **Proof replay & tamper guards**
  Replay guards exist on-chain, but there is no backend persistence/logging. Extend the worker/API to store `proofNonce`, emitting receipts via `/proofs`, so downstream systems can audit replays and cross-check zkVerify receipts.

- **Resolution event stream**
  `MarketResolved` plus the `resolutionSummary()` view now publish winning stake, net pool, rake paid, and settlement timestamp. Next iteration should add payout vectors / UMA question IDs so indexers capture full context without rereading storage.

- **Factory deployment artifacts**
  `Deploy.s.sol` writes `last-deployment.json`, but nothing consumes it. Build a CLI or backend bootstrap that ingests these manifests (addresses, guardian keys, rake caps) and hydrates env vars automatically. Consider emitting per-market manifests and default demo deployments for integration testing.

- **Invariant + fuzz coverage**
  Extend current unit/fuzz suites with Forge `invariant` tests (`paidOut + rake <= deposits`, guardian state monotonicity), plus Slither + echidna runs in CI. Highlight coverage gaps (refund loops, emergency settle) and gate PRs on these checks.

- **Ownership & guardian transfer drills**
  Codify runbooks + tests for `Ownable2Step`/guardian transfers (Factory, RakeManager) so we can rotate keys without downtime—critical once capital pools rely on these contracts. Include simulated ceremonies in tests and document on-call procedures.

## Phase 2 – Treasury & Liquidity Mechanics

- **Rake override validation**
  Stress-test multi-market overrides, enforce 2% ceilings, and ensure `RakeConfigured` emits indexed parameters so analytics desks can reconcile revenue distribution. Add analytics hooks for per-market rake so backend/partners can reconcile treasury inflows.

- **Flexible treasury routing**
  Explore split payouts (treasury + insurance fund) and codify the model before token launch. Investors need clarity on cash-flow destinations. Consider upgradeable manager with per-market overrides, plus docs for revenue transparency.

- **Metadata lifecycle definition**
  Formalize a schema for `setMarketMetadata`, emit previous/next values, and document versioning so partner dashboards always reflect the latest collateral or narrative data.

- **Guardian operating model**
  Encode decision windows (cancel vs. emergency settle) as constants/configs and document the expected playbooks for compliance reviews.

- **Horizen ZEN testnet enablement**
  Provide scripts and configs that target Goldsky’s Horizen ZEN testnet so institutional pilots can run in a controlled sandbox before moving capital. Include canned deployment artifacts + faucet instructions.

## Phase 3 – Expansion & Operational Excellence

- **Upgradeable verifier registry**
  Track circuit versions per market so we can roll out new proofs without disrupting active liquidity, satisfying audit remediations while keeping markets live. Add events + backend sync to map markets → circuit hashes.

- **Gas regression gates**
  Establish budgets for commit/claim/refund paths and enforce them with `forge snapshot --check` plus custom assertions. Predictable gas profiles improve ROI modeling for LPs. Document macros for frequently-touched code (e.g., caching pause flags) to guide contributors.

- **Cross-chain readiness**
  Design how MarketFactory registries, oracle endpoints, and guardian keys extend to additional chains without fragmenting governance. Include address registries + metadata so the backend can route traffic per chain.

- **Backend-aligned settlement tooling**
  Offer a helper that consumes the backend’s Conditional Tokens snapshot and drives `postResult/settle` end-to-end, ensuring ops teams have a single button to sync books.

Delivering the Phase 1 items sends a clear message to strategic investors: Reveal Market’s settlement layer is audit-ready, tamper-resistant, and prepared to scale. Phases 2 and 3 compound that confidence into recurring treasury yield and multi-chain reach.
