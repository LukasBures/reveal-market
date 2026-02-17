// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {Test} from "forge-std/Test.sol";

import {Verifier} from "../src/Verifier.sol";

contract VerifierAdminTest is Test {
    address private owner = makeAddr("owner");
    address private stranger = makeAddr("stranger");

    function testSetVerifyingKeyEmitsAndUpdatesCircuitHash() external {
        Verifier verifier = _deployVerifier(keccak256("vk-1"));

        uint256[2] memory alpha1 = [uint256(11), uint256(12)];
        uint256[2][2] memory beta2 = [[uint256(13), uint256(14)], [uint256(15), uint256(16)]];
        uint256[2][2] memory gamma2 = [[uint256(17), uint256(18)], [uint256(19), uint256(20)]];
        uint256[2][2] memory delta2 = [[uint256(21), uint256(22)], [uint256(23), uint256(24)]];
        uint256[2][] memory icPoints = _icPoints();
        bytes32 newHash = keccak256("vk-2");

        vm.expectEmit(true, false, false, true, address(verifier));
        emit Verifier.VerifyingKeyUpdated(newHash, 10);
        vm.prank(owner);
        verifier.setVerifyingKey(alpha1, beta2, gamma2, delta2, icPoints, newHash);

        assertEq(verifier.circuitHash(), newHash);
        assertEq(verifier.expectedInputs(), 10);
        assertEq(verifier.icLength(), 11);
    }

    function testSetVerifyingKeyRequiresOwner() external {
        Verifier verifier = _deployVerifier(keccak256("vk-1"));

        uint256[2] memory alpha1 = [uint256(11), uint256(12)];
        uint256[2][2] memory beta2 = [[uint256(13), uint256(14)], [uint256(15), uint256(16)]];
        uint256[2][2] memory gamma2 = [[uint256(17), uint256(18)], [uint256(19), uint256(20)]];
        uint256[2][2] memory delta2 = [[uint256(21), uint256(22)], [uint256(23), uint256(24)]];
        uint256[2][] memory icPoints = _icPoints();

        vm.prank(stranger);
        vm.expectRevert();
        verifier.setVerifyingKey(alpha1, beta2, gamma2, delta2, icPoints, keccak256("vk-3"));
    }

    function _deployVerifier(bytes32 hash) private returns (Verifier) {
        uint256[2] memory alpha1 = [uint256(1), uint256(2)];
        uint256[2][2] memory beta2 = [[uint256(3), uint256(4)], [uint256(5), uint256(6)]];
        uint256[2][2] memory gamma2 = [[uint256(7), uint256(8)], [uint256(9), uint256(10)]];
        uint256[2][2] memory delta2 = [[uint256(11), uint256(12)], [uint256(13), uint256(14)]];
        uint256[2][] memory icPoints = _icPoints();

        vm.prank(owner);
        return new Verifier(alpha1, beta2, gamma2, delta2, icPoints, hash, 10);
    }

    function _icPoints() private pure returns (uint256[2][] memory points) {
        points = new uint256[2][](11);
        for (uint256 i = 0; i < points.length; ++i) {
            points[i] = [uint256(100 + i * 2), uint256(101 + i * 2)];
        }
    }
}
