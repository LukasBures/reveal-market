// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

/// @notice Interface for Groth16-compatible verifiers used by RevealMarket instances.
interface IVerifier {
    /// @notice Hash identifying the currently installed circuit/verifying key.
    function circuitHash() external view returns (bytes32);

    /// @notice Number of public inputs the verifier expects (enforced by the IC vector).
    function expectedInputs() external view returns (uint256);

    /// @notice Hash identifying the currently installed verifying-key material.
    function verifyingKeyHash() external view returns (bytes32);

    /// @notice Verifies a proof against public signals.
    /// @dev Public signals order:
    /// [merkleRoot, marketId, winningOutcomeId, totalEscrow, totalLiability, rakeBps, poolTotalYes, poolTotalNo, circuitHash, padding(0)].
    function verifyProof(bytes calldata proof, uint256[10] calldata pubSignals) external view returns (bool success);
}
