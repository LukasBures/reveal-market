// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";

import {IVerifier} from "./interfaces/IVerifier.sol";
import {Pairing} from "./utils/Pairing.sol";

/**
 * @title Configurable Groth16 verifier
 *
 * This contract wraps the auto-generated pairing logic from snarkjs/Noir with operational features expected in production:
 *   - Verifying keys are stored on-chain and can be rotated by the owner, enabling circuit upgrades without redeploying RevealMarket.
 *   - The verifier enforces a fixed number of public inputs (6) and rejects malformed data before hitting the expensive pairing precompile.
 *   - Instead of reverting on invalid proofs, `verifyProof` simply returns false so the caller (RevealMarket) can raise a domain-specific error.
 *
 * Storage layout:
 *   • `_vk` holds α/β/γ/δ points.
 *   • `_ic` is the input commitment vector, length `expectedInputs + 1`.
 *   • `circuitHash` gives downstream services a way to identify the exact circuit in use.
 *
 * Any consumer should treat this contract as immutable—only the owner may rotate keys.
 */

/// @notice Configurable Groth16 verifier that stores its verifying key on-chain.
contract Verifier is IVerifier, Ownable2Step {
    using Pairing for Pairing.G1Point;

    uint256 private constant MAX_SUPPORTED_INPUTS = 16;

    struct StoredVerifyingKey {
        Pairing.G1Point alfa1;
        Pairing.G2Point beta2;
        Pairing.G2Point gamma2;
        Pairing.G2Point delta2;
    }

    StoredVerifyingKey private _vk;
    Pairing.G1Point[] private _ic;

    bytes32 public circuitHash;
    uint256 public immutable EXPECTED_INPUTS;

    event VerifyingKeyUpdated(bytes32 indexed circuitHash, uint256 inputs);

    error UnsupportedInputCardinality(uint256 requested, uint256 maxSupported);
    error InvalidVerifyingKeyLength(uint256 provided, uint256 expected);
    error VerifyingKeyNotSet();
    error InvalidProofEncoding();
    error FieldOverflow(uint256 value);
    error ProofInputLengthMismatch(uint256 expected, uint256 provided);
    error PairingHelperUnauthorized();

    constructor(
        uint256[2] memory alpha1,
        uint256[2][2] memory beta2,
        uint256[2][2] memory gamma2,
        uint256[2][2] memory delta2,
        uint256[2][] memory icPoints,
        bytes32 circuitHash_,
        uint256 expectedInputs_
    ) Ownable(msg.sender) {
        if (expectedInputs_ == 0) revert InvalidVerifyingKeyLength(0, 1);
        if (expectedInputs_ > MAX_SUPPORTED_INPUTS) {
            revert UnsupportedInputCardinality(expectedInputs_, MAX_SUPPORTED_INPUTS);
        }
        EXPECTED_INPUTS = expectedInputs_;
        _setVerifyingKey(alpha1, beta2, gamma2, delta2, icPoints, circuitHash_);
    }

    /// @notice Allows the owner to rotate the verifying key (e.g., on circuit upgrade).
    function setVerifyingKey(
        uint256[2] memory alpha1,
        uint256[2][2] memory beta2,
        uint256[2][2] memory gamma2,
        uint256[2][2] memory delta2,
        uint256[2][] memory icPoints,
        bytes32 circuitHash_
    ) external onlyOwner {
        _setVerifyingKey(alpha1, beta2, gamma2, delta2, icPoints, circuitHash_);
    }

    /// @inheritdoc IVerifier
    function verifyProof(bytes calldata proofData, uint256[10] calldata pubSignals) external view override returns (bool) {
        if (_ic.length == 0) revert VerifyingKeyNotSet();
        if (pubSignals.length != EXPECTED_INPUTS) {
            revert ProofInputLengthMismatch(EXPECTED_INPUTS, pubSignals.length);
        }

        Proof memory proof = _decodeProof(proofData);
        _validateG1Point(proof.A);
        _validateG2Point(proof.B);
        _validateG1Point(proof.C);

        Pairing.G1Point memory vkx = _ic[0];
        for (uint256 i = 0; i < EXPECTED_INPUTS; ++i) {
            Pairing.G1Point memory term = Pairing.scalarMul(_ic[i + 1], pubSignals[i]);
            vkx = Pairing.add(vkx, term);
        }

        try this._pairingCheck(proof, vkx) returns (bool ok) {
            return ok;
        } catch {
            return false;
        }
    }

    /// @notice Returns the stored IC length (including the constant term).
    function icLength() external view returns (uint256) {
        return _ic.length;
    }

    struct Proof {
        Pairing.G1Point A;
        Pairing.G2Point B;
        Pairing.G1Point C;
    }

    function _setVerifyingKey(
        uint256[2] memory alpha1,
        uint256[2][2] memory beta2,
        uint256[2][2] memory gamma2,
        uint256[2][2] memory delta2,
        uint256[2][] memory icPoints,
        bytes32 circuitHash_
    ) private {
        if (icPoints.length != EXPECTED_INPUTS + 1) {
            revert InvalidVerifyingKeyLength(icPoints.length, EXPECTED_INPUTS + 1);
        }
        _vk.alfa1 = _buildG1(alpha1);
        _vk.beta2 = _buildG2(beta2);
        _vk.gamma2 = _buildG2(gamma2);
        _vk.delta2 = _buildG2(delta2);

        delete _ic;
        _ic = new Pairing.G1Point[](icPoints.length);
        for (uint256 i = 0; i < icPoints.length; ++i) {
            _ic[i] = _buildG1(icPoints[i]);
        }
        circuitHash = circuitHash_;
        emit VerifyingKeyUpdated(circuitHash_, EXPECTED_INPUTS);
    }

    function _decodeProof(bytes calldata data) private pure returns (Proof memory proof) {
        if (data.length != 32 * 8) revert InvalidProofEncoding();
        (uint256[2] memory a, uint256[2][2] memory b, uint256[2] memory c) =
            abi.decode(data, (uint256[2], uint256[2][2], uint256[2]));
        proof.A = _buildG1(a);
        proof.B = _buildG2(b);
        proof.C = _buildG1(c);
        return proof;
    }

    function _buildG1(uint256[2] memory coords) private pure returns (Pairing.G1Point memory) {
        _validateFieldElement(coords[0]);
        _validateFieldElement(coords[1]);
        return Pairing.G1Point(coords[0], coords[1]);
    }

    function _buildG2(uint256[2][2] memory coords) private pure returns (Pairing.G2Point memory) {
        _validateFieldElement(coords[0][0]);
        _validateFieldElement(coords[0][1]);
        _validateFieldElement(coords[1][0]);
        _validateFieldElement(coords[1][1]);
        return Pairing.G2Point([coords[0][0], coords[0][1]], [coords[1][0], coords[1][1]]);
    }

    function _validateG1Point(Pairing.G1Point memory point) private pure {
        if (point.X == 0 && point.Y == 0) {
            return;
        }
        _validateFieldElement(point.X);
        _validateFieldElement(point.Y);
    }

    function _validateG2Point(Pairing.G2Point memory point) private pure {
        if (
            point.X[0] == 0 && point.X[1] == 0 && point.Y[0] == 0 && point.Y[1] == 0
        ) {
            return;
        }
        _validateFieldElement(point.X[0]);
        _validateFieldElement(point.X[1]);
        _validateFieldElement(point.Y[0]);
        _validateFieldElement(point.Y[1]);
    }

    function _pairingCheck(Proof memory proof, Pairing.G1Point memory vkx) external view returns (bool) {
        if (msg.sender != address(this)) revert PairingHelperUnauthorized();
        return
            Pairing.pairingProd4(
                Pairing.negate(proof.A),
                proof.B,
                _vk.alfa1,
                _vk.beta2,
                vkx,
                _vk.gamma2,
                proof.C,
                _vk.delta2
            );
    }

    function _validateFieldElement(uint256 value) private pure {
        if (value >= Pairing.PRIME_Q) {
            revert FieldOverflow(value);
        }
    }
}
