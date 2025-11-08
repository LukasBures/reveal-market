// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Vm} from "forge-std/Vm.sol";
import {console} from "forge-std/console.sol";

import {MarketFactory} from "../src/MarketFactory.sol";
import {RakeManager} from "../src/RakeManager.sol";
import {RevealMarket} from "../src/RevealMarket.sol";
import {Verifier} from "../src/Verifier.sol";

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
    function run() external {
        // ── Load environment variables ─────────────────────────────────────────────
        uint256 deployerKey = HEVM.envUint("DEPLOYER_KEY");
        address oracle = HEVM.envAddress("ORACLE_ADDRESS");
        address payable treasury = payable(HEVM.envAddress("TREASURY_ADDRESS"));
        uint256 rakeBps = HEVM.envUint("RAKE_BPS");
        string memory metadataURI = HEVM.envString("MARKET_METADATA_URI");
        address collateral = HEVM.envAddress("COLLATERAL_ADDRESS");

        address deployer = HEVM.addr(deployerKey);

        // ── Deploy contracts ───────────────────────────────────────────────────────
        HEVM.startBroadcast(deployerKey);

        RakeManager rakeManager = new RakeManager(deployer, treasury, rakeBps);
        Verifier verifier = new Verifier();
        RevealMarket implementation = new RevealMarket();
        MarketFactory factory =
            new MarketFactory(address(implementation), address(rakeManager), treasury, address(verifier), collateral);

        HEVM.stopBroadcast();

        // ── Log deployed addresses ─────────────────────────────────────────────────
        console.log("RakeManager:", address(rakeManager));
        console.log("Verifier:", address(verifier));
        console.log("RevealMarket implementation:", address(implementation));
        console.log("MarketFactory:", address(factory));
        console.log("Oracle:", oracle);
        console.log("Default collateral:", collateral);
        console.log("Default metadata URI:", metadataURI);

        // Example (optional):
        // uint256 commitDeadline = block.timestamp + 3 days;
        // uint256 revealDeadline = commitDeadline + 2 days;
        // factory.createMarket("EVENT-ID", commitDeadline, revealDeadline, oracle, collateral, 0);
    }
}
