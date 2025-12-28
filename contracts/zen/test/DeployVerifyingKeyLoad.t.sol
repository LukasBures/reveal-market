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
        assertEq(config.beta2[1][1], 21847035105528745403288232691147584728191162732299865338377159692350059136679);
        assertEq(config.ic[0][0], 10225823287247248393444608432892982583186254041613184388450850785018558239998);
        assertEq(config.ic[10][1], 10363785078337021957266324160935166062316631311818703261827694221932035444241);
    }
}
