// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

import {Verifier} from "../src/Verifier.sol";

contract OwnershipFlowsVerifierTest is Test {
    address private owner = makeAddr("owner");
    address private newOwner = makeAddr("newOwner");

    function testVerifierOwnable2Step() external {
        uint256[2] memory alpha1 = [uint256(1), uint256(2)];
        uint256[2][2] memory beta2 = [[uint256(1), uint256(2)], [uint256(3), uint256(4)]];
        uint256[2][2] memory gamma2 = [[uint256(5), uint256(6)], [uint256(7), uint256(8)]];
        uint256[2][2] memory delta2 = [[uint256(9), uint256(10)], [uint256(11), uint256(12)]];
        uint256[2][] memory icPoints = new uint256[2][](11);
        for (uint256 i = 0; i < icPoints.length; ++i) {
            icPoints[i] = [uint256(100 + i * 2), uint256(101 + i * 2)];
        }
        vm.prank(owner);
        Verifier verifier = new Verifier(alpha1, beta2, gamma2, delta2, icPoints, keccak256("vk"), 10);
        vm.prank(owner);
        verifier.transferOwnership(newOwner);
        vm.prank(newOwner);
        verifier.acceptOwnership();
        assertEq(verifier.owner(), newOwner);
    }
}
