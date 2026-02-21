// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {Test} from "forge-std/Test.sol";

import {Deploy} from "../script/Deploy.s.sol";
import {SettlementVkJson} from "./generated/SettlementVkJson.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

contract DeployGuardsTest is Test, Deploy {
    function testRunRejectsCircuitHashMismatchAgainstPinnedValue() external {
        MockERC20 token = new MockERC20();

        vm.setEnv("EXPECTED_CHAIN_ID", vm.toString(block.chainid));
        vm.setEnv("DEPLOYER_KEY", "1");
        vm.setEnv("ORACLE_ADDRESS", vm.toString(makeAddr("oracle")));
        vm.setEnv("AUTHORIZATION_SIGNER", vm.toString(makeAddr("authSigner")));
        vm.setEnv("ZEN_TOKEN_ADDRESS", vm.toString(address(token)));
        vm.setEnv("SETTLEMENT_VK_JSON", string(SettlementVkJson.SETTLEMENT_VK_JSON));
        vm.setEnv("EXPECTED_VERIFIER_KEY_HASH", "0x1111111111111111111111111111111111111111111111111111111111111111");
        vm.setEnv("EXPECTED_CIRCUIT_HASH", "0x2222222222222222222222222222222222222222222222222222222222222222");

        vm.expectRevert(bytes("circuit hash mismatch"));
        this.run();
    }

    function testRunRejectsVerifierKeyHashMismatchAgainstPinnedValue() external {
        MockERC20 token = new MockERC20();
        VerifyingKeyConfig memory vkConfig = _loadVerifyingKeyJson(string(SettlementVkJson.SETTLEMENT_VK_JSON));

        vm.setEnv("EXPECTED_CHAIN_ID", vm.toString(block.chainid));
        vm.setEnv("DEPLOYER_KEY", "1");
        vm.setEnv("ORACLE_ADDRESS", vm.toString(makeAddr("oracle")));
        vm.setEnv("AUTHORIZATION_SIGNER", vm.toString(makeAddr("authSigner")));
        vm.setEnv("ZEN_TOKEN_ADDRESS", vm.toString(address(token)));
        vm.setEnv("SETTLEMENT_VK_JSON", string(SettlementVkJson.SETTLEMENT_VK_JSON));
        vm.setEnv("EXPECTED_CIRCUIT_HASH", vm.toString(vkConfig.circuitHash));
        vm.setEnv("EXPECTED_VERIFIER_KEY_HASH", "0x1111111111111111111111111111111111111111111111111111111111111111");

        vm.expectRevert(bytes("verifier key hash mismatch"));
        this.run();
    }
}
