# Settlement Circuit Specification

This document captures the current public-signal layout, constraints, and proof-handling guarantees for the Groth16 circuit that drives `RevealMarket.verifyProof`.

## Public Signals (10)

| Index | Name | Description |
| --- | --- | --- |
| `0` | `merkleRoot` | Keccak-based commitments root for the locked market. |
| `1` | `marketId` | `uint256` identifier (the market contract address cast to uint). |
| `2` | `winningOutcomeId` | Outcome id that wins (0 = YES, 1 = NO for MVP). |
| `3` | `totalEscrow` | Gross escrow before rake (sum of all commits). |
| `4` | `totalLiability` | Total owed to winners given the payout curve. |
| `5` | `rakeBps` | Applied rake in basis points (must be <= 10_000). |
| `6` | `poolTotalYes` | Aggregate YES stake. |
| `7` | `poolTotalNo` | Aggregate NO stake. |
| `8` | `circuitHash` | Binding hash for the circuit/proving/verification keys. |
| `9` | `padding` | Must be zero (reserved to keep array length 10). |

## Core Constraints

1. `poolTotalYes + poolTotalNo == totalEscrow`.
2. `winningOutcomeId` is in range for the compiled circuit (0/1 for MVP).
3. `rakeBps <= 10_000`.
4. `totalLiability <= totalEscrow` (checked via LessThan guard in-circuit).
5. `circuitHash` matches the hash derived from the proving/verification keys.
6. `padding == 0` to enforce a fixed 10-signal shape.

## Verifier Configuration

* The production verifier (`contracts/src/Verifier.sol`) stores its verifying key on-chain and enforces:
  * Expected signal count (`expectedInputs`, currently `10`).
  * Field-range checks for verifying-key coordinates (G1/G2 points).
  * Pairing equation via the BN254 precompiles.
* The verifying key is supplied at deployment time via `contracts/cache/settlement-vk.json` (mirrored under `contracts/zen/cache/settlement-vk.json` for Foundry tooling). Environment variables:
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
  "expectedInputs": 10
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

## Current hashes (compiled on macOS with circom 2.2.3)

* Proving key hash: `0x903b7ef2a7c90cf19408308f5d705ae86f9541a9a0411f9b9e49d626767ec13c`
* Verification key hash: `0xdbbddb31ad5ddbe8cbf502d5230b828562d0702d87ee23d33470dcec915c53d9`
* circuitHash: `0x6adf50a550f63493258f58fef2eedac95c39a42cb2615af23b85a6f42705f8c5`

Refer to `contracts/docs/RevealMarket_line_by_line.md` for the full settlement flow and to `contracts/script/Deploy.s.sol` for the automated deployment pipeline.
