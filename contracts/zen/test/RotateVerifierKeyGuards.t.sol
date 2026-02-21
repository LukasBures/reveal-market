// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {Test} from "forge-std/Test.sol";

import {RotateVerifierKey} from "../script/RotateVerifierKey.s.sol";
import {MockVerifier} from "./mocks/MockVerifier.sol";
import {SettlementVkJson} from "./generated/SettlementVkJson.sol";

contract RotateVerifierKeyGuardsTest is Test {
    function testRunRevertsOnWrongChainId() external {
        RotateVerifierKey rotate = new RotateVerifierKey();
        vm.setEnv("EXPECTED_CHAIN_ID", vm.toString(block.chainid + 1));

        vm.expectRevert(bytes("Wrong chain id"));
        rotate.run();
    }

    function testRunRejectsCircuitHashMismatchAgainstPinnedValue() external {
        RotateVerifierKey rotate = new RotateVerifierKey();
        MockVerifier verifier = new MockVerifier(keccak256("different-circuit"));

        vm.setEnv("EXPECTED_CHAIN_ID", vm.toString(block.chainid));
        vm.setEnv("DEPLOYER_KEY", "1");
        vm.setEnv("VERIFIER_ADDRESS", vm.toString(address(verifier)));
        vm.setEnv("SETTLEMENT_VK_JSON", string(SettlementVkJson.SETTLEMENT_VK_JSON));
        vm.setEnv("EXPECTED_VERIFIER_KEY_HASH", "0x1111111111111111111111111111111111111111111111111111111111111111");
        vm.setEnv("EXPECTED_CIRCUIT_HASH", vm.toString(verifier.circuitHash()));

        vm.expectRevert(bytes("circuit hash mismatch"));
        rotate.run();
    }
}
