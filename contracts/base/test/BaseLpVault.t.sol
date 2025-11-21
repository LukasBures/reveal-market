// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {BaseLpVault} from "../src/BaseLpVault.sol";

contract MockUSDC is ERC20 {
    constructor() ERC20("Mock USDC", "mUSDC") {}

    function decimals() public pure override returns (uint8) {
        return 6;
    }

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}

contract MockUSDC9 is ERC20 {
    constructor() ERC20("Mock USDC 9", "mUSDC9") {}

    function decimals() public pure override returns (uint8) {
        return 9;
    }

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}

contract FeeOnTransferUSDC is MockUSDC {
    uint256 private constant FEE = 1; // 1 unit (1e-6 USDC) to simulate fee-on-transfer behavior.

    function transfer(address to, uint256 amount) public override returns (bool) {
        uint256 amountAfterFee = amount - FEE;
        return super.transfer(to, amountAfterFee);
    }

    function transferFrom(address from, address to, uint256 amount) public override returns (bool) {
        uint256 amountAfterFee = amount - FEE;
        return super.transferFrom(from, to, amountAfterFee);
    }
}

contract DirectionalFeeUSDC is MockUSDC {
    uint256 private constant FEE = 1;
    address public feeTarget;

    function setFeeTarget(address target) external {
        feeTarget = target;
    }

    function transfer(address to, uint256 amount) public override returns (bool) {
        if (feeTarget != address(0) && to == feeTarget) {
            uint256 amountAfterFee = amount - FEE;
            return super.transfer(to, amountAfterFee);
        }
        return super.transfer(to, amount);
    }

    function transferFrom(address from, address to, uint256 amount) public override returns (bool) {
        if (feeTarget != address(0) && to == feeTarget) {
            uint256 amountAfterFee = amount - FEE;
            return super.transferFrom(from, to, amountAfterFee);
        }
        return super.transferFrom(from, to, amount);
    }
}

contract BaseLpVaultTest is Test {
    uint256 private constant ONE_USDC = 1e6;

    MockUSDC internal usdc;
    BaseLpVault internal vault;
    address internal hedger = address(0xBEEF);
    address internal lp1 = address(0xA11CE);
    address internal lp2 = address(0xB0B);

    function setUp() public {
        usdc = new MockUSDC();
        vault = new BaseLpVault(usdc, address(this), hedger);

        usdc.mint(lp1, 1_000_000 * ONE_USDC);
        usdc.mint(lp2, 1_000_000 * ONE_USDC);
    }

    function testDecimalsAndAssetMetadata() public view {
        assertEq(vault.decimals(), 18);
        assertEq(address(vault.ASSET()), address(usdc));
    }

    function testInitialDepositMintsOneToOneShares() public {
        uint256 amount = 100 * ONE_USDC;
        uint256 minted = _deposit(lp1, amount);

        assertEq(minted, amount);
        assertEq(vault.balanceOf(lp1), amount);
        assertEq(vault.totalSupply(), amount);
        assertEq(vault.totalAssets(), amount);
        assertEq(vault.idleAssets(), amount);
    }

    function testSubsequentDepositUsesPricePerShare() public {
        uint256 first = _deposit(lp1, 100 * ONE_USDC);
        assertEq(first, 100 * ONE_USDC);

        uint256 second = _deposit(lp2, 50 * ONE_USDC);
        assertEq(second, 50 * ONE_USDC);

        assertEq(vault.totalSupply(), 150 * ONE_USDC);
        assertEq(vault.totalAssets(), 150 * ONE_USDC);
    }

    function testWithdrawBurnsSharesAndReturnsAssets() public {
        _deposit(lp1, 120 * ONE_USDC);

        vm.startPrank(lp1);
        uint256 sharesToBurn = vault.withdraw(20 * ONE_USDC, lp1, lp1);
        vm.stopPrank();

        assertEq(sharesToBurn, 20 * ONE_USDC);
        assertEq(vault.balanceOf(lp1), 100 * ONE_USDC);
        assertEq(usdc.balanceOf(lp1), 20 * ONE_USDC + (1_000_000 - 120) * ONE_USDC);
        assertEq(vault.totalAssets(), 100 * ONE_USDC);
        assertEq(vault.idleAssets(), 100 * ONE_USDC);
    }

    function testRedeemKeepsPricePerShare() public {
        _deposit(lp1, 200 * ONE_USDC);
        _deposit(lp2, 100 * ONE_USDC);

        vm.startPrank(lp2);
        uint256 assetsOut = vault.redeem(30 * ONE_USDC, lp2, lp2);
        vm.stopPrank();

        assertEq(assetsOut, 30 * ONE_USDC);
        assertEq(vault.balanceOf(lp2), 70 * ONE_USDC);
        assertEq(vault.totalSupply(), 270 * ONE_USDC);
        assertEq(vault.totalAssets(), 270 * ONE_USDC);
    }

    function testBorrowAndRepayMaintainTotalAssets() public {
        _deposit(lp1, 200 * ONE_USDC);
        uint256 totalBefore = vault.totalAssets();

        vm.prank(hedger);
        vault.borrowForHedge(60 * ONE_USDC, hedger);

        assertEq(vault.utilizedAssets(), 60 * ONE_USDC);
        assertEq(vault.idleAssets(), 140 * ONE_USDC);
        assertEq(vault.totalAssets(), totalBefore);

        vm.startPrank(hedger);
        usdc.approve(address(vault), type(uint256).max);
        vault.repayFromHedge(60 * ONE_USDC, hedger);
        vm.stopPrank();

        assertEq(vault.utilizedAssets(), 0);
        assertEq(vault.idleAssets(), totalBefore);
        assertEq(vault.totalAssets(), totalBefore);
    }

    function testWithdrawRevertsWhenInsufficientIdle() public {
        _deposit(lp1, 100 * ONE_USDC);

        vm.prank(hedger);
        vault.borrowForHedge(80 * ONE_USDC, hedger);

        vm.startPrank(lp1);
        vm.expectRevert(BaseLpVault.InsufficientIdleAssets.selector);
        vault.withdraw(30 * ONE_USDC, lp1, lp1);
        vm.stopPrank();
    }

    function testBorrowChecksIdleBalance() public {
        _deposit(lp1, 50 * ONE_USDC);

        vm.prank(hedger);
        vault.borrowForHedge(40 * ONE_USDC, hedger);

        vm.prank(hedger);
        vm.expectRevert(BaseLpVault.InsufficientIdleAssets.selector);
        vault.borrowForHedge(20 * ONE_USDC, hedger);
    }

    function testUtilizationCapDefaultAllowsFull() public {
        _deposit(lp1, 100 * ONE_USDC);

        vm.prank(hedger);
        vault.borrowForHedge(100 * ONE_USDC, hedger);

        assertEq(vault.utilizedAssets(), 100 * ONE_USDC);
    }

    function testUtilizationCapEnforced() public {
        _deposit(lp1, 100 * ONE_USDC);
        vault.setMaxUtilizationBps(5_000);

        vm.prank(hedger);
        vm.expectRevert(BaseLpVault.UtilizationCapExceeded.selector);
        vault.borrowForHedge(60 * ONE_USDC, hedger);

        vm.prank(hedger);
        vault.borrowForHedge(50 * ONE_USDC, hedger);
    }

    function testSetMaxUtilizationOnlyOwner() public {
        vm.prank(lp1);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, lp1));
        vault.setMaxUtilizationBps(4_000);

        uint16 previous = vault.maxUtilizationBps();
        vm.expectEmit();
        emit BaseLpVault.MaxUtilizationBpsUpdated(previous, 8_000);
        vault.setMaxUtilizationBps(8_000);
        assertEq(vault.maxUtilizationBps(), 8_000);
    }

    function testSetMaxUtilizationRevertsAbove100Percent() public {
        vm.expectRevert(BaseLpVault.InvalidAmount.selector);
        vault.setMaxUtilizationBps(10_001);
    }

    function testUtilizationCapAfterPartialRepay() public {
        _deposit(lp1, 200 * ONE_USDC);
        vault.setMaxUtilizationBps(5_000); // 50%

        vm.prank(hedger);
        vault.borrowForHedge(100 * ONE_USDC, hedger);

        vm.startPrank(hedger);
        usdc.approve(address(vault), type(uint256).max);
        vault.repayFromHedge(20 * ONE_USDC, hedger);
        vm.stopPrank();

        vm.prank(hedger);
        vm.expectRevert(BaseLpVault.UtilizationCapExceeded.selector);
        vault.borrowForHedge(50 * ONE_USDC, hedger);

        vm.prank(hedger);
        vault.borrowForHedge(20 * ONE_USDC, hedger); // utilization returns to cap
    }

    function testRecoverTokenOnlyOwner() public {
        ERC20 stray = new MockUSDC();
        MockUSDC(address(stray)).mint(address(vault), 10);

        vm.prank(lp1);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, lp1));
        vault.recoverToken(address(stray), lp1, 1);
    }

    function testRecoverToken() public {
        ERC20 stray = new MockUSDC();
        MockUSDC(address(stray)).mint(address(vault), 100);

        vm.expectEmit();
        emit BaseLpVault.RecoveredToken(address(stray), lp1, 100);
        vault.recoverToken(address(stray), lp1, 100);
        assertEq(stray.balanceOf(lp1), 100);

        vm.expectRevert(BaseLpVault.InvalidToken.selector);
        vault.recoverToken(address(usdc), lp1, 1);

        vm.expectRevert(BaseLpVault.InvalidReceiver.selector);
        vault.recoverToken(address(stray), address(0), 1);
    }

    function testPartialRepayUpdatesAccounting() public {
        _deposit(lp1, 200 * ONE_USDC);

        vm.prank(hedger);
        vault.borrowForHedge(80 * ONE_USDC, hedger);

        vm.startPrank(hedger);
        usdc.approve(address(vault), type(uint256).max);
        vault.repayFromHedge(30 * ONE_USDC, hedger);
        vm.stopPrank();

        assertEq(vault.utilizedAssets(), 50 * ONE_USDC);
        assertEq(vault.idleAssets(), 150 * ONE_USDC);
        assertEq(vault.totalAssets(), 200 * ONE_USDC);
    }

    function testRepayCannotExceedUtilized() public {
        _deposit(lp1, 100 * ONE_USDC);

        vm.prank(hedger);
        vault.borrowForHedge(30 * ONE_USDC, hedger);

        vm.startPrank(hedger);
        usdc.approve(address(vault), type(uint256).max);
        vm.expectRevert(BaseLpVault.RepayExceedsUtilized.selector);
        vault.repayFromHedge(40 * ONE_USDC, hedger);
        vm.stopPrank();
    }

    function testRepayTracksExternalPayer() public {
        _deposit(lp1, 120 * ONE_USDC);
        vm.prank(hedger);
        vault.borrowForHedge(50 * ONE_USDC, hedger);

        address payer = address(0xC0FFEE);
        usdc.mint(payer, 100 * ONE_USDC);

        vm.startPrank(hedger);
        vm.expectRevert(BaseLpVault.InvalidAmount.selector);
        vault.repayFromHedge(0, payer);
        vm.stopPrank();

        vm.startPrank(hedger);
        usdc.approve(address(vault), 0);
        vm.stopPrank();

        vm.startPrank(hedger);
        usdc.approve(address(vault), 0);
        vm.stopPrank();

        vm.startPrank(hedger);
        usdc.approve(address(vault), 0);
        vm.stopPrank();

        vm.startPrank(payer);
        usdc.approve(address(vault), type(uint256).max);
        vm.stopPrank();

        vm.startPrank(hedger);
        vault.repayFromHedge(50 * ONE_USDC, payer);
        vm.stopPrank();

        assertEq(vault.utilizedAssets(), 0);
        assertEq(vault.idleAssets(), 120 * ONE_USDC);
    }

    function testOnlyHedgerMayBorrowOrRepay() public {
        _deposit(lp1, 100 * ONE_USDC);

        vm.prank(lp1);
        vm.expectRevert(abi.encodeWithSelector(BaseLpVault.NotHedger.selector, lp1));
        vault.borrowForHedge(10 * ONE_USDC, lp1);

        vm.prank(lp1);
        vm.expectRevert(abi.encodeWithSelector(BaseLpVault.NotHedger.selector, lp1));
        vault.repayFromHedge(10 * ONE_USDC, lp1);
    }

    function testPauseBlocksStateChanges() public {
        vault.pause();

        vm.startPrank(lp1);
        usdc.approve(address(vault), type(uint256).max);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        vault.deposit(10 * ONE_USDC, lp1);
        vm.stopPrank();

        vm.prank(hedger);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        vault.borrowForHedge(1 * ONE_USDC, hedger);
    }

    function testSetHedgerOnlyOwner() public {
        address newHedger = address(0xCAFE);

        vm.prank(lp1);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, lp1));
        vault.setHedger(newHedger);

        vault.setHedger(newHedger);
        assertEq(vault.hedger(), newHedger);
    }

    function testHedgerUpdateRevokesOldHedger() public {
        address newHedger = address(0xCAFE);
        vault.setHedger(newHedger);

        _deposit(lp1, 40 * ONE_USDC);

        vm.prank(hedger);
        vm.expectRevert(abi.encodeWithSelector(BaseLpVault.NotHedger.selector, hedger));
        vault.borrowForHedge(10 * ONE_USDC, hedger);

        vm.prank(newHedger);
        vault.borrowForHedge(10 * ONE_USDC, newHedger);
    }

    function testHedgerUpdateEmitsEvent() public {
        address newHedger = address(0xDEAD);

        vm.expectEmit();
        emit BaseLpVault.HedgerUpdated(hedger, newHedger);
        vault.setHedger(newHedger);
    }

    function testConvertHelpersTrackUtilization() public {
        _deposit(lp1, 100 * ONE_USDC);

        vm.prank(hedger);
        vault.borrowForHedge(40 * ONE_USDC, hedger);

        uint256 supply = vault.totalSupply();
        uint256 total = vault.totalAssets();

        assertEq(vault.convertToAssets(supply), total);
        assertEq(vault.convertToShares(total), supply);
        assertEq(vault.idleAssets() + vault.utilizedAssets(), total);
    }

    function testPricePerShareRespectsUtilizationDuringDeposit() public {
        _deposit(lp1, 100 * ONE_USDC);

        vm.prank(hedger);
        vault.borrowForHedge(60 * ONE_USDC, hedger);

        uint256 minted = _deposit(lp2, 100 * ONE_USDC);
        assertEq(minted, 100 * ONE_USDC);

        assertEq(vault.totalSupply(), 200 * ONE_USDC);
        assertEq(vault.totalAssets(), 200 * ONE_USDC);
        assertEq(vault.utilizedAssets(), 60 * ONE_USDC);
        assertEq(vault.idleAssets(), 140 * ONE_USDC);
    }

    function testDonationAccruesToExistingLps() public {
        _deposit(lp1, 100 * ONE_USDC);

        // Simulate hedging profit returned directly to vault (does not change utilizedAssets).
        usdc.mint(hedger, 50 * ONE_USDC);
        vm.prank(hedger);
        assertTrue(usdc.transfer(address(vault), 50 * ONE_USDC));

        assertEq(vault.totalAssets(), 150 * ONE_USDC);
        assertEq(vault.idleAssets(), 150 * ONE_USDC);

        uint256 minted = _deposit(lp2, 150 * ONE_USDC);
        assertEq(minted, 100 * ONE_USDC); // price per share is 1.5.

        assertEq(vault.totalSupply(), 200 * ONE_USDC);
        assertEq(vault.totalAssets(), 300 * ONE_USDC);
        assertEq(vault.convertToAssets(vault.balanceOf(lp1)), 150 * ONE_USDC);
    }

    function testDepositRejectsZeroReceiver() public {
        usdc.mint(address(this), 10 * ONE_USDC);
        usdc.approve(address(vault), type(uint256).max);
        vm.expectRevert(BaseLpVault.InvalidReceiver.selector);
        vault.deposit(1 * ONE_USDC, address(0));
    }

    function testWithdrawRejectsZeroReceiverOrOwner() public {
        _deposit(lp1, 20 * ONE_USDC);

        vm.prank(lp1);
        vm.expectRevert(BaseLpVault.InvalidReceiver.selector);
        vault.withdraw(10 * ONE_USDC, address(0), lp1);

        vm.prank(lp1);
        vm.expectRevert(BaseLpVault.InvalidOwner.selector);
        vault.withdraw(10 * ONE_USDC, lp1, address(0));
    }

    function testRedeemRejectsZeroReceiverOrOwner() public {
        uint256 minted = _deposit(lp1, 30 * ONE_USDC);

        vm.prank(lp1);
        vm.expectRevert(BaseLpVault.InvalidReceiver.selector);
        vault.redeem(minted, address(0), lp1);

        vm.prank(lp1);
        vm.expectRevert(BaseLpVault.InvalidOwner.selector);
        vault.redeem(minted, lp1, address(0));
    }

    function testWithdrawUsesAllowanceWhenCallerDiffers() public {
        uint256 minted = _deposit(lp1, 80 * ONE_USDC);
        address caller = address(0xD00D);

        vm.prank(lp1);
        vault.approve(caller, minted);

        vm.prank(caller);
        uint256 burned = vault.withdraw(30 * ONE_USDC, lp1, lp1);

        assertEq(burned, 30 * ONE_USDC);
        assertEq(vault.balanceOf(lp1), 50 * ONE_USDC);
        assertEq(vault.totalAssets(), 50 * ONE_USDC);
    }

    function testRedeemUsesAllowanceWhenCallerDiffers() public {
        uint256 minted = _deposit(lp1, 90 * ONE_USDC);
        address caller = address(0xF00D);

        vm.prank(lp1);
        vault.approve(caller, minted);

        vm.prank(caller);
        uint256 assetsOut = vault.redeem(20 * ONE_USDC, lp1, lp1);

        assertEq(assetsOut, 20 * ONE_USDC);
        assertEq(vault.balanceOf(lp1), 70 * ONE_USDC);
        assertEq(vault.totalAssets(), 70 * ONE_USDC);
    }

    function testEventsFireForBorrowAndRepay() public {
        _deposit(lp1, 100 * ONE_USDC);
        vm.startPrank(hedger);
        usdc.approve(address(vault), type(uint256).max);

        vm.expectEmit();
        emit BaseLpVault.BorrowForHedge(hedger, hedger, 40 * ONE_USDC, 40 * ONE_USDC, 20_000);
        vault.borrowForHedge(40 * ONE_USDC, hedger);

        vm.expectEmit();
        emit BaseLpVault.RepayFromHedge(hedger, hedger, 40 * ONE_USDC, 0, 0);
        vault.repayFromHedge(40 * ONE_USDC, hedger);
        vm.stopPrank();
    }

    function testPauseBlocksWithdrawAndRedeem() public {
        _deposit(lp1, 60 * ONE_USDC);
        vault.pause();

        vm.prank(lp1);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        vault.withdraw(10 * ONE_USDC, lp1, lp1);

        vm.prank(lp1);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        vault.redeem(10 * ONE_USDC, lp1, lp1);

        vm.prank(hedger);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        vault.repayFromHedge(1 * ONE_USDC, hedger);
    }

    function testZeroAmountReverts() public {
        vm.startPrank(lp1);
        usdc.approve(address(vault), type(uint256).max);
        vm.expectRevert(BaseLpVault.InvalidAmount.selector);
        vault.deposit(0, lp1);
        vm.stopPrank();

        vm.expectRevert(BaseLpVault.InvalidAmount.selector);
        vault.withdraw(0, lp1, lp1);

        vm.expectRevert(BaseLpVault.InvalidAmount.selector);
        vault.redeem(0, lp1, lp1);

        vm.prank(hedger);
        vm.expectRevert(BaseLpVault.InvalidAmount.selector);
        vault.borrowForHedge(0, lp1);

        vm.prank(hedger);
        vm.expectRevert(BaseLpVault.InvalidAmount.selector);
        vault.repayFromHedge(0, lp1);
    }

    function testBorrowRejectsZeroReceiver() public {
        _deposit(lp1, 10 * ONE_USDC);

        vm.prank(hedger);
        vm.expectRevert(BaseLpVault.InvalidReceiver.selector);
        vault.borrowForHedge(1 * ONE_USDC, address(0));
    }

    function testRedeemFailsIfIdleInsufficient() public {
        _deposit(lp1, 100 * ONE_USDC);

        vm.prank(hedger);
        vault.borrowForHedge(90 * ONE_USDC, hedger);

        vm.prank(lp1);
        vm.expectRevert(BaseLpVault.InsufficientIdleAssets.selector);
        vault.redeem(20 * ONE_USDC, lp1, lp1);
    }

    function testConvertHelpersWhenEmpty() public view {
        assertEq(vault.totalAssets(), 0);
        assertEq(vault.idleAssets(), 0);
        assertEq(vault.convertToShares(10 * ONE_USDC), 10 * ONE_USDC);
        assertEq(vault.convertToAssets(1e18), 0);
    }

    function testConstructorValidations() public {
        vm.expectRevert(abi.encodeWithSelector(BaseLpVault.InvalidAsset.selector, address(0)));
        new BaseLpVault(IERC20(address(0)), address(this), hedger);

        MockUSDC usdc2 = new MockUSDC();
        vm.expectRevert(abi.encodeWithSelector(BaseLpVault.InvalidHedger.selector, address(0)));
        new BaseLpVault(usdc2, address(this), address(0));

        MockUSDC9 usdc9 = new MockUSDC9();
        vm.expectRevert(abi.encodeWithSelector(BaseLpVault.InvalidAssetDecimals.selector, 6, 9));
        new BaseLpVault(usdc9, address(this), hedger);
    }

    function testSetHedgerZeroReverts() public {
        vm.expectRevert(abi.encodeWithSelector(BaseLpVault.InvalidHedger.selector, address(0)));
        vault.setHedger(address(0));
    }

    function testDepositRevertsForFeeOnTransferAsset() public {
        FeeOnTransferUSDC foT = new FeeOnTransferUSDC();
        BaseLpVault foTVault = new BaseLpVault(foT, address(this), hedger);
        foT.mint(lp1, 100 * ONE_USDC);

        vm.startPrank(lp1);
        foT.approve(address(foTVault), type(uint256).max);
        vm.expectRevert(BaseLpVault.InvalidAmount.selector);
        foTVault.deposit(10 * ONE_USDC, lp1);
        vm.stopPrank();
    }

    function testRepayRevertsForFeeOnTransferAsset() public {
        DirectionalFeeUSDC token = new DirectionalFeeUSDC();
        BaseLpVault feeVault = new BaseLpVault(token, address(this), hedger);

        token.mint(lp1, 200 * ONE_USDC);
        token.mint(hedger, 100 * ONE_USDC);

        vm.startPrank(lp1);
        token.approve(address(feeVault), type(uint256).max);
        feeVault.deposit(100 * ONE_USDC, lp1); // no fee target set yet
        vm.stopPrank();

        token.setFeeTarget(address(feeVault));

        vm.prank(hedger);
        feeVault.borrowForHedge(50 * ONE_USDC, hedger);

        vm.startPrank(hedger);
        token.approve(address(feeVault), type(uint256).max);
        vm.expectRevert(BaseLpVault.InvalidAmount.selector);
        feeVault.repayFromHedge(50 * ONE_USDC, hedger);
        vm.stopPrank();
    }

    function _deposit(address user, uint256 amount) internal returns (uint256 minted) {
        vm.startPrank(user);
        usdc.approve(address(vault), amount);
        minted = vault.deposit(amount, user);
        vm.stopPrank();
    }
}
