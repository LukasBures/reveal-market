// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {Script, console} from "forge-std/Script.sol";

import {Verifier} from "../src/Verifier.sol";
import {Deploy} from "./Deploy.s.sol";

/// @dev Rotate the verifying key on an existing Verifier contract.
contract RotateVerifierKey is Script {
    function run() external {
        uint256 expectedChainId = _loadExpectedChainId();
        if (block.chainid != expectedChainId) {
            revert("Wrong chain id");
        }
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address verifierAddress = vm.envAddress("VERIFIER_ADDRESS");
        string memory vkJson = _envOrString("SETTLEMENT_VK_JSON", "");
        if (bytes(vkJson).length == 0) {
            revert("SETTLEMENT_VK_JSON env var is required");
        }
        bytes32 expectedVerifierKeyHash = _loadEnvBytes32("EXPECTED_VERIFIER_KEY_HASH");
        bytes32 expectedCircuitHash = _loadEnvBytes32("EXPECTED_CIRCUIT_HASH");
        bytes32 expectedCurrentVerifierKeyHash = _envOrBytes32("EXPECTED_CURRENT_VERIFIER_KEY_HASH", bytes32(0));

        Deploy.VerifyingKeyConfig memory vkConfig = _loadVerifyingKeyJson(vkJson);
        Verifier verifier = Verifier(verifierAddress);
        if (vkConfig.expectedInputs != verifier.expectedInputs()) {
            revert("expected inputs mismatch");
        }
        if (
            expectedCurrentVerifierKeyHash != bytes32(0)
                && verifier.verifyingKeyHash() != expectedCurrentVerifierKeyHash
        ) {
            revert("current verifier key hash mismatch");
        }
        if (vkConfig.circuitHash != expectedCircuitHash) {
            revert("circuit hash mismatch");
        }
        bytes32 computedVerifierKeyHash = keccak256(
            abi.encode(
                vkConfig.alpha1,
                vkConfig.beta2,
                vkConfig.gamma2,
                vkConfig.delta2,
                vkConfig.ic,
                vkConfig.circuitHash,
                vkConfig.expectedInputs
            )
        );
        if (computedVerifierKeyHash != expectedVerifierKeyHash) {
            revert("verifier key hash mismatch");
        }

        vm.startBroadcast(deployerKey);
        verifier.setVerifyingKey(
            vkConfig.alpha1, vkConfig.beta2, vkConfig.gamma2, vkConfig.delta2, vkConfig.ic, vkConfig.circuitHash
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

    function _envOrBytes32(string memory key, bytes32 defaultValue) private view returns (bytes32) {
        try vm.envBytes32(key) returns (bytes32 value) {
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
        bool validAffine = coords.length == 2;
        bool validProjective = coords.length == 3 && coords[2] == 1;
        require(validAffine || validProjective, "invalid g1 coords");
        point[0] = coords[0];
        point[1] = coords[1];
        if (_hasArrayEntry(json, key, 3)) revert("invalid g1 coords");
    }

    function _readG2(string memory json, string memory key) private pure returns (uint256[2][2] memory point) {
        uint256[] memory x = _readUintArray(json, string.concat(key, "[0]"));
        uint256[] memory y = _readUintArray(json, string.concat(key, "[1]"));
        require(x.length == 2 && y.length == 2, "invalid g2 coords");
        if (_hasArrayEntry(json, key, 2)) {
            uint256[] memory z = _readUintArray(json, string.concat(key, "[2]"));
            require(z.length == 2 && z[0] == 1 && z[1] == 0, "invalid g2 coords");
            if (_hasArrayEntry(json, key, 3)) revert("invalid g2 coords");
        }
        // Swap FQ2 components to match Solidity pairing precompile order.
        point[0][0] = x[1];
        point[0][1] = x[0];
        point[1][0] = y[1];
        point[1][1] = y[0];
    }

    function _readIcPoints(string memory json, string memory key, uint256 expectedLength)
        private
        pure
        returns (uint256[2][] memory points)
    {
        uint256[][] memory coords = _readUintMatrix(json, key, expectedLength);
        points = new uint256[2][](coords.length);
        for (uint256 i = 0; i < coords.length; ++i) {
            bool validAffine = coords[i].length == 2;
            bool validProjective = coords[i].length == 3 && coords[i][2] == 1;
            require(validAffine || validProjective, "invalid ic coords");
            points[i][0] = coords[i][0];
            points[i][1] = coords[i][1];
        }
        if (_hasArrayEntry(json, key, expectedLength)) revert("invalid ic coords");
    }

    function _hasArrayEntry(string memory json, string memory key, uint256 index) private pure returns (bool) {
        string memory candidate = string.concat(key, "[", vm.toString(index), "]");
        try vm.parseJsonUint(json, candidate) returns (uint256) {
            return true;
        } catch {}
        try vm.parseJsonString(json, candidate) returns (string memory) {
            return true;
        } catch {}
        try vm.parseJsonUintArray(json, candidate) returns (uint256[] memory) {
            return true;
        } catch {}
        try vm.parseJsonStringArray(json, candidate) returns (string[] memory) {
            return true;
        } catch {
            return false;
        }
    }

    function _loadExpectedChainId() private view returns (uint256) {
        try vm.envUint("EXPECTED_CHAIN_ID") returns (uint256 chainId) {
            return chainId;
        } catch {
            try vm.envUint("CHAIN_ID") returns (uint256 fallbackChainId) {
                return fallbackChainId;
            } catch {
                revert("EXPECTED_CHAIN_ID (or CHAIN_ID) is required");
            }
        }
    }

    function _loadEnvBytes32(string memory key) private view returns (bytes32) {
        try vm.envBytes32(key) returns (bytes32 value) {
            return value;
        } catch {
            revert(string.concat(key, " is required"));
        }
    }
}
