// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {Deploy} from "../script/Deploy.s.sol";
import {Pairing} from "../src/utils/Pairing.sol";
import {SettlementVkJson} from "./generated/SettlementVkJson.sol";

/// @dev Ensures the deploy script can read the cached verifying key JSON (string encoded coordinates).
contract DeployVerifyingKeyLoadTest is Test, Deploy {
    function testLoadSettlementVkJson() external pure {
        string memory json = string(SettlementVkJson.SETTLEMENT_VK_JSON);
        VerifyingKeyConfig memory config = _loadVerifyingKeyJson(json);

        assertEq(config.expectedInputs, 10);
        assertEq(config.ic.length, 11);
        assertLt(config.alpha1[0], Pairing.PRIME_Q);
        assertLt(config.ic[0][1], Pairing.PRIME_Q);

        assertEq(config.alpha1[0], 20491192805390485299153009773594534940189261866228447918068658471970481763042);
        assertEq(config.beta2[1][1], 10505242626370262277552901082094356697409835680220590971873171140371331206856);
        assertEq(config.ic[0][0], 15091612243985784952927904334887453352283290208100772621720886306779230304984);
        assertEq(config.ic[10][1], 1131303110679354422192895392097385708213320203841048318146227852313491253724);
    }
}
