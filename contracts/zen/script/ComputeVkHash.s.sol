// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {console} from "forge-std/Script.sol";
import {Deploy} from "./Deploy.s.sol";

/// @dev Helper to compute EXPECTED_VERIFIER_KEY_HASH from a VK JSON file.
///      Usage: SETTLEMENT_VK_JSON="$(cat path/to/vk.json)" forge script script/ComputeVkHash.s.sol --tc ComputeVkHash --sig "computeHash()" -v
contract ComputeVkHash is Deploy {
    function computeHash() external view {
        string memory vkJson = vm.envString("SETTLEMENT_VK_JSON");
        VerifyingKeyConfig memory vkConfig = _loadVerifyingKeyJson(vkJson);

        bytes32 computedVerifierKeyHash = keccak256(
            abi.encode(
                vkConfig.alpha1, vkConfig.beta2, vkConfig.gamma2, vkConfig.delta2, vkConfig.ic, vkConfig.circuitHash,
                vkConfig.expectedInputs
            )
        );

        console.log("EXPECTED_CIRCUIT_HASH:");
        console.logBytes32(vkConfig.circuitHash);
        console.log("EXPECTED_VERIFIER_KEY_HASH:");
        console.logBytes32(computedVerifierKeyHash);
    }
}
