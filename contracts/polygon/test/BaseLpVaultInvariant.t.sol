// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {StdInvariant} from "forge-std/StdInvariant.sol";
import {BaseLpVault} from "../src/BaseLpVault.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

contract MockUSDCInvariant is ERC20 {
    constructor() ERC20("Mock USDC", "mUSDC") {}

    function decimals() public pure override returns (uint8) {
        return 6;
    }

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}

contract BaseLpVaultInvariantTest is StdInvariant, Test {
    uint256 private constant ONE_USDC = 1e6;

    BaseLpVault internal vault;
    MockUSDCInvariant internal usdc;
    address internal hedger = address(0xBEEF);

    address internal lp1 = address(0xA11CE);
    address internal lp2 = address(0xB0B);

    function setUp() public {
        usdc = new MockUSDCInvariant();
        vault = new BaseLpVault(usdc, address(this), hedger);

        usdc.mint(lp1, 1_000_000 * ONE_USDC);
        usdc.mint(lp2, 1_000_000 * ONE_USDC);

        targetContract(address(vault));
    }

    function invariant_totalAssetsConsistent() public view {
        uint256 total = vault.totalAssets();
        uint256 idle = vault.idleAssets();
        uint256 utilized = vault.utilizedAssets();

        assertEq(total, idle + utilized, "total assets must equal idle + utilized");
        assertGe(total, utilized, "utilized cannot exceed total");
    }

    function invariant_utilizationCapRespected() public view {
        uint256 total = vault.totalAssets();
        uint256 utilized = vault.utilizedAssets();
        if (total == 0) {
            assertEq(utilized, 0, "no total implies zero utilization");
            return;
        }
        uint256 cap = (uint256(vault.maxUtilizationBps()) * total) / vault.BPS_DENOMINATOR();
        assertLe(utilized, cap, "utilization cap exceeded");
    }
}
