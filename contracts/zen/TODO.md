# TODO – Zen Contracts (MVP)

## MVP blockers
- **Circuit + verifier alignment**
  - Regenerate Groth16 artifacts and deploy a fresh verifier; update `contracts/zen/cache/settlement-vk.json`, factory `circuitHash`, and prover hashes so settlement cannot verify with stale circuits.
  - Wire `scripts/check_circuit_hash.sh` into CI when RPC/VERIFIER envs are available so mismatches fail fast.
- **Deployment + env hygiene**
  - None at the moment; `run_deploy.sh` defaults and `.env.example` are aligned, and `scripts/create_market.sh` emits JSON for backend ingestion.
- **MVP test gaps**
  - Add regression tests for pause/rotation sequencing, cap updates mid-market, and multi-claim ordering.

## Post-MVP hardening
- **Fuzz/invariant coverage**
  - Fuzz Merkle inclusion/replay protection (duplicate tickets, reused salts, mismatched ticketId/outcome) and protocol cap edges (pool depletion, surplus distribution).
- **Monitoring/telemetry**
  - Confirm event ABI expectations for backend/hedger/relayer and add view helpers for outstanding liability, collected rake, and per-market cap if needed.
- **Admin guardrails**
  - Document signer/oracle rotation cadence and add optional timelocks for sensitive actions if required by ops.
