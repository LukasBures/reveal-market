// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {BaseLpVault} from "../src/BaseLpVault.sol";
import {HedgeStrategyExecutor} from "../src/HedgeStrategyExecutor.sol";
import {MockERC20} from "./utils/MockERC20.sol";

contract AdminGuardsPolygonTest is Test {
    BaseLpVault private vault;
    HedgeStrategyExecutor private executor;
    MockERC20 private usdc;

    address private owner = address(this);
    address private hedger = address(0xBEEF);
    address private guardian = address(0xCAFE);

    function setUp() public {
        usdc = new MockERC20("USDC", "USDC", 6);
        vault = new BaseLpVault(usdc, address(this), hedger);
        executor = new HedgeStrategyExecutor(vault, hedger, address(this), 1_000_000e6, 500);
    }

    function testVaultPauseGuarded() public {
        vm.prank(address(0xBAD));
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, address(0xBAD)));
        vault.pause();

        vm.prank(address(this));
        vault.pause();
        assertTrue(vault.paused());
    }

    function testHedgerOnlyBorrow() public {
        HedgeStrategyExecutor.Order memory order = HedgeStrategyExecutor.Order({
            receiver: address(0xAAA),
            amount: 1,
            minOut: 0,
            maxSlippageBps: 0,
            deadline: block.timestamp + 1,
            nonce: bytes32(uint256(1))
        });

        vm.prank(address(0xBAD));
        vm.expectRevert(HedgeStrategyExecutor.InvalidSigner.selector); // bad signer/unauthorized
        executor.executeBorrow(order, hex"");
    }

    function testOwnerCanRotateSigner() public {
        address newSigner = address(0x1234);
        executor.setSigner(newSigner);
        assertEq(executor.signer(), newSigner);

        vm.prank(address(0xBAD));
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, address(0xBAD)));
        executor.setSigner(hedger);
    }
}
