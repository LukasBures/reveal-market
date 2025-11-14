// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

import {Pairing} from "../src/utils/Pairing.sol";

contract PairingHarness {
    function negate(Pairing.G1Point memory p) external pure returns (Pairing.G1Point memory) {
        return Pairing.negate(p);
    }

    function add(Pairing.G1Point memory a, Pairing.G1Point memory b) external view returns (Pairing.G1Point memory) {
        return Pairing.add(a, b);
    }

    function scalarMul(Pairing.G1Point memory p, uint256 s) external view returns (Pairing.G1Point memory) {
        return Pairing.scalarMul(p, s);
    }

    function pairingCheck(Pairing.G1Point[] memory p1, Pairing.G2Point[] memory p2) external view returns (bool) {
        return Pairing.pairing(p1, p2);
    }
}

contract PairingTest is Test {
    PairingHarness private harness;

    function setUp() public {
        harness = new PairingHarness();
    }

    function testNegateOfZeroIsZero() public pure {
        Pairing.G1Point memory infinity = Pairing.pointAtInfinity();
        Pairing.G1Point memory neg = Pairing.negate(infinity);
        assertEq(neg.X, 0);
        assertEq(neg.Y, 0);
    }

    function testNegateRoundTrip() public pure {
        Pairing.G1Point memory p1 = _g1();
        Pairing.G1Point memory neg = Pairing.negate(p1);
        Pairing.G1Point memory back = Pairing.negate(neg);
        assertEq(back.X, p1.X);
        assertEq(back.Y, p1.Y);
    }

    function testScalarMulMatchesRepeatedAddition(uint256 scalar) public view {
        scalar = bound(scalar, 0, 50);
        Pairing.G1Point memory p1 = _g1();
        Pairing.G1Point memory mul = harness.scalarMul(p1, scalar);
        Pairing.G1Point memory accum = Pairing.pointAtInfinity();
        for (uint256 i = 0; i < scalar; ++i) {
            if (accum.X == 0 && accum.Y == 0) {
                accum = p1;
            } else {
                accum = harness.add(accum, p1);
            }
        }
        if (scalar == 0) {
            assertEq(mul.X, 0);
            assertEq(mul.Y, 0);
        } else {
            assertEq(mul.X, accum.X);
            assertEq(mul.Y, accum.Y);
        }
    }

    function _g1() private pure returns (Pairing.G1Point memory) {
        return Pairing.G1Point({X: 1, Y: 2});
    }
}
