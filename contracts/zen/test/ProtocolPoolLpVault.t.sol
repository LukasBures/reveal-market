// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {Test} from "forge-std/Test.sol";

import {ProtocolPool} from "../src/ProtocolPool.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

contract ProtocolPoolLpVaultTest is Test {
    MockERC20 private token;
    ProtocolPool private pool;
    address private owner = makeAddr("owner");
    address private factory = makeAddr("factory");
    address private market = makeAddr("market");
    address private lp1 = makeAddr("lp1");
    address private lp2 = makeAddr("lp2");

    function setUp() external {
        token = new MockERC20();
        pool = new ProtocolPool(owner, IERC20(address(token)));
        vm.prank(owner);
        pool.setMarketFactory(factory);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  Share math (1:1 minting, principal-capped)
    // ═══════════════════════════════════════════════════════════════════

    function testFirstDepositMints1to1() external {
        _lpDeposit(lp1, 100 ether);
        assertEq(pool.totalShares(), 100 ether);
        assertEq(pool.lpShareBalance(lp1), 100 ether);
    }

    function testSecondDepositAlways1to1() external {
        _lpDeposit(lp1, 100 ether);

        // Even with surplus, LP2 gets 1:1 shares.
        token.mint(address(pool), 50 ether);

        _lpDeposit(lp2, 150 ether);
        assertEq(pool.lpShareBalance(lp2), 150 ether, "always 1:1");
        assertEq(pool.totalShares(), 250 ether);
    }

    function testSecondDepositAfterLoss1to1() external {
        _lpDeposit(lp1, 100 ether);
        _registerAndDraw(50 ether);

        // Even after loss, LP2 gets 1:1 shares.
        _lpDeposit(lp2, 50 ether);
        assertEq(pool.lpShareBalance(lp2), 50 ether, "always 1:1");
        assertEq(pool.totalShares(), 150 ether);
    }

    function testZeroAmountDepositReverts() external {
        vm.expectRevert(ProtocolPool.InvalidAmount.selector);
        vm.prank(lp1);
        pool.deposit(0);
    }

    function testConvertToSharesAlways1to1() external {
        _lpDeposit(lp1, 200 ether);
        assertEq(pool.convertToShares(100 ether), 100 ether);

        // Even with surplus
        token.mint(address(pool), 100 ether);
        assertEq(pool.convertToShares(100 ether), 100 ether);
    }

    function testConvertToAssetsCappedAtPrincipal() external {
        _lpDeposit(lp1, 200 ether);
        // 1:1 initially
        assertEq(pool.convertToAssets(100 ether), 100 ether);

        // Surplus added — LP value still capped at 1:1
        token.mint(address(pool), 100 ether);
        // 200 shares, 300 assets → but capped at principal: 100 shares = 100 ZEN (not 150)
        assertEq(pool.convertToAssets(100 ether), 100 ether);
        assertEq(pool.convertToAssets(200 ether), 200 ether);
    }

    function testConvertToAssetsReducedOnLoss() external {
        _lpDeposit(lp1, 100 ether);
        _registerAndDraw(40 ether);
        // 60 assets, 100 shares → 100 shares = 60 ZEN (below principal, so proportional)
        assertEq(pool.convertToAssets(100 ether), 60 ether);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  Protocol surplus
    // ═══════════════════════════════════════════════════════════════════

    function testProtocolSurplusAfterMarketReturn() external {
        _lpDeposit(lp1, 100 ether);
        assertEq(pool.protocolSurplus(), 0);

        // Market returns 50 surplus
        token.mint(address(pool), 50 ether);
        assertEq(pool.protocolSurplus(), 50 ether);
    }

    function testProtocolSurplusZeroWhenUnderwater() external {
        _lpDeposit(lp1, 100 ether);
        _registerAndDraw(40 ether);
        assertEq(pool.protocolSurplus(), 0);
    }

    function testOwnerCanWithdrawSurplus() external {
        _lpDeposit(lp1, 100 ether);
        token.mint(address(pool), 50 ether);

        // Owner withdraws the 50 surplus
        vm.prank(owner);
        pool.withdraw(payable(owner), 50 ether);
        assertEq(pool.protocolSurplus(), 0);
        assertEq(token.balanceOf(owner), 50 ether);

        // LP can still withdraw full principal
        vm.warp(block.timestamp + 60 days);
        vm.prank(lp1);
        pool.lpWithdraw(100 ether, 0);
        assertEq(token.balanceOf(lp1), 100 ether);
    }

    function testLpCannotProfitFromSurplus() external {
        _lpDeposit(lp1, 100 ether);
        token.mint(address(pool), 200 ether); // big surplus

        vm.warp(block.timestamp + 60 days);
        vm.prank(lp1);
        pool.lpWithdraw(100 ether, 0);

        // LP gets exactly 100 (principal), not 300
        assertEq(token.balanceOf(lp1), 100 ether);
        // Remaining 200 stays in pool (surplus for owner)
        assertEq(pool.protocolSurplus(), 200 ether);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  Lock mechanics
    // ═══════════════════════════════════════════════════════════════════

    function testDepositSetsCorrectUnlockTime() external {
        uint256 t = block.timestamp;
        _lpDeposit(lp1, 10 ether);
        (uint256 shares, uint256 unlockTime) = pool.depositAt(lp1, 0);
        assertEq(shares, 10 ether);
        assertEq(unlockTime, t + 60 days);
    }

    function testWithdrawBeforeLockReverts() external {
        _lpDeposit(lp1, 10 ether);
        vm.warp(block.timestamp + 59 days);
        vm.prank(lp1);
        vm.expectRevert(ProtocolPool.InsufficientUnlockedShares.selector);
        pool.lpWithdraw(10 ether, 0);
    }

    function testWithdrawAtExactExpirySucceeds() external {
        _lpDeposit(lp1, 10 ether);
        vm.warp(block.timestamp + 60 days);
        vm.prank(lp1);
        pool.lpWithdraw(10 ether, 0);
        assertEq(pool.lpShareBalance(lp1), 0);
        assertEq(token.balanceOf(lp1), 10 ether);
    }

    function testTwoDepositsOnlyOlderWithdrawableAtMidpoint() external {
        // Deposit 1 at t=1, unlocks at t = 1 + 60 days = 5_184_001
        _lpDeposit(lp1, 10 ether);

        // Deposit 2 at t = 30 days + 1, unlocks at t = 30 days + 1 + 60 days = 7_776_001
        vm.warp(1 + 30 days);
        _lpDeposit(lp1, 5 ether);

        // Warp to exactly 60 days + 1 — first deposit unlocked, second still locked
        vm.warp(1 + 60 days);
        assertEq(pool.unlockedShares(lp1), 10 ether);
        assertEq(pool.depositCount(lp1), 2);

        // Can withdraw 10 but not 15
        vm.prank(lp1);
        pool.lpWithdraw(10 ether, 0);
        assertEq(pool.lpShareBalance(lp1), 5 ether);

        vm.prank(lp1);
        vm.expectRevert(ProtocolPool.InsufficientUnlockedShares.selector);
        pool.lpWithdraw(5 ether, 0);
    }

    function testNewDepositDoesNotResetPriorLock() external {
        _lpDeposit(lp1, 10 ether);
        uint256 firstUnlock;
        (, firstUnlock) = pool.depositAt(lp1, 0);

        vm.warp(block.timestamp + 30 days);
        _lpDeposit(lp1, 5 ether);

        // First deposit's unlock time unchanged
        uint256 afterUnlock;
        (, afterUnlock) = pool.depositAt(lp1, 0);
        assertEq(afterUnlock, firstUnlock);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  Withdrawal flow
    // ═══════════════════════════════════════════════════════════════════

    function testFullWithdrawal() external {
        _lpDeposit(lp1, 50 ether);
        vm.warp(block.timestamp + 60 days);
        vm.prank(lp1);
        pool.lpWithdraw(50 ether, 0);
        assertEq(pool.totalShares(), 0);
        assertEq(pool.lpShareBalance(lp1), 0);
        assertEq(token.balanceOf(lp1), 50 ether);
    }

    function testPartialWithdrawal() external {
        _lpDeposit(lp1, 50 ether);
        vm.warp(block.timestamp + 60 days);
        vm.prank(lp1);
        pool.lpWithdraw(20 ether, 0);
        assertEq(pool.lpShareBalance(lp1), 30 ether);
        assertEq(token.balanceOf(lp1), 20 ether);
    }

    function testFifoOrdering() external {
        _lpDeposit(lp1, 10 ether);
        vm.warp(block.timestamp + 10 days);
        _lpDeposit(lp1, 20 ether);

        // Unlock both
        vm.warp(block.timestamp + 60 days);

        // Withdraw 15 — should consume all of deposit 0 (10) and 5 from deposit 1.
        // After withdrawal, compaction removes the zeroed-out first record.
        vm.prank(lp1);
        pool.lpWithdraw(15 ether, 0);

        assertEq(pool.depositCount(lp1), 1, "zero-share record compacted");
        (uint256 s0,) = pool.depositAt(lp1, 0);
        assertEq(s0, 15 ether, "remaining deposit partially consumed");
    }

    function testWithdrawRespectsIdleLiquidity() external {
        _lpDeposit(lp1, 100 ether);
        vm.warp(block.timestamp + 60 days);

        // Reserve 80 of 100
        vm.prank(factory);
        pool.registerMarket(market, 100 ether);
        vm.prank(market);
        pool.reserveLiability(market, 80 ether);

        // Only 20 idle
        vm.prank(lp1);
        vm.expectRevert(ProtocolPool.InsufficientIdleLiquidity.selector);
        pool.lpWithdraw(30 ether, 0);

        // 20 shares = 20 assets (1:1)
        vm.prank(lp1);
        pool.lpWithdraw(20 ether, 0);
        assertEq(token.balanceOf(lp1), 20 ether);
    }

    function testRevertsWhenAllLiquidityReserved() external {
        _lpDeposit(lp1, 100 ether);
        vm.warp(block.timestamp + 60 days);

        vm.prank(factory);
        pool.registerMarket(market, 100 ether);
        vm.prank(market);
        pool.reserveLiability(market, 100 ether);

        vm.prank(lp1);
        vm.expectRevert(ProtocolPool.InsufficientIdleLiquidity.selector);
        pool.lpWithdraw(1 ether, 0);
    }

    function testTwoLpsFirstComeFirstServed() external {
        _lpDeposit(lp1, 50 ether);
        _lpDeposit(lp2, 50 ether);
        vm.warp(block.timestamp + 60 days);

        // Reserve 80 of 100 — only 20 idle
        vm.prank(factory);
        pool.registerMarket(market, 100 ether);
        vm.prank(market);
        pool.reserveLiability(market, 80 ether);

        // LP1 withdraws 20 (all idle)
        vm.prank(lp1);
        pool.lpWithdraw(20 ether, 0);

        // LP2 cannot withdraw — nothing idle
        vm.prank(lp2);
        vm.expectRevert(ProtocolPool.InsufficientIdleLiquidity.selector);
        pool.lpWithdraw(1 ether, 0);
    }

    function testMarketSettlesReleasesReservationLpCanWithdraw() external {
        _lpDeposit(lp1, 100 ether);
        vm.warp(block.timestamp + 60 days);

        vm.prank(factory);
        pool.registerMarket(market, 100 ether);
        vm.prank(market);
        pool.reserveLiability(market, 80 ether);

        // Market settles — releases reservation
        vm.prank(market);
        pool.releaseLiabilityReservation(market);

        // Full idle restored
        vm.prank(lp1);
        pool.lpWithdraw(100 ether, 0);
        assertEq(token.balanceOf(lp1), 100 ether);
    }

    function testMaxRedeemableBasic() external {
        _lpDeposit(lp1, 100 ether);

        // Locked — 0
        assertEq(pool.maxRedeemable(lp1), 0);

        vm.warp(block.timestamp + 60 days);
        assertEq(pool.maxRedeemable(lp1), 100 ether);
    }

    function testMaxRedeemableCappedByIdle() external {
        _lpDeposit(lp1, 100 ether);
        vm.warp(block.timestamp + 60 days);

        vm.prank(factory);
        pool.registerMarket(market, 100 ether);
        vm.prank(market);
        pool.reserveLiability(market, 70 ether);

        // 30 idle, 100 unlocked → max is 30 shares (1:1)
        assertEq(pool.maxRedeemable(lp1), 30 ether);
    }

    function testMaxRedeemableZeroWhenFullyReserved() external {
        _lpDeposit(lp1, 100 ether);
        vm.warp(block.timestamp + 60 days);

        vm.prank(factory);
        pool.registerMarket(market, 100 ether);
        vm.prank(market);
        pool.reserveLiability(market, 100 ether);

        assertEq(pool.maxRedeemable(lp1), 0);
    }

    function testZeroSharesWithdrawReverts() external {
        _lpDeposit(lp1, 10 ether);
        vm.warp(block.timestamp + 60 days);
        vm.prank(lp1);
        vm.expectRevert(ProtocolPool.InvalidAmount.selector);
        pool.lpWithdraw(0, 0);
    }

    function testWithdrawMoreSharesThanBalanceReverts() external {
        _lpDeposit(lp1, 10 ether);
        vm.warp(block.timestamp + 60 days);
        vm.prank(lp1);
        vm.expectRevert(ProtocolPool.InsufficientUnlockedShares.selector);
        pool.lpWithdraw(11 ether, 0);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  Loss dynamics (LPs bear downside only)
    // ═══════════════════════════════════════════════════════════════════

    function testDrawReducesLpValue() external {
        _lpDeposit(lp1, 100 ether);
        assertEq(pool.convertToAssets(100 ether), 100 ether);

        _registerAndDraw(40 ether);

        // 60 assets, 100 shares → 100 shares = 60 ZEN
        assertEq(pool.convertToAssets(100 ether), 60 ether);
    }

    function testSurplusDoesNotIncreaseLpValue() external {
        _lpDeposit(lp1, 100 ether);

        // Surplus of 50 — but LP value stays capped at principal
        token.mint(address(pool), 50 ether);
        assertEq(pool.convertToAssets(100 ether), 100 ether, "capped at principal");
        assertEq(pool.protocolSurplus(), 50 ether, "surplus belongs to protocol");
    }

    function testFullLifecycleWithLoss() external {
        _lpDeposit(lp1, 100 ether);

        // Market draws 30
        _registerAndDraw(30 ether);

        // No surplus returned — permanent loss
        vm.warp(block.timestamp + 60 days);
        vm.prank(lp1);
        pool.lpWithdraw(100 ether, 0);
        assertEq(token.balanceOf(lp1), 70 ether, "LP bears the loss");
    }

    function testFullLifecycleLossThenRecovery() external {
        _lpDeposit(lp1, 100 ether);

        // Market draws 30
        _registerAndDraw(30 ether);
        // Pool: 70 assets, 100 shares

        // Market returns 20 (partial recovery)
        token.mint(address(pool), 20 ether);
        // Pool: 90 assets, 100 shares

        vm.warp(block.timestamp + 60 days);
        vm.prank(lp1);
        pool.lpWithdraw(100 ether, 0);
        // LP gets 90 (recovered from 70, but still below 100 principal)
        assertEq(token.balanceOf(lp1), 90 ether, "partial recovery");
    }

    function testFullLifecycleLossThenFullRecoveryPlusSurplus() external {
        _lpDeposit(lp1, 100 ether);

        // Market draws 30
        _registerAndDraw(30 ether);

        // Market returns 60 (net +30 surplus above principal)
        token.mint(address(pool), 60 ether);
        // Pool: 130 assets, 100 shares

        vm.warp(block.timestamp + 60 days);
        vm.prank(lp1);
        pool.lpWithdraw(100 ether, 0);
        // LP gets exactly principal (100), not 130
        assertEq(token.balanceOf(lp1), 100 ether, "capped at principal");
        // 30 surplus remains for owner
        assertEq(pool.protocolSurplus(), 30 ether);
    }

    function testTwoLpsLossDistribution() external {
        _lpDeposit(lp1, 100 ether);
        _lpDeposit(lp2, 50 ether);

        // Market draws 30 (pool: 120 assets, 150 shares → each share = 0.8 ZEN)
        _registerAndDraw(30 ether);

        vm.warp(block.timestamp + 60 days);

        vm.prank(lp1);
        pool.lpWithdraw(100 ether, 0);
        assertEq(token.balanceOf(lp1), 80 ether, "LP1: 100 * 120/150 = 80");

        vm.prank(lp2);
        pool.lpWithdraw(50 ether, 0);
        assertEq(token.balanceOf(lp2), 40 ether, "LP2: 50 * 40/50 = 40");
    }

    function testAdminWithdrawReducesLpValue() external {
        _lpDeposit(lp1, 100 ether);

        // Admin withdraws 30
        vm.prank(owner);
        pool.withdraw(payable(owner), 30 ether);

        // 70 assets, 100 shares → LP's 100 shares = 70 ZEN
        assertEq(pool.convertToAssets(100 ether), 70 ether);
    }

    function testIdleLiquidity() external {
        _lpDeposit(lp1, 100 ether);
        assertEq(pool.idleLiquidity(), 100 ether);

        vm.prank(factory);
        pool.registerMarket(market, 100 ether);
        vm.prank(market);
        pool.reserveLiability(market, 60 ether);
        assertEq(pool.idleLiquidity(), 40 ether);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  Event emission
    // ═══════════════════════════════════════════════════════════════════

    function testDepositEmitsBothEvents() external {
        token.mint(lp1, 10 ether);
        vm.prank(lp1);
        token.approve(address(pool), 10 ether);

        vm.expectEmit(true, false, false, true);
        emit ProtocolPool.FundsReceived(lp1, 10 ether);

        vm.expectEmit(true, false, false, true);
        emit ProtocolPool.LpDeposited(lp1, 10 ether, 10 ether, block.timestamp + 60 days);

        vm.prank(lp1);
        pool.deposit(10 ether);
    }

    function testLpWithdrawEmitsEvent() external {
        _lpDeposit(lp1, 10 ether);
        vm.warp(block.timestamp + 60 days);

        vm.expectEmit(true, false, false, true);
        emit ProtocolPool.LpWithdrawn(lp1, 10 ether, 10 ether);

        vm.prank(lp1);
        pool.lpWithdraw(10 ether, 0);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  Slippage protection
    // ═══════════════════════════════════════════════════════════════════

    function testLpWithdrawSlippageGuard() external {
        _lpDeposit(lp1, 100 ether);
        _registerAndDraw(40 ether);
        // Pool: 60 assets, 100 shares → 100 shares = 60 ZEN

        vm.warp(block.timestamp + 60 days);
        vm.prank(lp1);
        vm.expectRevert(ProtocolPool.SlippageExceeded.selector);
        pool.lpWithdraw(100 ether, 80 ether); // expects 80, gets 60

        // Succeeds with correct minAssets
        vm.prank(lp1);
        pool.lpWithdraw(100 ether, 60 ether);
        assertEq(token.balanceOf(lp1), 60 ether);
    }

    function testLpWithdrawSlippageZeroBypass() external {
        _lpDeposit(lp1, 100 ether);
        _registerAndDraw(50 ether);

        vm.warp(block.timestamp + 60 days);
        // minAssets=0 always passes (no slippage check)
        vm.prank(lp1);
        pool.lpWithdraw(100 ether, 0);
        assertEq(token.balanceOf(lp1), 50 ether);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  Helpers
    // ═══════════════════════════════════════════════════════════════════

    function _lpDeposit(address lp, uint256 amount) private {
        token.mint(lp, amount);
        vm.prank(lp);
        token.approve(address(pool), amount);
        vm.prank(lp);
        pool.deposit(amount);
    }

    /// @dev Register a market, fund enough to draw, and draw.
    function _registerAndDraw(uint256 amount) private {
        if (!pool.allowedMarket(market)) {
            vm.prank(factory);
            pool.registerMarket(market, type(uint256).max);
        }
        vm.prank(market);
        pool.draw(market, amount);
    }
}
