# `Verifier.sol` walkthrough

The Groth16 verifier now deployed with Reveal Market is configurable, replay-safe, and auditable. This guide highlights the important sections rather than enumerating every line of code.

## Imports & Interfaces

* `Ownable2Step` — allows the team to rotate the verifying key through a two-step process (transfer + accept).
* `IVerifier` — shared interface consumed by `RevealMarket`.
* `Pairing` — BN254 helper library (addition, scalar multiplication, pairing checks).

## State

```solidity
StoredVerifyingKey private _vk;
Pairing.G1Point[] private _ic;
bytes32 public circuitHash;
uint256 public immutable EXPECTED_INPUTS;
```

* `_vk` holds `α`, `β`, `γ`, `δ`.
* `_ic` stores the commitment vector used to derive `vk_x`.
* `circuitHash` is a 32-byte fingerprint for the circuit / verifying key.
* `EXPECTED_INPUTS` is immutable (currently `10`) and keeps the Solidity contract in lockstep with the circuit.

## Constructor & Key Rotation

```solidity
constructor(..., uint256 expectedInputs_) Ownable(msg.sender) {
    require(expectedInputs_ <= 16);
    EXPECTED_INPUTS = expectedInputs_;
    _setVerifyingKey(...);
}

function setVerifyingKey(...) external onlyOwner {
    _setVerifyingKey(...);
}
```

* Rejects deployments with zero inputs or more than sixteen public signals.
* `_setVerifyingKey` validates IC length (`EXPECTED_INPUTS + 1`), range-checks coordinates, replaces the stored points, updates `circuitHash`, and emits `VerifyingKeyUpdated`.

## Proof Verification

```solidity
function verifyProof(bytes calldata proofData, uint256[10] calldata pubSignals) external view returns (bool)
```

1. Ensures a verifying key is configured and that the caller supplied exactly `EXPECTED_INPUTS` public signals (10-signal settlement layout with `circuitHash` at index 8 and a zero padding slot at 9).
2. Decodes `proofData` into the `(A, B, C)` triple (256 bytes total).
3. Validates all G1/G2 coordinates are either the point at infinity or within the BN254 field.
4. Computes `vk_x = IC[0] + Σ (pubSignals[i] * IC[i+1])`.
5. Executes the pairing product check and returns the result.

The verifier purposely does **not** reject public inputs that exceed the field modulus; the Groth16 proof already reduces them modulo `r`, and `RevealMarket` expects the raw `bytes32` outcome hash.

## Helper Functions

* `_decodeProof` — ABI-decodes the proof blob and reuses `_buildG1` / `_buildG2`.
* `_validateFieldElement` — bounds-checks coordinates to prevent invalid-curve attacks.
* `_buildG1` / `_buildG2` — convenience wrappers that perform validation and construct structs.

## Events & Errors

* `VerifyingKeyUpdated(bytes32 circuitHash, uint256 inputs)` is emitted whenever the key changes.
* Errors guard unsupported input lengths, missing verifying keys, malformed proofs, and field overflows.

## Stub Verifier

The previous always-true stub now lives at `contracts/src/verifiers/VerifierStub.sol`. It still implements `IVerifier` and emits `ProofChecked`, but should only be used for local development (`USE_STUB_VERIFIER=1` in the deploy script).

For an end-to-end description of the circuit signals and replay guards, see [`docs/settlement-circuit.md`](./settlement-circuit.md).
