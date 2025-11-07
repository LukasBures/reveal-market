// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Verifier
/// @notice Stub verifier that always approves provided proofs.
contract Verifier {
    event ProofChecked(bool success, address indexed sender); // Emits whenever the stub is called.

    /// @notice Verifies a proof. Always returns true for MVP.
    /// @param proof Serialized proof blob (unused for stub).
    /// @param pubSignals Public signals array (unused for stub).
    function verifyProof(bytes calldata proof, uint256[4] calldata pubSignals) external returns (bool success) {
        proof; // Silence unused variable warning.
        pubSignals; // Silence unused variable warning.
        emit ProofChecked(true, msg.sender); // Broadcast that verification (always) succeeded.
        return true; // Always return true for MVP stub.
    }
}
