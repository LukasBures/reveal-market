// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

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
        address collateralToken = _envOrAddress("ZEN_TOKEN_ADDRESS");
        if (collateralToken == address(0)) {
            collateralToken = _envOrAddress("COLLATERAL_TOKEN");
        }
        if (collateralToken == address(0)) {
            revert("ZEN_TOKEN_ADDRESS (or COLLATERAL_TOKEN) is required");
        }

        bool useStubVerifier = _envOrUint("USE_STUB_VERIFIER", 0) == 1;
        string memory vkJson = _envOrString("SETTLEMENT_VK_JSON", "");

        vm.startBroadcast(deployerKey);

        ProtocolPool protocolPool = new ProtocolPool(deployer, IERC20(collateralToken));
        RelayerEscrow relayerEscrow = new RelayerEscrow(deployer, IERC20(collateralToken));
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

        MarketFactory factory =
            new MarketFactory(address(implementation), protocolPool, relayerEscrow, collateralToken, deployer);
        protocolPool.setMarketFactory(address(factory));
        relayerEscrow.setMarketFactory(address(factory));

        vm.stopBroadcast();

        console.log("Deployer:", deployer);
        console.log("Collateral token:", collateralToken);
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

    function _loadVerifyingKeyJson(string memory json) internal pure returns (VerifyingKeyConfig memory config) {
        // Support the canonical zkSync/rapidsnark layout (vk_alpha_1, vk_beta_2, vk_gamma_2, vk_delta_2, IC, circuitHash, expectedInputs).
        config.alpha1 = _readG1(json, ".vk_alpha_1");
        config.beta2 = _readG2(json, ".vk_beta_2");
        config.gamma2 = _readG2(json, ".vk_gamma_2");
        config.delta2 = _readG2(json, ".vk_delta_2");
        config.ic = _readIcPoints(json, ".IC");
        config.circuitHash = abi.decode(vm.parseJson(json, ".circuitHash"), (bytes32));
        config.expectedInputs = _readUint(json, ".expectedInputs");
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

    function _readUintMatrix(string memory json, string memory key) private pure returns (uint256[][] memory matrix) {
        matrix = abi.decode(vm.parseJson(json, key), (uint256[][]));
    }

    function _readG1(string memory json, string memory key) private pure returns (uint256[2] memory point) {
        uint256[] memory coords = _readUintArray(json, key);
        require(coords.length >= 2, "invalid g1 coords");
        point[0] = coords[0];
        point[1] = coords[1];
    }

    function _readG2(string memory json, string memory key) private pure returns (uint256[2][2] memory point) {
        uint256[][] memory coords = _readUintMatrix(json, key);
        require(coords.length >= 2 && coords[0].length >= 2 && coords[1].length >= 2, "invalid g2 coords");
        point[0][0] = coords[0][0];
        point[0][1] = coords[0][1];
        point[1][0] = coords[1][0];
        point[1][1] = coords[1][1];
    }

    function _readIcPoints(string memory json, string memory key) private pure returns (uint256[2][] memory points) {
        uint256[][] memory coords = _readUintMatrix(json, key);
        points = new uint256[2][](coords.length);
        for (uint256 i = 0; i < coords.length; ++i) {
            require(coords[i].length >= 2, "invalid ic coords");
            points[i][0] = coords[i][0];
            points[i][1] = coords[i][1];
        }
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

    function _envOrAddress(string memory key) private view returns (address) {
        try vm.envAddress(key) returns (address addr) {
            return addr;
        } catch {
            return address(0);
        }
    }
}
