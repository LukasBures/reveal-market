// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

/// @notice Minimal pairing library for BN254-based Groth16 verification.
/// @dev Adapted from the contracts produced by circom/snarkjs (MIT licensed). Exposed as a standalone library so both the
///      production verifier and unit tests can exercise the same primitives (G1/G2 negation, addition, scalar multiplication, pairing checks).
library Pairing {
    // BN254 base field prime (q) used for curve coordinates and pairing checks.
    uint256 internal constant PRIME_Q = 21888242871839275222246405745257275088696311157297823662689037894645226208583;
    uint256 private constant G1_GENERATOR_X = 1;
    uint256 private constant G1_GENERATOR_Y = 2;

    struct G1Point {
        uint256 X;
        uint256 Y;
    }

    struct G2Point {
        uint256[2] X;
        uint256[2] Y;
    }

    /// @notice Returns the point at infinity for G1.
    function pointAtInfinity() internal pure returns (G1Point memory) {
        return G1Point({X: 0, Y: 0});
    }

    /// @notice Negates a G1 point.
    function negate(G1Point memory p) internal pure returns (G1Point memory) {
        if (p.X == 0 && p.Y == 0) {
            return pointAtInfinity();
        }
        return G1Point({X: p.X, Y: PRIME_Q - (p.Y % PRIME_Q)});
    }

    /// @notice Adds two G1 points using the bn128 addition precompile.
    function add(G1Point memory p1, G1Point memory p2) internal view returns (G1Point memory r) {
        uint256[4] memory input;
        input[0] = p1.X;
        input[1] = p1.Y;
        input[2] = p2.X;
        input[3] = p2.Y;
        bool success;
        assembly ("memory-safe") {
            success := staticcall(gas(), 0x06, input, 0x80, r, 0x40)
        }
        require(success, "Pairing: add failed");
    }

    /// @notice Performs scalar multiplication on a G1 point via precompile.
    function scalarMul(G1Point memory p, uint256 s) internal view returns (G1Point memory r) {
        uint256[3] memory input;
        input[0] = p.X;
        input[1] = p.Y;
        input[2] = s;
        bool success;
        assembly ("memory-safe") {
            success := staticcall(gas(), 0x07, input, 0x60, r, 0x40)
        }
        require(success, "Pairing: scalar mul failed");
    }

    /// @notice Performs a pairing check on supplied points.
    function pairing(G1Point[] memory p1, G2Point[] memory p2) internal view returns (bool) {
        require(p1.length == p2.length, "Pairing: point length mismatch");
        uint256 elements = p1.length;
        uint256 inputSize = elements * 6;
        uint256[] memory input = new uint256[](inputSize);
        for (uint256 i = 0; i < elements; ++i) {
            uint256 j = i * 6;
            input[j + 0] = p1[i].X;
            input[j + 1] = p1[i].Y;
            input[j + 2] = p2[i].X[0];
            input[j + 3] = p2[i].X[1];
            input[j + 4] = p2[i].Y[0];
            input[j + 5] = p2[i].Y[1];
        }
        uint256[1] memory out;
        bool success;
        assembly ("memory-safe") {
            success := staticcall(gas(), 0x08, add(input, 0x20), mul(inputSize, 0x20), out, 0x20)
        }
        require(success, "Pairing: pairing op failed");
        return out[0] != 0;
    }

    /// @notice Convenience wrapper for four pairings.
    function pairingProd4(
        G1Point memory a1,
        G2Point memory a2,
        G1Point memory b1,
        G2Point memory b2,
        G1Point memory c1,
        G2Point memory c2,
        G1Point memory d1,
        G2Point memory d2
    ) internal view returns (bool) {
        G1Point[] memory p1 = new G1Point[](4);
        G2Point[] memory p2 = new G2Point[](4);
        p1[0] = a1;
        p1[1] = b1;
        p1[2] = c1;
        p1[3] = d1;
        p2[0] = a2;
        p2[1] = b2;
        p2[2] = c2;
        p2[3] = d2;
        return pairing(p1, p2);
    }

    /// @notice Validates that a G1 point is accepted by the precompile.
    function isValidG1Point(G1Point memory p) internal view returns (bool) {
        if (p.X == 0 && p.Y == 0) {
            return true;
        }
        uint256[3] memory input;
        input[0] = p.X;
        input[1] = p.Y;
        input[2] = 1;
        uint256[2] memory out;
        bool success;
        assembly ("memory-safe") {
            success := staticcall(gas(), 0x07, input, 0x60, out, 0x40)
        }
        return success;
    }

    /// @notice Validates that a G2 point is accepted by the pairing precompile.
    function isValidG2Point(G2Point memory p) internal view returns (bool) {
        if (p.X[0] == 0 && p.X[1] == 0 && p.Y[0] == 0 && p.Y[1] == 0) {
            return true;
        }
        uint256[6] memory input;
        input[0] = G1_GENERATOR_X;
        input[1] = G1_GENERATOR_Y;
        input[2] = p.X[0];
        input[3] = p.X[1];
        input[4] = p.Y[0];
        input[5] = p.Y[1];
        uint256[1] memory out;
        bool success;
        assembly ("memory-safe") {
            success := staticcall(gas(), 0x08, input, 0xc0, out, 0x20)
        }
        return success;
    }
}
