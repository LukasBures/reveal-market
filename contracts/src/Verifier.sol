// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Verifier
/// @notice Stub verifier that always approves provided proofs.
contract Verifier {
    event ProofChecked(bool success, address indexed sender);

    /// @notice Verifies a proof. Always returns true for MVP.
    /// @param proof Serialized proof blob (unused for stub).
    /// @param pubSignals Public signals array (unused for stub).
    function verifyProof(bytes calldata proof, uint256[4] calldata pubSignals) external returns (bool success) {
        proof;
        pubSignals;
        emit ProofChecked(true, msg.sender);
        return true;
    }
}
