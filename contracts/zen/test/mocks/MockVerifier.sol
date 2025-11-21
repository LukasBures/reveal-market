// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IVerifier} from "../../src/interfaces/IVerifier.sol";

/// @notice Lightweight test double that allows forcing verifier outcomes.
contract MockVerifier is IVerifier {
    bool private _shouldVerify = true;
    uint256[10] private _lastSignals;
    bytes private _lastProof;
    bytes32 private _circuitHash;

    /// @notice Configure whether subsequent verify calls succeed.
    function setShouldVerify(bool value) external {
        _shouldVerify = value;
    }

    function setCircuitHash(bytes32 value) external {
        _circuitHash = value;
    }

    function circuitHash() external view returns (bytes32) {
        return _circuitHash;
    }

    function lastSignals() external view returns (uint256[10] memory) {
        return _lastSignals;
    }

    function lastProof() external view returns (bytes memory) {
        return _lastProof;
    }

    /// @inheritdoc IVerifier
    function verifyProof(bytes calldata proof, uint256[10] calldata signals) external override returns (bool success) {
        _lastSignals = signals;
        _lastProof = proof;
        return _shouldVerify;
    }
}
