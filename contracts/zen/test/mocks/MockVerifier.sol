// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IVerifier} from "../../src/interfaces/IVerifier.sol";

contract MockVerifier is IVerifier {
    bytes32 private _circuitHash;
    bool public shouldVerify = true;

    constructor(bytes32 circuitHash_) {
        _circuitHash = circuitHash_;
    }

    function circuitHash() external view override returns (bytes32) {
        return _circuitHash;
    }

    function expectedInputs() external pure override returns (uint256) {
        return 10;
    }

    function setShouldVerify(bool value) external {
        shouldVerify = value;
    }

    function verifyProof(bytes calldata, uint256[10] calldata) external view override returns (bool) {
        return shouldVerify;
    }
}
