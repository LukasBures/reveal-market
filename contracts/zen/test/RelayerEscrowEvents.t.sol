// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

import {RelayerEscrow} from "../src/RelayerEscrow.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

contract RelayerEscrowEventsTest is Test {
    RelayerEscrow private escrow;
    MockERC20 private token;
    address private owner = makeAddr("relayer");
    address private user = makeAddr("user");
    address private market = makeAddr("market");

    function setUp() external {
        token = new MockERC20();
        escrow = new RelayerEscrow(owner, IERC20(address(token)));
        vm.prank(owner);
        escrow.setMarketFactory(address(this));
        vm.prank(address(this));
        escrow.registerMarket(market);
    }

    function testDepositWithdrawEvents() external {
        token.mint(user, 1 ether);
        vm.prank(user);
        token.approve(address(escrow), 1 ether);
        vm.expectEmit(true, false, false, true);
        emit RelayerEscrow.Deposited(user, 1 ether);
        vm.prank(user);
        escrow.deposit(1 ether);

        vm.expectEmit(true, false, false, true);
        emit RelayerEscrow.Withdrawn(user, 0.4 ether);
        vm.prank(user);
        escrow.withdraw(0.4 ether);
    }

    function testCreditEvent() external {
        vm.expectEmit(true, true, false, true);
        emit RelayerEscrow.CreditReceived(market, user, 0.2 ether);
        vm.prank(market);
        escrow.creditFromMarket(user, 0.2 ether);
    }
}
