// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Interface for Groth16-compatible verifiers used by markets. Returning a bool keeps callers agnostic to the implementation.
interface IVerifier {
    /// @notice Hash identifying the currently installed circuit/verifying key.
    function circuitHash() external view returns (bytes32);

    /// @notice Verifies a proof against public signals.
    /// @dev Public signals are ordered as:
    /// [merkleRoot, marketId, winningOutcomeId, totalEscrow, totalLiability, rakeBps, poolTotalYes, poolTotalNo, circuitHash, padding(0)].
    /// @return success True when proof verification passes.
    function verifyProof(bytes calldata proof, uint256[10] calldata pubSignals) external returns (bool success);
}
