// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

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
        assertEq(config.ic[0][0], 19497960300567760639660261670012584085507675705850371475691093687439179069054);
        assertEq(config.ic[10][1], 8223598890083111104239146542008747113584684453192694534904016914676203259216);
    }

    function testLoadVerifyingKeyRejectsOverlongG1Array() external {
        vm.expectRevert(bytes("invalid g1 coords"));
        this.loadVkJson(_minimalVkJson(true, false));
    }

    function testLoadVerifyingKeyRejectsOverlongIcRow() external {
        vm.expectRevert(bytes("invalid ic coords"));
        this.loadVkJson(_minimalVkJson(false, true));
    }

    function loadVkJson(string memory json) external pure returns (VerifyingKeyConfig memory) {
        return _loadVerifyingKeyJson(json);
    }

    function _minimalVkJson(bool overlongG1, bool overlongIcRow) private pure returns (string memory) {
        string memory alpha = overlongG1 ? "[\"1\",\"2\",\"1\",\"9\"]" : "[\"1\",\"2\",\"1\"]";
        string memory ic0 = overlongIcRow ? "[\"11\",\"12\",\"1\",\"7\"]" : "[\"11\",\"12\",\"1\"]";
        return string.concat(
            "{\"vk_alpha_1\":",
            alpha,
            ",\"vk_beta_2\":[[\"1\",\"2\"],[\"3\",\"4\"],[\"1\",\"0\"]]",
            ",\"vk_gamma_2\":[[\"1\",\"2\"],[\"3\",\"4\"],[\"1\",\"0\"]]",
            ",\"vk_delta_2\":[[\"1\",\"2\"],[\"3\",\"4\"],[\"1\",\"0\"]]",
            ",\"expectedInputs\":1",
            ",\"IC\":[",
            ic0,
            ",[\"13\",\"14\",\"1\"]]",
            ",\"circuitHash\":\"0x00000000000000000000000000000000000000000000000000000000000000aa\"}"
        );
    }
}
