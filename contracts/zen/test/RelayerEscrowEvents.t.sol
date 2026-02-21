// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {Test} from "forge-std/Test.sol";

import {RelayerEscrow} from "../src/RelayerEscrow.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

contract RelayerEscrowEventsTest is Test {
    RelayerEscrow private escrow;
    MockERC20 private token;
    address private owner = makeAddr("relayer");
    address private user = makeAddr("user");
    RelayerEscrowEventMarket private market;

    function setUp() external {
        token = new MockERC20();
        escrow = new RelayerEscrow(owner, IERC20(address(token)));
        vm.prank(owner);
        escrow.setMarketFactory(address(this));
        market = new RelayerEscrowEventMarket(address(this), address(escrow), address(token));
        vm.prank(address(this));
        escrow.registerMarket(address(market));
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
        token.mint(address(market), 0.2 ether);
        vm.prank(address(market));
        token.approve(address(escrow), 0.2 ether);
        vm.expectEmit(true, true, false, true);
        emit RelayerEscrow.CreditReceived(address(market), user, 0.2 ether);
        vm.prank(address(market));
        escrow.creditFromMarket(user, 0.2 ether);
    }
}

contract RelayerEscrowEventMarket {
    address public factory;
    address public relayerEscrow;
    address public collateralToken;

    constructor(address factory_, address relayerEscrow_, address collateralToken_) {
        factory = factory_;
        relayerEscrow = relayerEscrow_;
        collateralToken = collateralToken_;
    }
}
