// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Interface for zero-knowledge proof verification contracts.
interface IVerifier {
    /// @notice Verifies a proof against public signals.
    /// @return success True when proof verification passes.
    function verifyProof(bytes calldata proof, uint256[4] calldata pubSignals) external returns (bool success);
}
