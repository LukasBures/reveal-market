// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Interface for Groth16-compatible verifiers used by markets. Returning a bool keeps callers agnostic to the implementation.
interface IVerifier {
    /// @notice Verifies a proof against public signals.
    /// @return success True when proof verification passes.
    function verifyProof(bytes calldata proof, uint256[12] calldata pubSignals) external returns (bool success);
}
