// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {Test} from "forge-std/Test.sol";

import {ProtocolPool} from "../src/ProtocolPool.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

contract ProtocolPoolGuardsTest is Test {
    MockERC20 private token;
    ProtocolPool private pool;
    address private owner = makeAddr("owner");
    address private factory = makeAddr("factory");
    address private market = makeAddr("market");
    address private stranger = makeAddr("stranger");

    function setUp() external {
        token = new MockERC20();
        pool = new ProtocolPool(owner, IERC20(address(token)));
        vm.prank(owner);
        pool.setMarketFactory(factory);
    }

    function testRegisterMarketOnlyFactory() external {
        vm.prank(stranger);
        vm.expectRevert(ProtocolPool.Unauthorized.selector);
        pool.registerMarket(market, 1 ether);
    }

    function testDrawRequiresAllowedMarket() external {
        vm.prank(factory);
        pool.registerMarket(market, 2 ether);
        vm.prank(stranger);
        vm.expectRevert(ProtocolPool.Unauthorized.selector);
        pool.draw(market, 1 ether);
    }

    function testDrawRespectsCap() external {
        _fundPool(5 ether);
        vm.prank(factory);
        pool.registerMarket(market, 1 ether);
        vm.prank(market);
        vm.expectRevert(ProtocolPool.CapExceeded.selector);
        pool.draw(market, 2 ether);
    }

    function testDrawRespectsPoolBalance() external {
        _fundPool(1 ether);
        vm.prank(factory);
        pool.registerMarket(market, 5 ether);
        vm.prank(market);
        vm.expectRevert(ProtocolPool.InsufficientPool.selector);
        pool.draw(market, 2 ether);
    }

    function testDrawRespectsCapacity() external {
        _fundPool(5 ether);
        vm.prank(owner);
        pool.setCapacity(1 ether);
        vm.prank(factory);
        pool.registerMarket(market, 5 ether);
        vm.prank(market);
        vm.expectRevert(ProtocolPool.CapacityExceeded.selector);
        pool.draw(market, 2 ether);
    }

    function testDrawUpdatesConsumedLiability() external {
        _fundPool(5 ether);
        vm.prank(factory);
        pool.registerMarket(market, 3 ether);
        vm.prank(market);
        pool.draw(market, 1 ether);
        assertEq(pool.consumedLiability(market), 1 ether);
        assertEq(token.balanceOf(market), 1 ether);
    }

    function testDrawPausedGlobal() external {
        _fundPool(5 ether);
        vm.prank(factory);
        pool.registerMarket(market, 3 ether);
        vm.prank(owner);
        pool.setDrawsPaused(true);

        vm.prank(market);
        vm.expectRevert(ProtocolPool.DrawsPaused.selector);
        pool.draw(market, 1 ether);
    }

    function testDrawPausedPerMarket() external {
        _fundPool(5 ether);
        vm.prank(factory);
        pool.registerMarket(market, 3 ether);
        vm.prank(owner);
        pool.setMarketDrawPaused(market, true);

        vm.prank(market);
        vm.expectRevert(ProtocolPool.DrawsPaused.selector);
        pool.draw(market, 1 ether);
    }

    function testWithdrawOnlyOwner() external {
        _fundPool(2 ether);
        vm.prank(stranger);
        vm.expectRevert();
        pool.withdraw(payable(stranger), 1 ether);

        vm.prank(owner);
        pool.withdraw(payable(owner), 1 ether);
        assertEq(token.balanceOf(owner), 1 ether);
    }

    function testUpdateLiabilityCapOnlyFactory() external {
        vm.prank(factory);
        pool.registerMarket(market, 1 ether);
        vm.prank(stranger);
        vm.expectRevert(ProtocolPool.Unauthorized.selector);
        pool.updateLiabilityCap(market, 2 ether);
    }

    function _fundPool(uint256 amount) private {
        token.mint(owner, amount);
        vm.prank(owner);
        token.approve(address(pool), amount);
        vm.prank(owner);
        pool.deposit(amount);
    }
}
