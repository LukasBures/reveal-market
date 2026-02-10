// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console} from "forge-std/Script.sol";

import {Verifier} from "../src/Verifier.sol";
import {Deploy} from "./Deploy.s.sol";

/// @dev Rotate the verifying key on an existing Verifier contract.
contract RotateVerifierKey is Script {
    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address verifierAddress = vm.envAddress("VERIFIER_ADDRESS");
        string memory vkJson = _envOrString("SETTLEMENT_VK_JSON", "");
        if (bytes(vkJson).length == 0) {
            revert("SETTLEMENT_VK_JSON env var is required");
        }

        Deploy.VerifyingKeyConfig memory vkConfig = _loadVerifyingKeyJson(vkJson);
        Verifier verifier = Verifier(verifierAddress);
        if (vkConfig.expectedInputs != verifier.expectedInputs()) {
            revert("expected inputs mismatch");
        }

        vm.startBroadcast(deployerKey);
        verifier.setVerifyingKey(
            vkConfig.alpha1,
            vkConfig.beta2,
            vkConfig.gamma2,
            vkConfig.delta2,
            vkConfig.ic,
            vkConfig.circuitHash
        );
        vm.stopBroadcast();

        console.log("Verifier:", verifierAddress);
        console.log("Circuit hash:", uint256(vkConfig.circuitHash));
        console.log("Expected inputs:", vkConfig.expectedInputs);
    }

    function _envOrString(string memory key, string memory defaultValue) private view returns (string memory) {
        try vm.envString(key) returns (string memory value) {
            return value;
        } catch {
            return defaultValue;
        }
    }

    function _loadVerifyingKeyJson(string memory json) internal pure returns (Deploy.VerifyingKeyConfig memory config) {
        // Support the canonical zkSync/rapidsnark layout (vk_alpha_1, vk_beta_2, vk_gamma_2, vk_delta_2, IC, circuitHash, expectedInputs).
        config.alpha1 = _readG1(json, ".vk_alpha_1");
        config.beta2 = _readG2(json, ".vk_beta_2");
        config.gamma2 = _readG2(json, ".vk_gamma_2");
        config.delta2 = _readG2(json, ".vk_delta_2");
        config.expectedInputs = _readUint(json, ".expectedInputs");
        config.ic = _readIcPoints(json, ".IC", config.expectedInputs + 1);
        config.circuitHash = abi.decode(vm.parseJson(json, ".circuitHash"), (bytes32));
        return config;
    }

    function _readUint(string memory json, string memory key) private pure returns (uint256) {
        try vm.parseJsonUint(json, key) returns (uint256 numeric) {
            return numeric;
        } catch {
            string memory numericStr = vm.parseJsonString(json, key);
            return vm.parseUint(numericStr);
        }
    }

    function _readUintArray(string memory json, string memory key) private pure returns (uint256[] memory values) {
        try vm.parseJsonUintArray(json, key) returns (uint256[] memory numeric) {
            return numeric;
        } catch {
            string[] memory text = vm.parseJsonStringArray(json, key);
            values = new uint256[](text.length);
            for (uint256 i = 0; i < text.length; ++i) {
                values[i] = vm.parseUint(text[i]);
            }
        }
    }

    function _readUintMatrix(string memory json, string memory key, uint256 rows)
        private
        pure
        returns (uint256[][] memory matrix)
    {
        matrix = new uint256[][](rows);
        for (uint256 i = 0; i < rows; ++i) {
            string memory rowKey = string.concat(key, "[", vm.toString(i), "]");
            matrix[i] = _readUintArray(json, rowKey);
        }
    }

    function _readG1(string memory json, string memory key) private pure returns (uint256[2] memory point) {
        uint256[] memory coords = _readUintArray(json, key);
        require(coords.length >= 2, "invalid g1 coords");
        point[0] = coords[0];
        point[1] = coords[1];
    }

    function _readG2(string memory json, string memory key) private pure returns (uint256[2][2] memory point) {
        uint256[][] memory coords = _readUintMatrix(json, key, 3);
        require(coords.length >= 2 && coords[0].length >= 2 && coords[1].length >= 2, "invalid g2 coords");
        // Swap FQ2 components to match Solidity pairing precompile order.
        point[0][0] = coords[0][1];
        point[0][1] = coords[0][0];
        point[1][0] = coords[1][1];
        point[1][1] = coords[1][0];
    }

    function _readIcPoints(string memory json, string memory key, uint256 expectedLength)
        private
        pure
        returns (uint256[2][] memory points)
    {
        uint256[][] memory coords = _readUintMatrix(json, key, expectedLength);
        points = new uint256[2][](coords.length);
        for (uint256 i = 0; i < coords.length; ++i) {
            require(coords[i].length >= 2, "invalid ic coords");
            points[i][0] = coords[i][0];
            points[i][1] = coords[i][1];
        }
    }
}
