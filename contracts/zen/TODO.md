# Zen Contracts TODO

## MVP
- Keep on-chain verifier + `circuitHash` aligned with `prover/circuits/build/settlement_hashes.json` (field-reduced). Add CI check (RPC-gated) and update env caches after any redeploy.
- Extend tests for pause/rotation sequencing, cap updates mid-market, multi-claim ordering, and protocol cap edge cases.

## Post-MVP
- Fuzz/invariant coverage for Poseidon leaf creation, duplicate tickets/salts, and surplus distribution (pool draw/return).
- Scripted monitoring helpers for protocol pool draws/rake and factory event mirroring for backend consumers.
- Optional guardrails: document signer/oracle rotation cadence and consider timelock/pauser flows if required by ops.
