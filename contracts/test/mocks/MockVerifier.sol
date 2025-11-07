// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IVerifier} from "../../src/interfaces/IVerifier.sol";

/// @notice Lightweight test double that allows forcing verifier outcomes.
contract MockVerifier is IVerifier {
    bool private _shouldVerify = true;

    /// @notice Configure whether subsequent verify calls succeed.
    function setShouldVerify(bool value) external {
        _shouldVerify = value;
    }

    /// @inheritdoc IVerifier
    function verifyProof(bytes calldata, uint256[4] calldata) external view override returns (bool success) {
        return _shouldVerify;
    }
}
