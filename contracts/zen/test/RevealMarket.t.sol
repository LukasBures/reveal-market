// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {MarketFactory} from "../src/MarketFactory.sol";
import {RevealMarket} from "../src/RevealMarket.sol";
import {RakeManager} from "../src/RakeManager.sol";
import {MockVerifier} from "./mocks/MockVerifier.sol";

contract RevealMarketHarness is RevealMarket {
    function exposedEstimate(uint256 amount) external view returns (uint256) {
        return previewMaxLiability(amount);
    }
}

contract RevealMarketTest is Test {
    RevealMarketHarness private market;
    MarketFactory private factory;
    RakeManager private rakeManager;
    MockVerifier private verifier;

    address payable private constant TREASURY = payable(address(0xB0B));
    address private constant ORACLE = address(0xA11CE);
    address private constant USER = address(0xCAFE);
    address private constant LOSER = address(0xD00D);

    bytes32 private constant OUTCOME_HASH = keccak256("TEAM_A");
    bytes32 private constant WIN_SALT = bytes32(uint256(1));
    bytes32 private constant LOSE_SALT = bytes32(uint256(2));

    uint256 private commitDeadline;
    uint256 private revealDeadline;
    uint256 private proofNonce;

    function setUp() public {
        market = new RevealMarketHarness();
        rakeManager = new RakeManager(address(this), TREASURY, 100); // 1% rake
        verifier = new MockVerifier();

        commitDeadline = block.timestamp + 1 days;
        revealDeadline = commitDeadline + 1 days;

        factory = new MarketFactory(address(market), address(rakeManager), TREASURY, address(verifier));

        MarketFactory.CreateMarketParams memory params;
        params.eventId = "EVT-1";
        params.commitDeadline = commitDeadline;
        params.revealDeadline = revealDeadline;
        params.oracle = ORACLE;
        params.payoutMultiplier = 2e18;
        params.payoutCurve = RevealMarket.PayoutCurve.FixedOdds;
        params.maxMarketSize = 5 ether;

        address deployed = factory.createMarket(params);
        market = RevealMarketHarness(payable(deployed));
    }

    function testCommitRevertsWhenCoverageInsufficient() public {
        vm.deal(USER, 1 ether);
        bytes32 ticketHash = keccak256(abi.encodePacked(USER, OUTCOME_HASH, WIN_SALT));
        vm.prank(USER);
        vm.expectRevert();
        market.commit{value: 1 ether}(ticketHash, 1 ether);
    }

    function testCommitSucceedsWithFloat() public {
        vm.deal(address(this), 2 ether);
        market.fundMarket{value: 2 ether}(2 ether);
        assertEq(market.houseFloat(), 2 ether);

        vm.deal(USER, 1 ether);
        bytes32 ticketHash = keccak256(abi.encodePacked(USER, OUTCOME_HASH, WIN_SALT));
        vm.prank(USER);
        market.commit{value: 1 ether}(ticketHash, 1 ether);
        assertEq(market.userEscrow(), 1 ether);
        assertGt(market.maxLiability(), 0);
    }

    function testFundMarketRequiresTreasuryOrFactory() public {
        vm.deal(LOSER, 1 ether);
        vm.prank(LOSER);
        vm.expectRevert(RevealMarket.NotAuthorized.selector);
        market.fundMarket{value: 1 ether}(1 ether);

        vm.deal(address(this), 1 ether);
        market.fundMarket{value: 1 ether}(1 ether);
        assertEq(market.houseFloat(), 1 ether);
    }

    function testSettlementUsesMultiplierAndTracksFloat() public {
        _prepareMarketWithFloat();

        vm.warp(commitDeadline + 1);
        market.lock();
        vm.prank(ORACLE);
        market.postResult(OUTCOME_HASH);

        uint256[12] memory signals = _buildSignals(1 ether);
        uint256 treasuryBefore = TREASURY.balance;
        uint256 beforeFloat = market.houseFloat();
        uint256 beforeEscrow = market.userEscrow();
        market.verifyAndSettle("", signals);

        assertEq(uint256(market.phase()), uint256(RevealMarket.Phase.Settled));
        uint256 expectedLiability = 2 ether;
        assertEq(market.totalLiability(), expectedLiability);
        assertEq(market.rakePaid(), (beforeEscrow * rakeManager.rakeBps()) / 10_000);
        assertEq(TREASURY.balance, treasuryBefore + market.rakePaid());

        uint256 winnerBalanceBefore = USER.balance;
        vm.prank(USER);
        bytes32[] memory proof = new bytes32[](0);
        market.claim(0, "TEAM_A", WIN_SALT, proof);
        assertEq(USER.balance, winnerBalanceBefore + expectedLiability);
        assertLt(market.houseFloat(), beforeFloat);
    }

    function testVerifyAndSettleRevertsWhenFloatUsedExceedsBalance() public {
        _prepareMarketWithFloat();
        vm.warp(commitDeadline + 1);
        market.lock();
        vm.prank(ORACLE);
        market.postResult(OUTCOME_HASH);

        uint256[12] memory signals = _buildSignals(1 ether);
        signals[9] = market.houseFloat() + 1;
        vm.expectRevert();
        market.verifyAndSettle("", signals);
    }

    function testVerifyAndSettleRevertsOnRakeMismatch() public {
        _prepareMarketWithFloat();
        vm.warp(commitDeadline + 1);
        market.lock();
        vm.prank(ORACLE);
        market.postResult(OUTCOME_HASH);

        uint256[12] memory signals = _buildSignals(1 ether);
        signals[3] = 0;
        vm.expectRevert(RevealMarket.ProofTotalsMismatch.selector);
        market.verifyAndSettle("", signals);
    }

    function testWithdrawFloatBeforeSettlementReverts() public {
        vm.expectRevert(abi.encodeWithSelector(RevealMarket.InvalidPhase.selector, RevealMarket.Phase.Settled, 0));
        market.withdrawFloat(TREASURY, 1);
    }

    function testWithdrawFloatAfterClaims() public {
        _prepareMarketWithFloat();

        vm.warp(commitDeadline + 1);
        market.lock();
        vm.prank(ORACLE);
        market.postResult(OUTCOME_HASH);

        uint256[12] memory signals = _buildSignals(1 ether);
        market.verifyAndSettle("", signals);

        vm.prank(USER);
        bytes32[] memory proof = new bytes32[](0);
        market.claim(0, "TEAM_A", WIN_SALT, proof);
        assertEq(market.paidOut(), market.totalLiability());

        uint256 treasuryBefore = TREASURY.balance;
        vm.prank(address(this));
        market.withdrawFloat(TREASURY, market.houseFloat());
        assertGt(TREASURY.balance, treasuryBefore);
        assertEq(market.houseFloat(), 0);
    }

    function testMarketSizeLimitBlocksOversizedFunding() public {
        vm.deal(address(this), 4 ether);
        market.fundMarket{value: 4 ether}(4 ether);
        vm.deal(USER, 2 ether);
        bytes32 ticketHash = keccak256(abi.encodePacked(USER, OUTCOME_HASH, WIN_SALT));
        vm.prank(USER);
        vm.expectRevert(RevealMarket.ExceedsMarketSize.selector);
        market.commit{value: 2 ether}(ticketHash, 2 ether);
    }

    function testCommitmentRootMustMatchProof() public {
        _prepareMarketWithFloat();

        vm.warp(commitDeadline + 1);
        market.lock();
        vm.prank(ORACLE);
        market.postResult(OUTCOME_HASH);

        uint256[12] memory signals = _buildSignals(1 ether);
        signals[10] = uint256(keccak256("bad-root"));
        vm.expectRevert(RevealMarket.InvalidProofLayout.selector);
        market.verifyAndSettle("", signals);
    }

    function testInitializeRejectsExcessivePayoutMultiplier() public {
        RevealMarketHarness bad = new RevealMarketHarness();
        vm.expectRevert(RevealMarket.InvalidPayoutMultiplier.selector);
        bad.initialize(
            "EVT-BAD",
            block.timestamp + 1 days,
            block.timestamp + 2 days,
            ORACLE,
            address(verifier),
            address(rakeManager),
            address(TREASURY),
            address(this),
            0,
            6e18,
            RevealMarket.PayoutCurve.FixedOdds,
            5 ether
        );
    }

    function testVerifyAndSettleRejectsMultiplierMismatch() public {
        _prepareMarketWithFloat();
        vm.warp(commitDeadline + 1);
        market.lock();
        vm.prank(ORACLE);
        market.postResult(OUTCOME_HASH);

        uint256[12] memory signals = _buildSignals(1 ether);
        signals[4] = market.payoutMultiplier() + 1;
        vm.expectRevert(RevealMarket.InvalidPayoutMultiplier.selector);
        market.verifyAndSettle("", signals);
    }

    function testPreviewMaxLiabilityExposesEstimate() public {
        vm.deal(address(this), 2 ether);
        market.fundMarket{value: 2 ether}(2 ether);
        uint256 liability = market.exposedEstimate(1 ether);
        assertGt(liability, 0);
    }

    function _prepareMarketWithFloat() private {
        vm.deal(address(this), 3 ether);
        market.fundMarket{value: 2 ether}(2 ether);
        vm.deal(USER, 1 ether);
        bytes32 ticketHash = keccak256(abi.encodePacked(USER, OUTCOME_HASH, WIN_SALT));
        vm.prank(USER);
        market.commit{value: 1 ether}(ticketHash, 1 ether);
    }

    function _buildSignals(uint256 winningStake) private returns (uint256[12] memory signals) {
        uint256 grossPool = market.userEscrow() + market.houseFloat();
        uint256 rakeAmount = (market.userEscrow() * rakeManager.rakeBps()) / 10_000;
        uint256 grossPayout = (winningStake * market.payoutMultiplier()) / market.WAD();
        uint256 liability = grossPayout;
        uint256 netEscrow = market.userEscrow() - rakeAmount;
        uint256 floatUsed = liability > netEscrow ? liability - netEscrow : 0;

        signals[0] = winningStake;
        signals[1] = liability;
        signals[2] = grossPool;
        signals[3] = rakeAmount;
        signals[4] = market.payoutMultiplier();
        signals[5] = uint256(OUTCOME_HASH);
        signals[6] = market.CIRCUIT_VERSION();
        signals[7] = ++proofNonce;
        signals[8] = uint256(uint160(address(market)));
        signals[9] = floatUsed;
        signals[10] = uint256(market.commitmentsRoot());
        signals[11] = uint256(_winningCommitHash());
    }

    function _winningCommitHash() private pure returns (bytes32) {
        return keccak256(abi.encodePacked(USER, OUTCOME_HASH, WIN_SALT));
    }
}
