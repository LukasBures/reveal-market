// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {Test} from "forge-std/Test.sol";

import {RelayerEscrow} from "../src/RelayerEscrow.sol";
import {ToggleFeeERC20} from "./mocks/ToggleFeeERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

contract RelayerEscrowTransferInTest is Test {
    ToggleFeeERC20 private token;
    RelayerEscrow private escrow;
    address private owner = makeAddr("owner");
    address private user = makeAddr("user");

    function setUp() external {
        token = new ToggleFeeERC20();
        escrow = new RelayerEscrow(owner, IERC20(address(token)));
    }

    function testDepositRejectsFeeOnTransferToken() external {
        token.mint(user, 1 ether);
        vm.prank(user);
        token.approve(address(escrow), 1 ether);

        token.setFeeBps(100);
        vm.prank(user);
        vm.expectRevert(RelayerEscrow.FeeOnTransferNotSupported.selector);
        escrow.deposit(1 ether);

        assertEq(escrow.balances(user), 0, "no balance credited");
    }

    function testDepositForRejectsFeeOnTransferToken() external {
        token.mint(owner, 1 ether);
        vm.prank(owner);
        token.approve(address(escrow), 1 ether);

        token.setFeeBps(100);
        vm.prank(owner);
        vm.expectRevert(RelayerEscrow.FeeOnTransferNotSupported.selector);
        escrow.depositFor(user, 1 ether);

        assertEq(escrow.balances(user), 0, "no balance credited");
    }

    function testWithdrawRejectsSenderSideSurcharge() external {
        token.mint(user, 1 ether);
        vm.prank(user);
        token.approve(address(escrow), 1 ether);
        vm.prank(user);
        escrow.deposit(1 ether);

        token.setFeeBps(100);
        token.setSenderSurchargeMode(true);
        vm.prank(user);
        vm.expectRevert(RelayerEscrow.FeeOnTransferNotSupported.selector);
        escrow.withdraw(0.5 ether);

        assertEq(escrow.balances(user), 1 ether, "balance unchanged after failed withdraw");
    }
}
