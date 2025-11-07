# Contracts Growth Roadmap

Smart-contract credibility is the clearest signal that Reveal Market handles investor capital with institutional rigor. The objectives below prioritize features that harden settlement guarantees, grow treasury yield, and prepare the protocol for broader distribution.

## Phase 1 – Credible Settlement Layer (Highest Leverage)

- **Groth16 verifier integration**  
  Replace the temporary stub with the audited verifier circuit, document public-signal layouts, and assert every settlement parameter (winning pool, circuit version, oracle hash) directly in `RevealMarket`. This unlocks external audits and institutional listings.

- **Proof replay & tamper guards**  
  Introduce proof nonces and circuit hashes so outdated or duplicated proofs cannot slip through during volatile markets.

- **Resolution event stream**  
  `MarketResolved` plus the `resolutionSummary()` view now publish winning stake, net pool, rake paid, and settlement timestamp. Next iteration should add payout vectors / UMA question IDs so indexers capture full context without rereading storage.

- **Factory deployment artifacts**  
  Extend `script/Deploy.s.sol` to emit JSON manifests (addresses, guardian keys, rake caps) and optionally instantiate a demo market. Deterministic artifacts accelerate partner testnet rollouts.

- **Invariant + fuzz coverage**  
  Add Foundry invariant suites (`paidOut + rake <= totalPool`, guardian-state correctness) and wire Slither/solhint into CI. Demonstrable security hygiene is a prerequisite for major investors.

## Phase 2 – Treasury & Liquidity Mechanics

- **Rake override validation**  
  Stress-test multi-market overrides, enforce 2% ceilings, and ensure `RakeConfigured` emits indexed parameters so analytics desks can reconcile revenue distribution.

- **Flexible treasury routing**  
  Explore split payouts (treasury + insurance fund) and codify the model before token launch. Investors need clarity on cash-flow destinations.

- **Metadata lifecycle definition**  
  Formalize a schema for `setMarketMetadata`, emit previous/next values, and document versioning so partner dashboards always reflect the latest collateral or narrative data.

- **Guardian operating model**  
  Encode decision windows (cancel vs. emergency settle) as constants/configs and document the expected playbooks for compliance reviews.

- **Horizen ZEN testnet enablement**  
  Provide scripts and configs that target Goldsky’s Horizen ZEN testnet so institutional pilots can run in a controlled sandbox before moving capital.

## Phase 3 – Expansion & Operational Excellence

- **Upgradeable verifier registry**  
  Track circuit versions per market so we can roll out new proofs without disrupting active liquidity, satisfying audit remediations while keeping markets live.

- **Gas regression gates**  
  Establish budgets for commit/claim/refund paths and enforce them with `forge snapshot --check` plus custom assertions. Predictable gas profiles improve ROI modeling for LPs.

- **Cross-chain readiness**  
  Design how MarketFactory registries, oracle endpoints, and guardian keys extend to additional chains without fragmenting governance.

- **Backend-aligned settlement tooling**  
  Offer a helper that consumes the backend’s Conditional Tokens snapshot and drives `postResult/settle` end-to-end, ensuring ops teams have a single button to sync books.

Delivering the Phase 1 items sends a clear message to strategic investors: Reveal Market’s settlement layer is audit-ready, tamper-resistant, and prepared to scale. Phases 2 and 3 compound that confidence into recurring treasury yield and multi-chain reach. 
