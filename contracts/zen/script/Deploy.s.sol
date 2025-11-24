// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Vm} from "forge-std/Vm.sol";
import {console} from "forge-std/console.sol";

import {MarketFactory} from "../src/MarketFactory.sol";
import {RakeManager} from "../src/RakeManager.sol";
import {RevealMarket} from "../src/RevealMarket.sol";
import {Verifier} from "../src/Verifier.sol";
import {VerifierStub} from "../src/verifiers/VerifierStub.sol";

/// @notice Extends Vm with helper aliases for environment reads and broadcast control.
interface VmExtended is Vm {
    function envUint(string calldata name) external view returns (uint256);
    function envAddress(string calldata name) external view returns (address);
    function envString(string calldata name) external view returns (string memory);
    function startBroadcast(uint256 privateKey) external;
    function stopBroadcast() external;
}

abstract contract ScriptBase {
    VmExtended internal constant HEVM = VmExtended(address(uint160(uint256(keccak256("hevm cheat code")))));
}

contract Deploy is ScriptBase {
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
        // ── Load environment variables ─────────────────────────────────────────────
        uint256 deployerKey = HEVM.envUint("DEPLOYER_KEY");
        address oracle = HEVM.envAddress("ORACLE_ADDRESS");
        address payable treasury = payable(HEVM.envAddress("TREASURY_ADDRESS"));
        uint256 rakeBps = HEVM.envUint("RAKE_BPS");
        bool useStubVerifier = _envOrUint("USE_STUB_VERIFIER", 0) == 1;
        string memory vkPath = _envOrString("SETTLEMENT_VK_PATH", "contracts/cache/settlement-vk.json");

        address deployer = HEVM.addr(deployerKey);

        // ── Deploy contracts ───────────────────────────────────────────────────────
        HEVM.startBroadcast(deployerKey);

        RakeManager rakeManager = new RakeManager(deployer, treasury, rakeBps);
        RevealMarket implementation = new RevealMarket();

        address verifierAddress;
        bytes32 circuitHash;
        uint256 expectedInputs;
        if (useStubVerifier) {
            VerifierStub stub = new VerifierStub();
            verifierAddress = address(stub);
            circuitHash = bytes32(0);
            expectedInputs = 12;
        } else {
            VerifyingKeyConfig memory vkConfig = _loadVerifyingKey(vkPath);
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
            new MarketFactory(address(implementation), address(rakeManager), treasury, verifierAddress);

        HEVM.stopBroadcast();

        // ── Log deployed addresses ─────────────────────────────────────────────────
        console.log("RakeManager:", address(rakeManager));
        console.log("Verifier:", verifierAddress);
        console.log("RevealMarket implementation:", address(implementation));
        console.log("MarketFactory:", address(factory));
        console.log("Oracle:", oracle);
        console.log("Circuit hash:", uint256(circuitHash));
        console.log("Expected signals:", expectedInputs);

        _writeArtifacts(rakeManager, implementation, factory, verifierAddress, oracle, circuitHash, expectedInputs);

        // Example (optional):
        // uint256 commitDeadline = block.timestamp + 3 days;
        // uint256 revealDeadline = commitDeadline + 2 days;
        // MarketFactory.CreateMarketParams memory params = MarketFactory.CreateMarketParams({
        //     eventId: "EVENT-ID",
        //     commitDeadline: commitDeadline,
        //     revealDeadline: revealDeadline,
        //     oracle: oracle,
        //     rakeBpsOverride: 0,
        //     payoutMultiplier: 1e18,
        //     payoutCurve: RevealMarket.PayoutCurve.FixedOdds,
        //     floatAmount: 0,
        //     maxMarketSize: 0
        // });
        // factory.createMarket(params);
    }

    function _loadVerifyingKey(string memory path) private view returns (VerifyingKeyConfig memory config) {
        // forge-lint: disable-next-line(unsafe-cheatcode)
        string memory json = HEVM.readFile(path);
        config.alpha1 = abi.decode(HEVM.parseJson(json, ".alpha1"), (uint256[2]));
        config.beta2 = abi.decode(HEVM.parseJson(json, ".beta2"), (uint256[2][2]));
        config.gamma2 = abi.decode(HEVM.parseJson(json, ".gamma2"), (uint256[2][2]));
        config.delta2 = abi.decode(HEVM.parseJson(json, ".delta2"), (uint256[2][2]));
        config.ic = abi.decode(HEVM.parseJson(json, ".ic"), (uint256[2][]));
        config.circuitHash = abi.decode(HEVM.parseJson(json, ".circuitHash"), (bytes32));
        config.expectedInputs = abi.decode(HEVM.parseJson(json, ".expectedInputs"), (uint256));
    }

    function _envOrString(string memory key, string memory defaultValue) private view returns (string memory) {
        try HEVM.envString(key) returns (string memory value) {
            return value;
        } catch {
            return defaultValue;
        }
    }

    function _envOrUint(string memory key, uint256 defaultValue) private view returns (uint256) {
        try HEVM.envUint(key) returns (uint256 value) {
            return value;
        } catch {
            return defaultValue;
        }
    }

    function _writeArtifacts(
        RakeManager rakeManager,
        RevealMarket implementation,
        MarketFactory factory,
        address verifier,
        address oracle,
        bytes32 circuitHash,
        uint256 expectedInputs
    ) private {
        string memory root = "deploy";
        string memory json = HEVM.serializeAddress(root, "rakeManager", address(rakeManager));
        json = HEVM.serializeAddress(root, "verifier", verifier);
        json = HEVM.serializeAddress(root, "revealMarketImplementation", address(implementation));
        json = HEVM.serializeAddress(root, "marketFactory", address(factory));
        json = HEVM.serializeAddress(root, "oracle", oracle);
        json = HEVM.serializeBytes32(root, "circuitHash", circuitHash);
        json = HEVM.serializeUint(root, "expectedInputs", expectedInputs);

        string memory outputPath = "contracts/cache/last-deployment.json";
        HEVM.writeJson(json, outputPath);
        console.log("Wrote deployment artifact:", outputPath);
    }
}
