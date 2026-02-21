// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {Test} from "forge-std/Test.sol";

import {Verifier} from "../src/Verifier.sol";
import {Deploy} from "../script/Deploy.s.sol";
import {SettlementVkJson} from "./generated/SettlementVkJson.sol";

contract OwnershipFlowsVerifierTest is Test {
    address private owner = makeAddr("owner");
    address private newOwner = makeAddr("newOwner");
    DeployHarnessOwnership private loader;

    function setUp() external {
        loader = new DeployHarnessOwnership();
    }

    function testVerifierOwnable2Step() external {
        Deploy.VerifyingKeyConfig memory cfg = loader.loadVkJson(string(SettlementVkJson.SETTLEMENT_VK_JSON));
        vm.prank(owner);
        Verifier verifier =
            new Verifier(cfg.alpha1, cfg.beta2, cfg.gamma2, cfg.delta2, cfg.ic, keccak256("vk"), cfg.expectedInputs);
        vm.prank(owner);
        verifier.transferOwnership(newOwner);
        vm.prank(newOwner);
        verifier.acceptOwnership();
        assertEq(verifier.owner(), newOwner);
    }
}

contract DeployHarnessOwnership is Deploy {
    function loadVkJson(string memory json) external pure returns (VerifyingKeyConfig memory) {
        return _loadVerifyingKeyJson(json);
    }
}
