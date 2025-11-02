# Contracts TODO

- [contracts] Replace the stub `Verifier` with the production Groth16/Noir verifier generated from the Polymarket circuit and wire in real `pubSignals` semantics.
- [backend] Implement the off-chain oracle agent that watches Polymarket markets, enforces the probation window, and invokes `lock`, `postResult`, and `verifyProof` on-chain.
- [contracts/testing] Add gas snapshot assertions for commit/claim/refund to meet the ≥90% coverage + gas budget targets.
- [devops/testing] Integrate Slither/Solhint linting and gas snapshot assertions into CI as required by the project plan.
