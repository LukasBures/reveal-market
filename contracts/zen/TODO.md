# TODO – Zen Contracts

- **Verifier refresh + circuit hash alignment**
  - Regenerate Groth16 artifacts and deploy a fresh verifier; update factory configs (`circuitHash`) and caches (`contracts/cache/settlement-vk.json`, prover hashes) so settlement cannot verify with stale circuits.
  - Add a script/assertion to compare on-chain `circuitHash()` with cached hash before settlement; fail CI when mismatched.

- **Test coverage + fuzzing**
  - Fuzz Merkle inclusion/replay protection (duplicate tickets, reused salts, mismatched ticketId/outcome) and protocol cap edges (pool depletion, surplus distribution).
  - Add multi-claim sequencing tests with interleaved pauses and cap updates; cover rake updates mid-market and ensure settlement enforces proof rake equals storage.
  - Include invariant tests for deadline extension monotonicity and signer/oracle rotations.

- **Deployment scripts**
  - Production-grade `script/Deploy*.s.sol` with env-driven parameters (ticket size, max commits, rake bps, cap, oracle, relayer, signer, verifier, circuit hash).
  - Add scripts for factory/escrow/pool rotation and rake sync across markets; include broadcast + summary output for backend ingestion.

- **Monitoring/telemetry**
  - Emit explicit events for protocol pool draws/repayments and relayer credits if downstream analytics expect them; document ABI for backend/hedger/relayer.
  - Consider exposing view functions for outstanding liability, collected rake, and per-market cap to simplify dashboards.

- **Admin & safety**
  - Document signer lifecycle (rotation cadence, timelock/pauser expectations) and add optional timelocks/pauses on admin actions if required by ops.
  - Add guardrails for `setCommitsPaused`/`setClaimsPaused` misuse (e.g., cannot unpause settled markets) and consider emit reason codes for pauses.
