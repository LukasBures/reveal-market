// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

import {RevealMarket} from "../src/RevealMarket.sol";
import {RakeManager} from "../src/RakeManager.sol";
import {Verifier} from "../src/Verifier.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

contract RevealMarketTest is Test {
    RevealMarket private market;
    RakeManager private rakeManager;
    Verifier private verifier;
    MockERC20 private collateralToken;

    address private constant ORACLE = address(0xA11CE);
    address payable private constant TREASURY = payable(address(0xB0B));
    address private constant WINNER = address(0xC0FFEE);
    address private constant LOSER = address(0xD00D);

    string private constant OUTCOME = "TEAM_A";
    bytes32 private constant OUTCOME_HASH = keccak256(bytes(OUTCOME));
    bytes32 private constant WIN_SALT = bytes32(uint256(1));
    bytes32 private constant LOSE_SALT = bytes32(uint256(2));

    uint256 private commitDeadline;
    uint256 private revealDeadline;
    uint256 private constant STAKE = 100e6; // 100 USDC with 6 decimals
    string private constant METADATA_URI = "ipfs://market/EVT-1";

    function setUp() public {
        market = new RevealMarket();
        rakeManager = new RakeManager(address(this), TREASURY, 100); // 1% rake
        verifier = new Verifier();
        collateralToken = new MockERC20("USD Coin", "USDC", 6);

        commitDeadline = block.timestamp + 1 days;
        revealDeadline = commitDeadline + 1 days;

        market.initialize(
            "EVT-1",
            commitDeadline,
            revealDeadline,
            ORACLE,
            address(verifier),
            address(rakeManager),
            address(TREASURY),
            address(collateralToken),
            address(this),
            METADATA_URI
        );
    }

    function _commitTicket(address bettor, bytes32 salt, bytes32 outcomeHash, uint256 stake) private {
        vm.deal(bettor, 1 ether);
        collateralToken.mint(bettor, stake);
        vm.prank(bettor);
        collateralToken.approve(address(market), stake);
        bytes32 ticketHash = keccak256(abi.encodePacked(bettor, outcomeHash, salt));
        vm.prank(bettor);
        market.commit(ticketHash, stake);
    }

    function testCommitAndClaimFlow() public {
        assertEq(market.collateral(), address(collateralToken));
        assertEq(market.metadataURI(), METADATA_URI);

        _commitTicket(WINNER, WIN_SALT, OUTCOME_HASH, STAKE);
        _commitTicket(LOSER, LOSE_SALT, keccak256(bytes("TEAM_B")), STAKE);

        RevealMarket.Ticket memory ticketBefore = market.ticketInfo(WINNER, 0);
        assertEq(ticketBefore.amount, STAKE);
        assertTrue(!ticketBefore.claimed);
        assertTrue(!ticketBefore.revealed);

        vm.warp(commitDeadline + 1);
        market.lock();

        vm.prank(ORACLE);
        market.postResult(OUTCOME_HASH);

        uint256[4] memory pubSignals;
        pubSignals[0] = STAKE;

        bytes memory proof = "";
        market.verifyProof(proof, pubSignals);

        assertEq(uint256(market.phase()), uint256(RevealMarket.Phase.Settled));
        assertEq(market.winningPool(), STAKE);
        uint256 expectedGross = STAKE * 2;
        uint256 expectedRake = (expectedGross * 100) / 10_000;
        assertEq(market.totalPool(), expectedGross - expectedRake);
        assertEq(collateralToken.balanceOf(TREASURY), expectedRake);
        assertEq(market.remainingPayoutPool(), collateralToken.balanceOf(address(market)));

        (uint256 previewPayout, bool previewClaimable) = market.payoutPreview(WINNER, 0, OUTCOME, WIN_SALT);
        assertTrue(previewClaimable);
        assertEq(previewPayout, market.totalPool());

        uint256 winnerBalanceBefore = collateralToken.balanceOf(WINNER);
        vm.prank(WINNER);
        market.claim(0, OUTCOME, WIN_SALT);
        assertEq(collateralToken.balanceOf(WINNER), winnerBalanceBefore + previewPayout);

        RevealMarket.Ticket memory ticketAfter = market.ticketInfo(WINNER, 0);
        assertTrue(ticketAfter.claimed);
        assertTrue(ticketAfter.revealed);

        (uint256 postClaimPreview, bool postClaimClaimable) = market.payoutPreview(WINNER, 0, OUTCOME, WIN_SALT);
        assertEq(postClaimPreview, 0);
        assertTrue(!postClaimClaimable);
        assertEq(collateralToken.balanceOf(address(market)), 0);
        assertEq(market.remainingPayoutPool(), 0);

        vm.prank(LOSER);
        vm.expectRevert(RevealMarket.TicketLoses.selector);
        market.claim(0, OUTCOME, LOSE_SALT);

        vm.expectRevert(RevealMarket.AlreadySettled.selector);
        market.refund();
    }

    function testCommitRevertsAfterDeadline() public {
        vm.warp(commitDeadline);
        vm.expectRevert(RevealMarket.InvalidTimestamp.selector);
        market.commit(bytes32(uint256(1)), STAKE);
    }

    function testLockRevertsBeforeDeadline() public {
        vm.expectRevert(RevealMarket.InvalidTimestamp.selector);
        market.lock();
    }

    function testPostResultOnlyOracle() public {
        vm.warp(commitDeadline + 1);
        market.lock();

        vm.expectRevert(RevealMarket.InvalidOracle.selector);
        market.postResult(OUTCOME_HASH);

        vm.prank(ORACLE);
        market.postResult(OUTCOME_HASH);
        vm.expectRevert(RevealMarket.OutcomeAlreadySet.selector);
        vm.prank(ORACLE);
        market.postResult(OUTCOME_HASH);
    }

    function testVerifyProofRequiresOutcome() public {
        vm.warp(commitDeadline + 1);
        market.lock();

        uint256[4] memory pubSignals;
        bytes memory proof = "";
        vm.expectRevert(RevealMarket.WinningPoolNotSet.selector);
        market.verifyProof(proof, pubSignals);
    }

    function testResultPostedEmitsEvent() public {
        bytes32 outcomeHash = OUTCOME_HASH;

        vm.warp(commitDeadline + 1);
        market.lock();

        vm.prank(ORACLE);
        vm.expectEmit(false, true, false, false);
        emit RevealMarket.ResultPosted(outcomeHash);
        market.postResult(outcomeHash);
    }

    function testVerifyProofRejectsWinningPoolAboveTotal() public {
        _commitTicket(WINNER, WIN_SALT, OUTCOME_HASH, STAKE);

        vm.warp(commitDeadline + 1);
        market.lock();

        vm.prank(ORACLE);
        market.postResult(OUTCOME_HASH);

        uint256[4] memory pubSignals;
        pubSignals[0] = STAKE * 2; // greater than total pool

        bytes memory proof = "";
        vm.expectRevert(RevealMarket.WinningPoolNotSet.selector);
        market.verifyProof(proof, pubSignals);
    }

    function testClaimRevertsWithWrongSalt() public {
        _commitTicket(WINNER, WIN_SALT, OUTCOME_HASH, STAKE);

        vm.warp(commitDeadline + 1);
        market.lock();

        vm.prank(ORACLE);
        market.postResult(OUTCOME_HASH);

        uint256[4] memory pubSignals;
        pubSignals[0] = STAKE;
        bytes memory proof = "";
        market.verifyProof(proof, pubSignals);

        vm.prank(WINNER);
        vm.expectRevert(RevealMarket.TicketLoses.selector);
        market.claim(0, OUTCOME, bytes32(uint256(999)));
    }

    function testRefundFlowWhenNotSettled() public {
        _commitTicket(WINNER, WIN_SALT, OUTCOME_HASH, STAKE);

        vm.warp(revealDeadline + 1);

        uint256 balanceBefore = collateralToken.balanceOf(WINNER);
        vm.prank(WINNER);
        market.refund();

        assertEq(collateralToken.balanceOf(WINNER), balanceBefore + STAKE);
        assertEq(market.totalPool(), 0);
        assertEq(collateralToken.balanceOf(address(market)), 0);

        vm.prank(WINNER);
        vm.expectRevert(RevealMarket.NothingToRefund.selector);
        market.refund();
    }

    function testInitializeEmitsEventAndCannotReinitialize() public {
        RevealMarket fresh = new RevealMarket();
        bytes memory initData = bytes("EVT-NEW");
        string memory eventId = string(initData);

        vm.expectEmit(true, true, false, true);
        emit RevealMarket.Initialized(
            eventId,
            ORACLE,
            commitDeadline,
            revealDeadline,
            address(collateralToken),
            address(this),
            METADATA_URI
        );
        fresh.initialize(
            eventId,
            commitDeadline,
            revealDeadline,
            ORACLE,
            address(verifier),
            address(rakeManager),
            address(TREASURY),
            address(collateralToken),
            address(this),
            METADATA_URI
        );

        vm.expectRevert(RevealMarket.AlreadyInitialized.selector);
        fresh.initialize(
            eventId,
            commitDeadline,
            revealDeadline,
            ORACLE,
            address(verifier),
            address(rakeManager),
            address(TREASURY),
            address(collateralToken),
            address(this),
            METADATA_URI
        );
    }

    function testPayoutPreviewBeforeSettlementReturnsFalse() public {
        _commitTicket(WINNER, WIN_SALT, OUTCOME_HASH, STAKE);

        (uint256 payoutAmount, bool claimable) = market.payoutPreview(WINNER, 0, OUTCOME, WIN_SALT);
        assertEq(payoutAmount, 0);
        assertTrue(!claimable);
    }

    function testCommitWithEtherRevertsForERC20Market() public {
        collateralToken.mint(WINNER, STAKE);
        vm.deal(WINNER, STAKE);
        vm.prank(WINNER);
        collateralToken.approve(address(market), STAKE);
        bytes32 ticketHash = keccak256(abi.encodePacked(WINNER, OUTCOME_HASH, WIN_SALT));
        vm.prank(WINNER);
        vm.expectRevert(RevealMarket.InvalidPayment.selector);
        market.commit{value: STAKE}(ticketHash, STAKE);
    }

    function testCommitZeroAmountReverts() public {
        bytes32 ticketHash = keccak256(abi.encodePacked(WINNER, OUTCOME_HASH, WIN_SALT));
        vm.expectRevert(RevealMarket.InvalidAmount.selector);
        market.commit(ticketHash, 0);
    }

    function testMetadataUpdate() public {
        string memory newURI = "ipfs://market/updated";
        vm.expectEmit(false, false, false, true);
        emit RevealMarket.MetadataUpdated(newURI);
        market.updateMetadataURI(newURI);
        assertEq(market.metadataURI(), newURI);
    }

    function testCancelMarketAllowsImmediateRefund() public {
        _commitTicket(WINNER, WIN_SALT, OUTCOME_HASH, STAKE);

        string memory reason = "oracle dispute";
        vm.expectEmit(false, false, false, true);
        emit RevealMarket.MarketCancelled(address(this), reason);
        market.cancelMarket(reason);
        assertEq(uint256(market.phase()), uint256(RevealMarket.Phase.Cancelled));
        assertEq(market.cancellationTimestamp(), block.timestamp);
        assertEq(market.cancellationReason(), reason);
        assertTrue(market.commitsPaused());
        assertTrue(market.claimsPaused());

        uint256 balanceBefore = collateralToken.balanceOf(WINNER);
        vm.prank(WINNER);
        market.refund();
        assertGt(collateralToken.balanceOf(WINNER), balanceBefore);
    }

    function testEmergencySettle() public {
        _commitTicket(WINNER, WIN_SALT, OUTCOME_HASH, STAKE);
        _commitTicket(LOSER, LOSE_SALT, keccak256(bytes("TEAM_B")), STAKE);

        vm.warp(commitDeadline + 1);
        market.lock();

        vm.prank(ORACLE);
        market.postResult(OUTCOME_HASH);

        vm.expectEmit(false, false, false, true);
        emit RevealMarket.EmergencySettled(OUTCOME_HASH, STAKE, address(this));
        market.emergencySettle(OUTCOME_HASH, STAKE);

        assertEq(uint256(market.phase()), uint256(RevealMarket.Phase.Settled));
        assertEq(market.winningPool(), STAKE);

        uint256[4] memory dummySignals;
        dummySignals[0] = STAKE;

        uint256 winnerBalanceBefore = collateralToken.balanceOf(WINNER);
        vm.prank(WINNER);
        market.claim(0, OUTCOME, WIN_SALT);
        assertGt(collateralToken.balanceOf(WINNER), winnerBalanceBefore);
    }

    function testUpdateOracle() public {
        address newOracle = address(0x123456);
        vm.expectEmit(true, true, false, false);
        emit RevealMarket.OracleUpdated(ORACLE, newOracle);
        market.updateOracle(newOracle);
        assertEq(market.oracle(), newOracle);
    }

    function testCancelMarketTwiceReverts() public {
        market.cancelMarket("reason");
        vm.expectRevert(RevealMarket.MarketAlreadyCancelled.selector);
        market.cancelMarket("again");
    }

    function testEmergencySettleUnauthorizedReverts() public {
        vm.expectRevert(RevealMarket.NotAuthorized.selector);
        vm.prank(WINNER);
        market.emergencySettle(OUTCOME_HASH, STAKE);
    }

    function testCommitPausedBlocksCommits() public {
        market.setCommitPaused(true);
        collateralToken.mint(WINNER, STAKE);
        vm.prank(WINNER);
        collateralToken.approve(address(market), STAKE);
        bytes32 ticketHash = keccak256(abi.encodePacked(WINNER, OUTCOME_HASH, WIN_SALT));
        vm.prank(WINNER);
        vm.expectRevert(RevealMarket.CommitPaused.selector);
        market.commit(ticketHash, STAKE);
    }

    function testCommitPauseOnlyController() public {
        vm.expectRevert(RevealMarket.NotAuthorized.selector);
        vm.prank(WINNER);
        market.setCommitPaused(true);

        market.setCommitPaused(true);
        market.setCommitPaused(false);
    }

    function testClaimPausedBlocksClaims() public {
        _commitTicket(WINNER, WIN_SALT, OUTCOME_HASH, STAKE);
        _commitTicket(LOSER, LOSE_SALT, keccak256(bytes("TEAM_B")), STAKE);

        vm.warp(commitDeadline + 1);
        market.lock();
        vm.prank(ORACLE);
        market.postResult(OUTCOME_HASH);
        uint256[4] memory pubSignals;
        pubSignals[0] = STAKE;
        market.verifyProof(new bytes(0), pubSignals);

        market.setClaimPaused(true);
        vm.prank(WINNER);
        vm.expectRevert(RevealMarket.ClaimPaused.selector);
        market.claim(0, OUTCOME, WIN_SALT);

        market.setClaimPaused(false);
        uint256 balanceBefore = collateralToken.balanceOf(WINNER);
        vm.prank(WINNER);
        market.claim(0, OUTCOME, WIN_SALT);
        assertGt(collateralToken.balanceOf(WINNER), balanceBefore);
    }

    function testGuardianUpdateFlow() public {
        address newGuardian = address(0xDEAD);
        market.setGuardian(newGuardian);
        assertEq(market.guardian(), newGuardian);

        vm.prank(newGuardian);
        market.setCommitPaused(true);
        vm.prank(newGuardian);
        market.setCommitPaused(false);

        vm.prank(newGuardian);
        market.setClaimPaused(true);
        vm.prank(newGuardian);
        market.setClaimPaused(false);
    }

    function testUnauthorizedGuardianActionsRevert() public {
        vm.expectRevert(RevealMarket.NotAuthorized.selector);
        vm.prank(WINNER);
        market.setCommitPaused(true);
    }

    function testRemainingPayoutPoolMatchesTokenBalance() public {
        _commitTicket(WINNER, WIN_SALT, OUTCOME_HASH, STAKE);
        assertEq(market.totalPool(), STAKE);
        assertEq(market.remainingPayoutPool(), collateralToken.balanceOf(address(market)));
    }

    function testTicketCountTracksUserDeposits() public {
        _commitTicket(WINNER, WIN_SALT, OUTCOME_HASH, STAKE);
        assertEq(market.ticketCount(WINNER), 1);
        _commitTicket(WINNER, bytes32(uint256(3)), OUTCOME_HASH, STAKE);
        assertEq(market.ticketCount(WINNER), 2);
    }
}

contract RevealMarketNativeTest is Test {
    RevealMarket private market;
    RakeManager private rakeManager;
    Verifier private verifier;

    address private constant ORACLE = address(0xAA11CE);
    address payable private constant TREASURY = payable(address(0xBB0B));
    address private constant WINNER = address(0xCC0FFEE);
    address private constant LOSER = address(0xDD00D);

    string private constant OUTCOME = "TEAM_A";
    bytes32 private constant OUTCOME_HASH = keccak256(bytes(OUTCOME));
    bytes32 private constant WIN_SALT = bytes32(uint256(11));
    bytes32 private constant LOSE_SALT = bytes32(uint256(22));

    uint256 private commitDeadline;
    uint256 private revealDeadline;
    uint256 private constant STAKE = 1 ether;
    string private constant NATIVE_METADATA_URI = "ipfs://market/native";

    function setUp() public {
        market = new RevealMarket();
        rakeManager = new RakeManager(address(this), TREASURY, 100);
        verifier = new Verifier();

        commitDeadline = block.timestamp + 1 days;
        revealDeadline = commitDeadline + 1 days;

        market.initialize(
            "EVT-NATIVE",
            commitDeadline,
            revealDeadline,
            ORACLE,
            address(verifier),
            address(rakeManager),
            address(TREASURY),
            address(0),
            address(this),
            NATIVE_METADATA_URI
        );
    }

    function _commitTicket(address bettor, bytes32 salt, bytes32 outcomeHash, uint256 stake) private {
        vm.deal(bettor, stake);
        bytes32 ticketHash = keccak256(abi.encodePacked(bettor, outcomeHash, salt));
        vm.prank(bettor);
        market.commit{value: stake}(ticketHash, stake);
    }

    function testNativeCommitAndClaimFlow() public {
        _commitTicket(WINNER, WIN_SALT, OUTCOME_HASH, STAKE);
        _commitTicket(LOSER, LOSE_SALT, keccak256(bytes("TEAM_B")), STAKE);

        vm.warp(commitDeadline + 1);
        market.lock();

        vm.prank(ORACLE);
        market.postResult(OUTCOME_HASH);

        uint256[4] memory pubSignals;
        pubSignals[0] = STAKE;

        uint256 treasuryBefore = TREASURY.balance;
        market.verifyProof(new bytes(0), pubSignals);

        uint256 expectedGross = STAKE * 2;
        uint256 expectedRake = (expectedGross * 100) / 10_000;
        assertEq(TREASURY.balance, treasuryBefore + expectedRake);
        assertEq(market.totalPool(), expectedGross - expectedRake);
        assertEq(market.remainingPayoutPool(), address(market).balance);
        assertEq(market.winningPool(), STAKE);

        (uint256 previewPayout, bool claimable) = market.payoutPreview(WINNER, 0, OUTCOME, WIN_SALT);
        assertTrue(claimable);
        assertEq(previewPayout, market.totalPool());

        uint256 winnerBalanceBefore = WINNER.balance;
        vm.prank(WINNER);
        market.claim(0, OUTCOME, WIN_SALT);
        assertEq(WINNER.balance, winnerBalanceBefore + previewPayout);
        assertEq(address(market).balance, 0);

        vm.prank(LOSER);
        vm.expectRevert(RevealMarket.TicketLoses.selector);
        market.claim(0, OUTCOME, LOSE_SALT);

        vm.expectRevert(RevealMarket.AlreadySettled.selector);
        market.refund();
    }

    function testNativeRefundFlow() public {
        _commitTicket(WINNER, WIN_SALT, OUTCOME_HASH, STAKE);

        vm.warp(revealDeadline + 1);
        uint256 balanceBefore = WINNER.balance;

        vm.prank(WINNER);
        market.refund();

        assertEq(WINNER.balance, balanceBefore + STAKE);
        assertEq(market.totalPool(), 0);
        assertEq(address(market).balance, 0);
        assertEq(market.remainingPayoutPool(), 0);
    }

    function testNativeCommitMismatchedValueReverts() public {
        vm.deal(WINNER, STAKE);
        bytes32 ticketHash = keccak256(abi.encodePacked(WINNER, OUTCOME_HASH, WIN_SALT));
        vm.prank(WINNER);
        vm.expectRevert(RevealMarket.InvalidPayment.selector);
        market.commit{value: STAKE}(ticketHash, STAKE / 2);
    }

    function testNativePayoutPreviewBeforeSettlement() public {
        _commitTicket(WINNER, WIN_SALT, OUTCOME_HASH, STAKE);
        (uint256 amount, bool claimable) = market.payoutPreview(WINNER, 0, OUTCOME, WIN_SALT);
        assertEq(amount, 0);
        assertTrue(!claimable);
    }

    function testNativeCommitZeroAmountReverts() public {
        bytes32 ticketHash = keccak256(abi.encodePacked(WINNER, OUTCOME_HASH, WIN_SALT));
        vm.expectRevert(RevealMarket.InvalidAmount.selector);
        market.commit(ticketHash, 0);
    }

    function testNativeCommitPausedBlocksCommits() public {
        market.setCommitPaused(true);
        vm.deal(WINNER, STAKE);
        bytes32 ticketHash = keccak256(abi.encodePacked(WINNER, OUTCOME_HASH, WIN_SALT));
        vm.prank(WINNER);
        vm.expectRevert(RevealMarket.CommitPaused.selector);
        market.commit{value: STAKE}(ticketHash, STAKE);
    }

    function testNativeCommitPauseOnlyController() public {
        vm.expectRevert(RevealMarket.NotAuthorized.selector);
        vm.prank(WINNER);
        market.setCommitPaused(true);

        market.setCommitPaused(true);
        market.setCommitPaused(false);
    }

    function testNativeMetadataUpdate() public {
        string memory newURI = "ipfs://market/native-updated";
        vm.expectEmit(false, false, false, true);
        emit RevealMarket.MetadataUpdated(newURI);
        market.updateMetadataURI(newURI);
        assertEq(market.metadataURI(), newURI);
    }

    function testNativeCancelMarketAllowsRefund() public {
        _commitTicket(WINNER, WIN_SALT, OUTCOME_HASH, STAKE);
        market.cancelMarket("oracle dispute");
        vm.prank(WINNER);
        market.refund();
        assertEq(uint256(market.phase()), uint256(RevealMarket.Phase.Cancelled));
    }

    function testNativeEmergencySettle() public {
        _commitTicket(WINNER, WIN_SALT, OUTCOME_HASH, STAKE);
        _commitTicket(LOSER, LOSE_SALT, keccak256(bytes("TEAM_B")), STAKE);

        vm.warp(commitDeadline + 1);
        market.lock();
        vm.prank(ORACLE);
        market.postResult(OUTCOME_HASH);

        vm.expectEmit(false, false, false, true);
        emit RevealMarket.EmergencySettled(OUTCOME_HASH, STAKE, address(this));
        market.emergencySettle(OUTCOME_HASH, STAKE);

        uint256 winnerBalanceBefore = WINNER.balance;
        vm.prank(WINNER);
        market.claim(0, OUTCOME, WIN_SALT);
        assertGt(WINNER.balance, winnerBalanceBefore);
    }

    function testNativeUpdateOracle() public {
        address newOracle = address(0x4321);
        vm.expectEmit(true, true, false, false);
        emit RevealMarket.OracleUpdated(ORACLE, newOracle);
        market.updateOracle(newOracle);
        assertEq(market.oracle(), newOracle);
    }

    function testNativeClaimPausedBlocksClaims() public {
        _commitTicket(WINNER, WIN_SALT, OUTCOME_HASH, STAKE);
        _commitTicket(LOSER, LOSE_SALT, keccak256(bytes("TEAM_B")), STAKE);

        vm.warp(commitDeadline + 1);
        market.lock();
        vm.prank(ORACLE);
        market.postResult(OUTCOME_HASH);

        uint256[4] memory pubSignals;
        pubSignals[0] = STAKE;
        market.verifyProof(new bytes(0), pubSignals);

        market.setClaimPaused(true);
        vm.prank(WINNER);
        vm.expectRevert(RevealMarket.ClaimPaused.selector);
        market.claim(0, OUTCOME, WIN_SALT);

        market.setClaimPaused(false);
        uint256 winnerBalanceBefore = WINNER.balance;
        vm.prank(WINNER);
        market.claim(0, OUTCOME, WIN_SALT);
        assertGt(WINNER.balance, winnerBalanceBefore);
    }
}
