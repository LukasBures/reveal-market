// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {Test} from "forge-std/Test.sol";

import {RotateVerifierKey} from "../script/RotateVerifierKey.s.sol";
import {MockVerifier} from "./mocks/MockVerifier.sol";
import {SettlementVkJson} from "./generated/SettlementVkJson.sol";

contract RotateVerifierKeyGuardsTest is Test {
    function _setEnv(string memory key, string memory value) private {
        // forge-lint: disable-next-line(unsafe-cheatcode)
        vm.setEnv(key, value);
    }

    function testRunRevertsOnWrongChainId() external {
        RotateVerifierKey rotate = new RotateVerifierKey();
        _setEnv("EXPECTED_CHAIN_ID", vm.toString(block.chainid + 1));

        vm.expectRevert(bytes("Wrong chain id"));
        rotate.run();
    }

    function testRunRejectsCircuitHashMismatchAgainstPinnedValue() external {
        RotateVerifierKey rotate = new RotateVerifierKey();
        MockVerifier verifier = new MockVerifier(keccak256("different-circuit"));
        bytes32 wrongCircuitHash = keccak256("wrong-circuit-hash");

        _setEnv("EXPECTED_CHAIN_ID", vm.toString(block.chainid));
        _setEnv("DEPLOYER_KEY", "1");
        _setEnv("VERIFIER_ADDRESS", vm.toString(address(verifier)));
        _setEnv("SETTLEMENT_VK_JSON", string(SettlementVkJson.SETTLEMENT_VK_JSON));
        _setEnv("EXPECTED_VERIFIER_KEY_HASH", "0x1111111111111111111111111111111111111111111111111111111111111111");
        _setEnv("EXPECTED_CIRCUIT_HASH", vm.toString(wrongCircuitHash));

        vm.expectRevert(bytes("circuit hash mismatch"));
        rotate.run();
    }
}
