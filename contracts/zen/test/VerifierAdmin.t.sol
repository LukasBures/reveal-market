// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {Test} from "forge-std/Test.sol";

import {Verifier} from "../src/Verifier.sol";
import {Deploy} from "../script/Deploy.s.sol";
import {SettlementVkJson} from "./generated/SettlementVkJson.sol";

contract VerifierAdminTest is Test {
    address private owner = makeAddr("owner");
    address private stranger = makeAddr("stranger");
    DeployHarness private loader;

    function setUp() external {
        loader = new DeployHarness();
    }

    function testSetVerifyingKeyEmitsAndUpdatesCircuitHash() external {
        Verifier verifier = _deployVerifier(keccak256("vk-1"));
        Deploy.VerifyingKeyConfig memory cfg = _vkConfig();
        bytes32 newHash = keccak256("vk-2");

        vm.expectEmit(true, false, false, true, address(verifier));
        emit Verifier.VerifyingKeyUpdated(newHash, 10);
        vm.prank(owner);
        verifier.setVerifyingKey(cfg.alpha1, cfg.beta2, cfg.gamma2, cfg.delta2, cfg.ic, newHash);

        assertEq(verifier.circuitHash(), newHash);
        assertEq(verifier.expectedInputs(), 10);
        assertEq(verifier.icLength(), 11);
    }

    function testSetVerifyingKeyRequiresOwner() external {
        Verifier verifier = _deployVerifier(keccak256("vk-1"));
        Deploy.VerifyingKeyConfig memory cfg = _vkConfig();

        vm.prank(stranger);
        vm.expectRevert();
        verifier.setVerifyingKey(cfg.alpha1, cfg.beta2, cfg.gamma2, cfg.delta2, cfg.ic, keccak256("vk-3"));
    }

    function testSetVerifyingKeyRejectsInfinityPoints() external {
        Verifier verifier = _deployVerifier(keccak256("vk-1"));

        uint256[2] memory alpha1 = [uint256(0), uint256(0)];
        uint256[2][2] memory beta2 = [[uint256(0), uint256(0)], [uint256(0), uint256(0)]];
        uint256[2][2] memory gamma2 = [[uint256(0), uint256(0)], [uint256(0), uint256(0)]];
        uint256[2][2] memory delta2 = [[uint256(0), uint256(0)], [uint256(0), uint256(0)]];
        uint256[2][] memory icPoints = new uint256[2][](11);

        vm.prank(owner);
        vm.expectRevert(Verifier.InvalidCurvePoint.selector);
        verifier.setVerifyingKey(alpha1, beta2, gamma2, delta2, icPoints, keccak256("vk-infinity"));
    }

    function testVerifyProofReturnsFalseOnScalarFieldOverflow() external {
        Verifier verifier = _deployVerifier(keccak256("vk-1"));
        uint256[10] memory signals;
        signals[0] = type(uint256).max;

        bool ok = verifier.verifyProof(new bytes(32 * 8), signals);
        assertFalse(ok, "overflowing public signal must fail");
    }

    function _deployVerifier(bytes32 hash) private returns (Verifier) {
        Deploy.VerifyingKeyConfig memory cfg = _vkConfig();

        vm.prank(owner);
        return new Verifier(cfg.alpha1, cfg.beta2, cfg.gamma2, cfg.delta2, cfg.ic, hash, 10);
    }

    function _vkConfig() private view returns (Deploy.VerifyingKeyConfig memory) {
        return loader.loadVkJson(string(SettlementVkJson.SETTLEMENT_VK_JSON));
    }
}

contract DeployHarness is Deploy {
    function loadVkJson(string memory json) external pure returns (VerifyingKeyConfig memory) {
        return _loadVerifyingKeyJson(json);
    }
}
