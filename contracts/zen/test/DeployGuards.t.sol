// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {Test} from "forge-std/Test.sol";

import {Deploy} from "../script/Deploy.s.sol";
import {SettlementVkJson} from "./generated/SettlementVkJson.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

contract DeployGuardsTest is Test, Deploy {
    function _setEnv(string memory key, string memory value) private {
        // forge-lint: disable-next-line(unsafe-cheatcode)
        vm.setEnv(key, value);
    }

    function testRunRejectsCircuitHashMismatchAgainstPinnedValue() external {
        MockERC20 token = new MockERC20();

        _setEnv("DEPLOYER_KEY", "1");
        _setEnv("ORACLE_ADDRESS", vm.toString(makeAddr("oracle")));
        _setEnv("AUTHORIZATION_SIGNER", vm.toString(makeAddr("authSigner")));
        _setEnv("ZEN_TOKEN_ADDRESS", vm.toString(address(token)));
        _setEnv("SETTLEMENT_VK_JSON", string(SettlementVkJson.SETTLEMENT_VK_JSON));
        _setEnv("EXPECTED_VERIFIER_KEY_HASH", "0x1111111111111111111111111111111111111111111111111111111111111111");
        _setEnv("EXPECTED_CIRCUIT_HASH", "0x2222222222222222222222222222222222222222222222222222222222222222");
        _setEnv("EXPECTED_CHAIN_ID", vm.toString(block.chainid));

        vm.expectRevert(bytes("circuit hash mismatch"));
        this.run();
    }

    function testRunRejectsVerifierKeyHashMismatchAgainstPinnedValue() external {
        MockERC20 token = new MockERC20();
        VerifyingKeyConfig memory vkConfig = _loadVerifyingKeyJson(string(SettlementVkJson.SETTLEMENT_VK_JSON));

        _setEnv("DEPLOYER_KEY", "1");
        _setEnv("ORACLE_ADDRESS", vm.toString(makeAddr("oracle")));
        _setEnv("AUTHORIZATION_SIGNER", vm.toString(makeAddr("authSigner")));
        _setEnv("ZEN_TOKEN_ADDRESS", vm.toString(address(token)));
        _setEnv("SETTLEMENT_VK_JSON", string(SettlementVkJson.SETTLEMENT_VK_JSON));
        _setEnv("EXPECTED_CIRCUIT_HASH", vm.toString(vkConfig.circuitHash));
        _setEnv("EXPECTED_VERIFIER_KEY_HASH", "0x1111111111111111111111111111111111111111111111111111111111111111");
        _setEnv("EXPECTED_CHAIN_ID", vm.toString(block.chainid));

        vm.expectRevert(bytes("verifier key hash mismatch"));
        this.run();
    }
}
