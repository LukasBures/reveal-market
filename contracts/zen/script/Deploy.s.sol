// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console} from "forge-std/Script.sol";

import {MarketFactory} from "../src/MarketFactory.sol";
import {ProtocolPool} from "../src/ProtocolPool.sol";
import {RelayerEscrow} from "../src/RelayerEscrow.sol";
import {RevealMarket} from "../src/RevealMarket.sol";
import {Verifier} from "../src/Verifier.sol";
import {IVerifier} from "../src/interfaces/IVerifier.sol";

/// @dev Minimal stub verifier for test deployments.
contract StubVerifier is IVerifier {
    bytes32 public override circuitHash;

    constructor(bytes32 circuitHash_) {
        circuitHash = circuitHash_;
    }

    function expectedInputs() external pure override returns (uint256) {
        return 10;
    }

    function verifyProof(bytes calldata, uint256[10] calldata) external pure override returns (bool) {
        return true;
    }
}

    contract Deploy is Script {
        struct VerifyingKeyConfig {
            uint256[2] alpha1;
            uint256[2][2] beta2;
            uint256[2][2] gamma2;
            uint256[2][2] delta2;
            uint256[2][] ic;
            bytes32 circuitHash;
            uint256 expectedInputs;
        }

        function run() external {
            uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
            address deployer = vm.addr(deployerKey);
            address oracle = vm.envAddress("ORACLE_ADDRESS");
            address authSigner = vm.envAddress("AUTHORIZATION_SIGNER");
            bool useStubVerifier = _envOrUint("USE_STUB_VERIFIER", 0) == 1;
            string memory vkJson = _envOrString("SETTLEMENT_VK_JSON", "");

            vm.startBroadcast(deployerKey);

            ProtocolPool protocolPool = new ProtocolPool(deployer);
            RelayerEscrow relayerEscrow = new RelayerEscrow(deployer);
            RevealMarket implementation = new RevealMarket();

            address verifierAddress;
            bytes32 circuitHash;
            uint256 expectedInputs;
            if (useStubVerifier) {
                StubVerifier stub = new StubVerifier(bytes32(0));
                verifierAddress = address(stub);
                circuitHash = stub.circuitHash();
                expectedInputs = stub.expectedInputs();
            } else {
                if (bytes(vkJson).length == 0) {
                    revert("SETTLEMENT_VK_JSON env var is required when USE_STUB_VERIFIER=0");
                }
                VerifyingKeyConfig memory vkConfig = _loadVerifyingKeyJson(vkJson);
                Verifier verifier = new Verifier(
                    vkConfig.alpha1,
                    vkConfig.beta2,
                    vkConfig.gamma2,
                    vkConfig.delta2,
                    vkConfig.ic,
                    vkConfig.circuitHash,
                    vkConfig.expectedInputs
                );
                verifierAddress = address(verifier);
                circuitHash = vkConfig.circuitHash;
                expectedInputs = vkConfig.expectedInputs;
            }

            MarketFactory factory = new MarketFactory(address(implementation), protocolPool, relayerEscrow, deployer);
            factory.syncFactoryHooks();

            vm.stopBroadcast();

            console.log("Deployer:", deployer);
            console.log("ProtocolPool:", address(protocolPool));
            console.log("RelayerEscrow:", address(relayerEscrow));
            console.log("RevealMarket implementation:", address(implementation));
            console.log("Verifier:", verifierAddress);
            console.log("MarketFactory:", address(factory));
            console.log("Oracle:", oracle);
            console.log("Authorization signer:", authSigner);
            console.log("Circuit hash:", uint256(circuitHash));
            console.log("Expected public signals:", expectedInputs);
        }

        function _loadVerifyingKeyJson(string memory json) private pure returns (VerifyingKeyConfig memory config) {
            // Support the canonical zkSync/rapidsnark layout (vk_alpha_1, vk_beta_2, vk_gamma_2, vk_delta_2, IC, circuitHash, expectedInputs).
            config.alpha1 = abi.decode(vm.parseJson(json, ".vk_alpha_1"), (uint256[2]));
            config.beta2 = abi.decode(vm.parseJson(json, ".vk_beta_2"), (uint256[2][2]));
            config.gamma2 = abi.decode(vm.parseJson(json, ".vk_gamma_2"), (uint256[2][2]));
            config.delta2 = abi.decode(vm.parseJson(json, ".vk_delta_2"), (uint256[2][2]));
            config.ic = abi.decode(vm.parseJson(json, ".IC"), (uint256[2][]));
            config.circuitHash = abi.decode(vm.parseJson(json, ".circuitHash"), (bytes32));
            config.expectedInputs = abi.decode(vm.parseJson(json, ".expectedInputs"), (uint256));
            return config;
        }

        function _envOrString(string memory key, string memory defaultValue) private view returns (string memory) {
            try vm.envString(key) returns (string memory value) {
                return value;
            } catch {
                return defaultValue;
            }
        }

        function _envOrUint(string memory key, uint256 defaultValue) private view returns (uint256) {
            try vm.envUint(key) returns (uint256 value) {
                return value;
            } catch {
                return defaultValue;
            }
        }
    }
