// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {HedgeStrategyExecutor} from "../src/HedgeStrategyExecutor.sol";
import {BaseLpVault} from "../src/BaseLpVault.sol";
import {MockUSDC} from "./BaseLpVault.t.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";

contract HedgeStrategyExecutorTest is Test {
    uint256 private constant ONE_USDC = 1e6;
    uint16 private constant DEFAULT_SLIPPAGE_BPS = 500; // 5%

    MockUSDC internal usdc;
    BaseLpVault internal vault;
    HedgeStrategyExecutor internal executor;

    address internal lp = address(0xA11CE);
    address internal hedgerReceiver = address(0xBEEF);

    uint256 internal signerPk;
    address internal signer;

    function setUp() public {
        vm.chainId(137); // Simulate Polygon chain id for EIP-712 domain separation.

        usdc = new MockUSDC();
        vault = new BaseLpVault(usdc, address(this), address(this)); // temporary hedger = owner
        signerPk = 0xDEADBEEF;
        signer = vm.addr(signerPk);

        executor = new HedgeStrategyExecutor(
            vault,
            signer,
            address(this),
            1_000_000 * ONE_USDC, // default per-order cap = 1m USDC
            DEFAULT_SLIPPAGE_BPS
        );

        // Wire executor as the vault hedger and allow the default receiver.
        vault.setHedger(address(executor));
        executor.setReceiverAllowed(hedgerReceiver, true);

        // Seed LP and vault liquidity.
        usdc.mint(lp, 2_000_000 * ONE_USDC);
        vm.startPrank(lp);
        usdc.approve(address(vault), type(uint256).max);
        vault.deposit(1_000_000 * ONE_USDC, lp);
        vm.stopPrank();
    }

    function testExecuteBorrowHappyPath() public {
        HedgeStrategyExecutor.Order memory order = _order(100_000 * ONE_USDC);
        bytes32 orderHash = executor.hashOrder(order);
        bytes memory sig = _sign(orderHash);

        vm.expectEmit(true, true, false, true);
        emit HedgeStrategyExecutor.HedgeOrderExecuted(
            orderHash,
            order.receiver,
            order.amount,
            order.minOut,
            order.maxSlippageBps,
            order.deadline
        );

        executor.executeBorrow(order, sig);

        assertEq(vault.utilizedAssets(), order.amount);
        assertEq(vault.idleAssets(), 900_000 * ONE_USDC);
        assertTrue(executor.usedNonces(order.nonce));
    }

    function testReplayNonceRejected() public {
        HedgeStrategyExecutor.Order memory order = _order(50_000 * ONE_USDC);
        bytes32 orderHash = executor.hashOrder(order);
        bytes memory sig = _sign(orderHash);
        executor.executeBorrow(order, sig);

        vm.expectRevert(HedgeStrategyExecutor.NonceUsed.selector);
        executor.executeBorrow(order, sig);
    }

    function testExpiredOrderReverts() public {
        HedgeStrategyExecutor.Order memory order = _order(10_000 * ONE_USDC);
        order.deadline = block.timestamp - 1;
        bytes32 orderHash = executor.hashOrder(order);
        bytes memory sig = _sign(orderHash);

        vm.expectRevert(HedgeStrategyExecutor.OrderExpired.selector);
        executor.executeBorrow(order, sig);
    }

    function testInvalidSignatureReverts() public {
        HedgeStrategyExecutor.Order memory order = _order(75_000 * ONE_USDC);
        bytes32 orderHash = executor.hashOrder(order);
        // Sign with a different key so recovery fails.
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(1, orderHash);
        bytes memory badSig = abi.encodePacked(r, s, v);

        vm.expectRevert(HedgeStrategyExecutor.InvalidSigner.selector);
        executor.executeBorrow(order, badSig);
    }

    function testReceiverWhitelistEnforced() public {
        HedgeStrategyExecutor.Order memory order = _order(25_000 * ONE_USDC);
        order.receiver = address(0x123);
        bytes32 orderHash = executor.hashOrder(order);
        bytes memory sig = _sign(orderHash);

        vm.expectRevert(HedgeStrategyExecutor.ReceiverNotAllowed.selector);
        executor.executeBorrow(order, sig);
    }

    function testAmountCapEnforced() public {
        HedgeStrategyExecutor.Order memory order = _order(1_000_001 * ONE_USDC);
        bytes32 orderHash = executor.hashOrder(order);
        bytes memory sig = _sign(orderHash);

        vm.expectRevert(HedgeStrategyExecutor.InvalidAmount.selector);
        executor.executeBorrow(order, sig);
    }

    function testSlippageCapEnforced() public {
        HedgeStrategyExecutor.Order memory order = _order(10_000 * ONE_USDC);
        order.maxSlippageBps = DEFAULT_SLIPPAGE_BPS + 1;
        bytes32 orderHash = executor.hashOrder(order);
        bytes memory sig = _sign(orderHash);

        vm.expectRevert(HedgeStrategyExecutor.SlippageTooHigh.selector);
        executor.executeBorrow(order, sig);
    }

    function testPauseBlocksExecution() public {
        HedgeStrategyExecutor.Order memory order = _order(5_000 * ONE_USDC);
        bytes32 orderHash = executor.hashOrder(order);
        bytes memory sig = _sign(orderHash);

        executor.pause();
        vm.expectRevert(Pausable.EnforcedPause.selector);
        executor.executeBorrow(order, sig);
    }

    function testAdminUpdates() public {
        address newSigner = address(0x999);
        executor.setSigner(newSigner);
        assertEq(executor.signer(), newSigner);

        executor.setMaxOrderAmount(500_000 * ONE_USDC);
        assertEq(executor.maxOrderAmount(), 500_000 * ONE_USDC);

        executor.setMaxSlippageBps(100);
        assertEq(executor.maxSlippageBps(), 100);

        executor.setReceiverAllowed(hedgerReceiver, false);
        assertFalse(executor.receiverAllowed(hedgerReceiver));
    }

    function testBorrowRespectsVaultIdleAssets() public {
        executor.setMaxOrderAmount(2_000_000 * ONE_USDC); // allow large asks
        HedgeStrategyExecutor.Order memory order = _order(1_200_000 * ONE_USDC); // exceeds idle assets in vault
        bytes32 orderHash = executor.hashOrder(order);
        bytes memory sig = _sign(orderHash);

        vm.expectRevert(BaseLpVault.InsufficientIdleAssets.selector);
        executor.executeBorrow(order, sig);
    }

    function testHashOrderMatchesEip712() public view {
        HedgeStrategyExecutor.Order memory order = _order(42_000 * ONE_USDC);
        bytes32 expected = executor.hashOrder(order);

        assertTrue(expected != bytes32(0));
    }

    // ----------------------
    // Helpers
    // ----------------------

    function _order(uint256 amount) internal view returns (HedgeStrategyExecutor.Order memory) {
        return HedgeStrategyExecutor.Order({
            receiver: hedgerReceiver,
            amount: amount,
            minOut: amount, // off-chain use only; emitted for monitoring
            maxSlippageBps: DEFAULT_SLIPPAGE_BPS,
            deadline: block.timestamp + 1 hours,
            nonce: keccak256(abi.encodePacked(address(this), amount, block.number))
        });
    }

    function _sign(bytes32 orderHash) internal view returns (bytes memory sig) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(signerPk, orderHash);
        sig = abi.encodePacked(r, s, v);
    }
}
