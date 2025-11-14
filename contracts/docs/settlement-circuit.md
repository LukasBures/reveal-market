# Settlement Circuit Specification

This document captures the current public-signal layout, constraints, and proof-handling guarantees for the Groth16 circuit that drives `RevealMarket.verifyProof`.

## Public Signals (6)

| Index | Name | Description |
| --- | --- | --- |
| `0` | `winningPool` | Total stake attributed to the winning outcome. Must be `> 0` and `<= totalPool`. |
| `1` | `totalPool` | Gross collateral held by the market **before** rake is deducted. Must equal the contract’s `totalPool`. |
| `2` | `outcomeHash` | 32-byte hash of the winning outcome (keccak-256). The circuit emits this value modulo the BN254 field; `RevealMarket` reinterprets it as a `bytes32` and compares it to the oracle-posted hash. |
| `3` | `circuitVersion` | Hard-coded version guard. The on-chain contract enforces equality with `RevealMarket.CIRCUIT_VERSION()`. |
| `4` | `proofNonce` | Unique monotonic nonce (recommended 256-bit random) used once per settlement. Prevents replay across blocks or chains. |
| `5` | `marketAddress` | 160-bit address of the market contract packed into the lower bits of the signal. `RevealMarket` rejects proofs whose address does not match `address(this)` or that attempt to use high bits. |

## Core Constraints

1. `totalPool` equals the sum of all revealed ticket amounts before rake.
2. `winningPool` is the sum of tickets committed to the oracle-declared outcome.
3. `winningPool > 0` and `winningPool <= totalPool`.
4. `outcomeHash` matches the oracle result stored on-chain.
5. `circuitVersion` equals the hard-coded constant baked into both the Solidity contract and the circuit artifacts.
6. `proofNonce` is recorded inside the contract; a nonce can only be used once.
7. `marketAddress` binds the proof to a specific clone so proofs cannot be replayed across markets/forks.

## Anti-Replay Guards

* The Solidity contract tracks every consumed `proofNonce` in `_consumedProofNonces` and exposes the latest via `lastProofNonce()`.
* Nonces are required to be non-zero and unique. Duplicate nonces revert with `ProofNonceUsed`.
* `marketAddress` must fit inside 160 bits; otherwise the contract reverts with `InvalidMarketAddress`.

## Verifier Configuration

* The production verifier (`contracts/src/Verifier.sol`) stores its verifying key on-chain and enforces:
  * Expected signal count (`expectedInputs`, currently `6`).
  * Field-range checks for verifying-key coordinates (G1/G2 points).
  * Pairing equation via the BN254 precompiles.
* The verifying key is supplied at deployment time via `contracts/cache/settlement-vk.json`. Environment variables:
  * `SETTLEMENT_VK_PATH` — optional override for the JSON file.
  * `USE_STUB_VERIFIER=1` — bypasses Groth16 verification and deploys the legacy stub (dev/test only).
* JSON schema:

```jsonc
{
  "alpha1": [ "<uint256>", "<uint256>" ],
  "beta2": [
    ["<uint256>", "<uint256>"],
    ["<uint256>", "<uint256>"]
  ],
  "gamma2": [...],
  "delta2": [...],
  "ic": [
    ["<uint256>", "<uint256>"], // length == expectedInputs + 1
    "..."
  ],
  "circuitHash": "0x<bytes32>",
  "expectedInputs": 6
}
```

Use `snarkjs zkey export solidityverifier` (or Noir’s verifier generator) to emit these values.

## Dual Verification Workflow

1. Generate Groth16 proof off-chain after the oracle posts a result.
2. Submit the proof + public signals to `RevealMarket.verifyProof`. The contract emits:
   * `ProofVerified(success)` — parity with legacy instrumentation.
   * `ProofReceipt(proofNonce, verifierAddress, success)` — traceable identifier for dashboards/partners.
3. Forward the same proof to zkVerify (or another attestation layer) and persist their receipt/identifier.
4. Surface both the on-chain transaction hash and the zkVerify receipt to end users (see `frontend/app/proofs`).

## Security Notes

* The solidity verifier refuses to run without a verifying key (IC length mismatch reverts).
* Field elements for public inputs are not truncated on-chain; the circuit must already enforce validity.
* The stub verifier (`VerifierStub`) is preserved for local development but should never be deployed to production networks.

Refer to `contracts/docs/RevealMarket_line_by_line.md` for the full settlement flow and to `contracts/script/Deploy.s.sol` for the automated deployment pipeline.
