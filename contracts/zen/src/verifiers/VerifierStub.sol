// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IVerifier} from "../../src/interfaces/IVerifier.sol";

/**
 * @title VerifierStub – dev-only proving shortcut
 *
 * Local testnets often need a drop-in replacement for the Groth16 verifier so contracts can be smoke-tested without large proofs.
 * This stub can be toggled via `setShouldVerify` and emits `ProofChecked` for traceability.
 *
 * Never deploy it in production: there is no actual validation and it returns whatever boolean is configured.
 */

/// @notice Simple fallback verifier that always approves proofs. Intended for local/dev usage only.
contract VerifierStub is IVerifier {
    event ProofChecked(bool success, address indexed caller);

    bool private _shouldVerify = true;
    bytes32 private _circuitHash;

    /// @notice Configure whether the stub should report success.
    function setShouldVerify(bool value) external {
        _shouldVerify = value;
    }

    function setCircuitHash(bytes32 hash) external {
        _circuitHash = hash;
    }

    function circuitHash() external view returns (bytes32) {
        return _circuitHash;
    }

    /// @inheritdoc IVerifier
    function expectedInputs() external pure returns (uint256) {
        return 10;
    }

    /// @inheritdoc IVerifier
    function verifyProof(bytes calldata, uint256[10] calldata) external override returns (bool success) {
        emit ProofChecked(_shouldVerify, msg.sender);
        return _shouldVerify;
    }
}
