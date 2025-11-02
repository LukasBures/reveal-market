// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

import {Verifier} from "../src/Verifier.sol";

contract VerifierTest is Test {
    Verifier private verifier;

    function setUp() public {
        verifier = new Verifier();
    }

    function testVerifyProofAlwaysSucceeds() public {
        uint256[4] memory pubSignals;
        bool success = verifier.verifyProof(bytes(""), pubSignals);
        assertTrue(success);
    }

    function testVerifyProofEmitsEvent() public {
        uint256[4] memory pubSignals;
        vm.expectEmit(true, false, false, true);
        emit Verifier.ProofChecked(true, address(this));
        verifier.verifyProof(bytes(""), pubSignals);
    }
}
