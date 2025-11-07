# Reveal Market On-Chain Stack

Our smart contracts provide the settlement certainty that investors, auditors, and liquidity programs demand. They turn every market listed by the API into a verifiable on-chain asset with transparent rake distribution and zk-proof enforcement.

## Core Components

| Contract | Investor Impact |
| --- | --- |
| **RevealMarket** | Handles commit → lock → settle flows with guardian safeguards and prepares the protocol for Groth16-based verification, so winnings cannot be manipulated. |
| **MarketFactory** | Mints minimal proxy markets, controls global safety switches, and emits metadata so off-chain services can index liquidity in real time. |
| **RakeManager** | Caps protocol fees below 2%, records treasury routing, and makes rake modeling clear for tokenholders. |
| **Verifier (upgrading)** | Temporary stub today; roadmap replaces it with the audited proof verifier that validates every settlement proof on-chain. |

This modular architecture lets us innovate quickly without sacrificing the compliance posture large partners expect.

## Design Principles

- **Guardrails first** – Guardian roles, commit/reveal deadlines, and emergency settlement tooling protect capital even under extreme market conditions.
- **Event-rich telemetry** – `MarketCreated`, `RakeConfigured`, and live `MarketResolved` events (plus the on-chain `resolutionSummary()` view) give analytics desks everything they need to reconcile revenue in real time.
- **Upgradeable yet predictable** – Factory-managed implementation pointers ensure that audits remain valid while still allowing us to roll out new verifier versions or collateral allow-lists.
- **Gas-conscious** – Minimal proxy deployments and carefully profiled settlement flows keep user costs low, preserving yield for LPs rather than miners.

## What’s Next

1. **Groth16 verifier integration** – Replaces the stub with a production verifier, documents signal layouts, and locks in settlement authenticity.
2. **Resolution telemetry enrichment** – Extend the new `MarketResolved` + `resolutionSummary()` surface with payout vectors and UMA references so treasuries can mirror results instantly.
3. **Factory deployment automation** – Produce machine-readable artifacts post-deployment for safer exchange integrations.
4. **Invariant testing & static analysis** – Expand fuzz and invariant suites alongside Slither/Solhint automation ahead of external audits.
5. **Horizen ZEN testnet-ready scripts** – Support sandbox launches where institutional partners can pilot liquidity with guardrails.

Each milestone strengthens the economic flywheel: provable outcomes lead to deeper liquidity, which drives more rake for the treasury and future token backers.

## Strategic Takeaways

- **Investable compliance** – All fees, overrides, and guardian actions are on-chain, enabling regulators and institutional LPs to audit payouts without privileged access.
- **Cross-stack synergy** – Backend services ingest on-chain events, while the worker can originate markets directly through the factory. This closed loop reduces informational asymmetry for investors.
- **Future token alignment** – Rake events and treasury routing feed into the broader tokenomics plan. When the token launches, holders inherit an infrastructure with transparent, recurring cash flows.

For partnership opportunities, validator participation, or audit collaboration, contact hello@revealmarket.xyz or DM [@RevealMarket](https://x.com/RevealMarket).
