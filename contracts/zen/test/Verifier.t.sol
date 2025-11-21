// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

import {Pairing} from "../src/utils/Pairing.sol";
import {Verifier} from "../src/Verifier.sol";
import {VerifierStub} from "../src/verifiers/VerifierStub.sol";

contract VerifierStubTest is Test {
    VerifierStub private verifier;

    function setUp() public {
        verifier = new VerifierStub();
    }

    function testVerifyProofAlwaysSucceeds() public {
        uint256[10] memory pubSignals;
        bool success = verifier.verifyProof(bytes(""), pubSignals);
        assertTrue(success);
    }

    function testVerifyProofEmitsEvent() public {
        uint256[10] memory pubSignals;
        vm.expectEmit(true, true, false, true);
        emit VerifierStub.ProofChecked(true, address(this));
        verifier.verifyProof(bytes(""), pubSignals);
    }
}

contract Groth16VerifierTest is Test {
    uint256 private constant FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617;
    Verifier private verifier;

    function setUp() public {
        (
            uint256[2] memory alpha1,
            uint256[2][2] memory beta2,
            uint256[2][2] memory gamma2,
            uint256[2][2] memory delta2,
            uint256[2][] memory ic
        ) = _demoVerifyingKey();
        verifier = new Verifier(alpha1, beta2, gamma2, delta2, ic, keccak256("demo"), 10);
    }

    function testVerifyProofFailsWithMalformedBytes() public {
        uint256[10] memory signals = _demoSignals();
        vm.expectRevert(Verifier.InvalidProofEncoding.selector);
        verifier.verifyProof(hex"1234", signals);
    }

    function testVerifyProofReturnsFalseForInvalidProof() public view {
        uint256[10] memory signals = _demoSignals();
        bool success = verifier.verifyProof(new bytes(32 * 8), signals);
        assertFalse(success);
    }

    function testSetVerifyingKeyRejectsMismatchedIC() public {
        uint256[2][] memory ic = new uint256[2][](2);
        ic[0] = [uint256(1), uint256(2)];
        ic[1] = [uint256(1), uint256(2)];
        vm.expectRevert(abi.encodeWithSelector(Verifier.InvalidVerifyingKeyLength.selector, 2, 11));
        bytes32 altHash = keccak256(bytes("alt"));
        verifier.setVerifyingKey([uint256(1), uint256(2)], _g2(), _g2(), _g2(), ic, altHash);
    }

    function testSetVerifyingKeyEmitsEvent() public {
        (, , , , uint256[2][] memory ic) = _demoVerifyingKey();
        vm.expectEmit(true, false, false, true);
        bytes32 updatedHash = keccak256(bytes("updated"));
        emit Verifier.VerifyingKeyUpdated(updatedHash, 10);
        verifier.setVerifyingKey([uint256(1), uint256(2)], _g2(), _g2(), _g2(), ic, updatedHash);
    }

    function testSetVerifyingKeyRevertsOnFieldOverflow() public {
        (, , , , uint256[2][] memory ic) = _demoVerifyingKey();
        uint256[2] memory badAlpha = [FIELD, uint256(1)];
        vm.expectRevert(abi.encodeWithSelector(Verifier.FieldOverflow.selector, FIELD));
        bytes32 badHash = keccak256(bytes("bad"));
        verifier.setVerifyingKey(badAlpha, _g2(), _g2(), _g2(), ic, badHash);
    }

    function testPairingHelperUnauthorizedReverts() public {
        Verifier.Proof memory emptyProof;
        vm.expectRevert(Verifier.PairingHelperUnauthorized.selector);
        verifier._pairingCheck(emptyProof, Pairing.G1Point({X: 0, Y: 0}));
    }

    function testConstructorRevertsWhenInputsExceedLimit() public {
        uint256[2][] memory ic = new uint256[2][](18);
        for (uint256 i = 0; i < ic.length; ++i) {
            ic[i] = [uint256(1), uint256(2)];
        }
        vm.expectRevert(abi.encodeWithSelector(Verifier.UnsupportedInputCardinality.selector, 17, 16));
        new Verifier([uint256(1), uint256(2)], _g2(), _g2(), _g2(), ic, keccak256("too-many"), 17);
    }

    function _demoVerifyingKey()
        private
        pure
        returns (
            uint256[2] memory,
            uint256[2][2] memory,
            uint256[2][2] memory,
            uint256[2][2] memory,
            uint256[2][] memory
        )
    {
        uint256[2][] memory ic = new uint256[2][](11);
        for (uint256 i = 0; i < ic.length; ++i) {
            ic[i] = [uint256(1), uint256(2)];
        }
        return ([uint256(1), uint256(2)], _g2(), _g2(), _g2(), ic);
    }

    function _demoSignals() private pure returns (uint256[10] memory signals) {
        signals[0] = 10;
        signals[1] = 20;
        signals[2] = 30;
        signals[3] = 2;
        signals[4] = 123;
        signals[5] = uint256(keccak256("outcome")) % FIELD;
        signals[6] = 1;
        signals[7] = 42;
        signals[8] = 0;
        signals[9] = 0;
    }

    function _g2() private pure returns (uint256[2][2] memory point) {
        point[0][0] = 10857046999023057135944570725244913614418924822909023963942422418144186054646;
        point[0][1] = 11559732032986387107991004021392285783925812861821192530917403151452391805634;
        point[1][0] = 8495653923123431417604973247489272438418190587263600148770280649306958101930;
        point[1][1] = 4082367875863433681332203403145435568316851327593401208105741076214120093531;
    }
}
