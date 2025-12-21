# TODO – Zen Contracts (MVP)

## MVP blockers
- **Circuit + verifier alignment**
  - Regenerate Groth16 artifacts and deploy a fresh verifier; update `contracts/zen/cache/settlement-vk.json`, factory `circuitHash`, and prover hashes so settlement cannot verify with stale circuits.
  - Add a script/assertion to compare on-chain `circuitHash()` with cached hash before settlement; fail CI when mismatched.
  - Update `docs/settlement-circuit.md` to match current signals (marketId is factory id, `totalEscrow` is net-of-rake, protocol cap allowed).
- **Deployment + env hygiene**
  - Fix `run_deploy.sh` default VK path and align `contracts/zen/.env.example` with the env names it expects (`PRIVATE_KEY`, `AUTHORIZATION_SIGNER`, `ZEN_TOKEN_ADDRESS`, etc.).
  - Add a `CreateMarket` script (or `cast` recipe) that emits JSON output for backend ingestion and preserves deterministic market ids/addresses.
- **Settlement safety**
  - Add a timeout cancel/refund path if the oracle never posts a result or proof.
  - Add a claim deadline + sweep for unclaimed payouts (to `ProtocolPool` or escrow) so funds do not remain stranded.
- **Payout routing decision**
  - Decide whether claims pay users directly or credit `RelayerEscrow`; wire `creditFromMarket` or remove it and update relayer/backend assumptions.
- **MVP test gaps**
  - Add regression tests for pause/rotation sequencing, cap updates mid-market, and multi-claim ordering.

## Post-MVP hardening
- **Fuzz/invariant coverage**
  - Fuzz Merkle inclusion/replay protection (duplicate tickets, reused salts, mismatched ticketId/outcome) and protocol cap edges (pool depletion, surplus distribution).
- **Monitoring/telemetry**
  - Confirm event ABI expectations for backend/hedger/relayer and add view helpers for outstanding liability, collected rake, and per-market cap if needed.
- **Admin guardrails**
  - Document signer/oracle rotation cadence and add optional timelocks for sensitive actions if required by ops.
