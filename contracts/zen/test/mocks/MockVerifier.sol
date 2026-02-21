// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {IVerifier} from "../../src/interfaces/IVerifier.sol";

contract MockVerifier is IVerifier {
    bytes32 private _circuitHash;
    bytes32 private _verifyingKeyHash;
    address private _owner;
    bool public shouldVerify = true;

    constructor(bytes32 circuitHash_) {
        _circuitHash = circuitHash_;
        _verifyingKeyHash = keccak256(abi.encodePacked("mock-vk", circuitHash_));
        _owner = msg.sender;
    }

    function circuitHash() external view override returns (bytes32) {
        return _circuitHash;
    }

    function expectedInputs() external pure override returns (uint256) {
        return 10;
    }

    function verifyingKeyHash() external view override returns (bytes32) {
        return _verifyingKeyHash;
    }

    function setShouldVerify(bool value) external {
        shouldVerify = value;
    }

    function setCircuitHash(bytes32 newHash) external {
        _circuitHash = newHash;
        _verifyingKeyHash = keccak256(abi.encodePacked("mock-vk", newHash));
    }

    function setVerifyingKeyHash(bytes32 newHash) external {
        _verifyingKeyHash = newHash;
    }

    function owner() external view returns (address) {
        return _owner;
    }

    function transferOwnership(address newOwner) external {
        require(msg.sender == _owner, "not owner");
        _owner = newOwner;
    }

    function verifyProof(bytes calldata, uint256[10] calldata) external view override returns (bool) {
        return shouldVerify;
    }
}
