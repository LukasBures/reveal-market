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
    address private market2 = makeAddr("market2");
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

    function testSetMarketFactoryOnlyOwner() external {
        address nextFactory = makeAddr("nextFactory");

        vm.prank(stranger);
        vm.expectRevert();
        pool.setMarketFactory(nextFactory);

        // Factory is already set — changing to a different address reverts with FactoryLocked.
        vm.prank(owner);
        vm.expectRevert(ProtocolPool.FactoryLocked.selector);
        pool.setMarketFactory(nextFactory);

        // Idempotent set to the same factory succeeds.
        vm.prank(owner);
        pool.setMarketFactory(factory);
        assertEq(pool.marketFactory(), factory);
    }

    function testSetMarketFactoryLockPreventsReassignment() external {
        // Deploy a fresh pool with no factory set.
        ProtocolPool freshPool = new ProtocolPool(owner, IERC20(address(token)));
        vm.prank(owner);
        freshPool.setMarketFactory(factory);
        assertEq(freshPool.marketFactory(), factory);

        // Second call to a different factory reverts.
        vm.prank(owner);
        vm.expectRevert(ProtocolPool.FactoryLocked.selector);
        freshPool.setMarketFactory(makeAddr("anotherFactory"));
    }

    function testSetMarketFactoryRejectsSpoofedOwnerContract() external {
        ProtocolPoolFactorySpoof spoof = new ProtocolPoolFactorySpoof(owner);
        vm.expectRevert();
        spoof.attack(pool, makeAddr("attackerFactory"));
        assertEq(pool.marketFactory(), factory, "factory unchanged");
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

    function testDrawCannotSpendReservedLiquidity() external {
        _fundPool(10 ether);
        vm.prank(factory);
        pool.registerMarket(market, 10 ether);
        vm.prank(factory);
        pool.registerMarket(market2, 10 ether);

        vm.prank(market);
        pool.reserveLiability(market, 6 ether);

        vm.prank(market2);
        vm.expectRevert(ProtocolPool.InsufficientPool.selector);
        pool.draw(market2, 5 ether);
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

    function testReservedDrawBypassesPause() external {
        _fundPool(5 ether);
        vm.prank(factory);
        pool.registerMarket(market, 3 ether);
        vm.prank(market);
        pool.reserveLiability(market, 2 ether);

        vm.prank(owner);
        pool.setDrawsPaused(true);
        vm.prank(owner);
        pool.setMarketDrawPaused(market, true);

        vm.prank(market);
        pool.draw(market, 1 ether);
        assertEq(pool.consumedLiability(market), 1 ether);
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
        token.mint(address(pool), 3 ether); // add surplus so owner can withdraw

        vm.prank(stranger);
        vm.expectRevert();
        pool.withdraw(payable(stranger), 1 ether);

        // Owner can withdraw surplus (3 ether) but not LP principal.
        vm.prank(owner);
        pool.withdraw(payable(owner), 3 ether);
        assertEq(token.balanceOf(owner), 3 ether);
    }

    function testWithdrawCannotBreachReservedLiability() external {
        _fundPool(2 ether);
        vm.prank(owner);
        pool.setCapacity(2 ether);
        vm.prank(factory);
        pool.registerMarket(market, 2 ether);
        vm.prank(market);
        pool.reserveLiability(market, 1.5 ether);

        vm.prank(owner);
        vm.expectRevert(ProtocolPool.InsufficientPool.selector);
        pool.withdraw(payable(owner), 1 ether);
    }

    function testSetCapacityRevertsWhenReservationsExist() external {
        _fundPool(2 ether);
        vm.prank(owner);
        pool.setCapacity(2 ether);
        vm.prank(factory);
        pool.registerMarket(market, 2 ether);
        vm.prank(market);
        pool.reserveLiability(market, 1 ether);

        vm.prank(owner);
        vm.expectRevert(ProtocolPool.ActiveReservations.selector);
        pool.setCapacity(5 ether);
    }

    function testReserveLiabilityUsesLiquidityWhenCapacityDisabled() external {
        _fundPool(2 ether);
        vm.prank(factory);
        pool.registerMarket(market, 2 ether);

        vm.prank(market);
        pool.reserveLiability(market, 2 ether);

        vm.prank(factory);
        pool.registerMarket(stranger, 2 ether);
        vm.prank(stranger);
        vm.expectRevert(ProtocolPool.InsufficientPool.selector);
        pool.reserveLiability(stranger, 1 wei);
    }

    function testReserveLiabilityRespectsCap() external {
        _fundPool(3 ether);
        vm.prank(factory);
        pool.registerMarket(market, 2 ether);

        vm.prank(market);
        vm.expectRevert(ProtocolPool.CapExceeded.selector);
        pool.reserveLiability(market, 3 ether);
    }

    function testUpdateLiabilityCapCannotDipBelowReservedOrConsumed() external {
        _fundPool(5 ether);
        vm.prank(factory);
        pool.registerMarket(market, 5 ether);

        vm.prank(market);
        pool.reserveLiability(market, 2 ether);
        vm.prank(market);
        pool.draw(market, 1 ether);

        vm.prank(factory);
        vm.expectRevert(ProtocolPool.CapExceeded.selector);
        pool.updateLiabilityCap(market, 1 ether);
    }

    function testUpdateLiabilityCapOnlyFactory() external {
        vm.prank(factory);
        pool.registerMarket(market, 1 ether);
        vm.prank(stranger);
        vm.expectRevert(ProtocolPool.Unauthorized.selector);
        pool.updateLiabilityCap(market, 2 ether);
    }

    function testCompactDepositsRemovesZeroRecords() external {
        // Deposit twice, withdraw the first, compact.
        _fundPool(10 ether);
        _fundPool(5 ether);

        // Two deposits under owner.
        assertEq(pool.depositCount(owner), 2);

        // Unlock and withdraw the first deposit.
        vm.warp(block.timestamp + 60 days);
        vm.prank(owner);
        pool.lpWithdraw(10 ether, 0);

        // After lpWithdraw, compaction runs automatically.
        // First record (shares=0) should be removed.
        assertEq(pool.depositCount(owner), 1, "zero-share record compacted");

        (uint256 shares,) = pool.depositAt(owner, 0);
        assertEq(shares, 5 ether, "remaining deposit intact");
    }

    function testWithdrawCannotBreachLpPrincipal() external {
        // LP deposits 10, market surplus adds 5 → balance=15, totalShares=10.
        _fundPool(10 ether);
        token.mint(address(pool), 5 ether); // simulate surplus from rake

        // Owner can withdraw the 5 surplus.
        vm.prank(owner);
        pool.withdraw(payable(owner), 5 ether);
        assertEq(token.balanceOf(owner), 5 ether);

        // Owner cannot withdraw into LP principal.
        vm.prank(owner);
        vm.expectRevert(ProtocolPool.InsufficientPool.selector);
        pool.withdraw(payable(owner), 1 wei);
    }

    function testWithdrawFloorUsesMaxOfReservedAndShares() external {
        // LP deposits 5, then market reserves 8 (with extra liquidity from direct mint).
        _fundPool(5 ether);
        token.mint(address(pool), 10 ether); // balance=15
        vm.prank(factory);
        pool.registerMarket(market, 10 ether);
        vm.prank(market);
        pool.reserveLiability(market, 8 ether);

        // reservedTotal=8 > totalShares=5, so floor=8. Can withdraw 15-8=7.
        vm.prank(owner);
        pool.withdraw(payable(owner), 7 ether);
        assertEq(token.balanceOf(owner), 7 ether);

        // Cannot withdraw more.
        vm.prank(owner);
        vm.expectRevert(ProtocolPool.InsufficientPool.selector);
        pool.withdraw(payable(owner), 1 wei);
    }

    function testForceReleaseLiability() external {
        _fundPool(10 ether);
        vm.prank(factory);
        pool.registerMarket(market, 10 ether);
        vm.prank(market);
        pool.reserveLiability(market, 5 ether);

        assertEq(pool.reservedTotal(), 5 ether);

        // Owner force-releases the orphaned reservation.
        vm.prank(owner);
        pool.forceReleaseLiability(market);
        assertEq(pool.reservedTotal(), 0);
        assertEq(pool.reservedLiability(market), 0);
    }

    function testForceReleaseLiabilityOnlyOwner() external {
        _fundPool(10 ether);
        vm.prank(factory);
        pool.registerMarket(market, 10 ether);
        vm.prank(market);
        pool.reserveLiability(market, 5 ether);

        vm.prank(stranger);
        vm.expectRevert();
        pool.forceReleaseLiability(market);
    }

    function testForceReleaseLiabilityRevertsOnZero() external {
        vm.prank(owner);
        vm.expectRevert(ProtocolPool.InvalidAmount.selector);
        pool.forceReleaseLiability(market);
    }

    function _fundPool(uint256 amount) private {
        token.mint(owner, amount);
        vm.prank(owner);
        token.approve(address(pool), amount);
        vm.prank(owner);
        pool.deposit(amount);
    }
}

contract ProtocolPoolFactorySpoof {
    address private immutable SPOOFED_OWNER;

    constructor(address owner_) {
        SPOOFED_OWNER = owner_;
    }

    function owner() external view returns (address) {
        return SPOOFED_OWNER;
    }

    function attack(ProtocolPool pool, address attackerFactory) external {
        pool.setMarketFactory(attackerFactory);
    }
}
