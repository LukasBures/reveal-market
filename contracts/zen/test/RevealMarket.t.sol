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

    uint256 private constant OUTCOME_ID = 0;
    bytes32 private constant WIN_SALT = bytes32(uint256(1));
    uint256 private commitDeadline;
    uint256 private revealDeadline;

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
        vm.prank(USER);
        vm.expectRevert();
        market.commit{value: 1 ether}(0, 1 ether, WIN_SALT);
    }

    function testCommitSucceedsWithFloat() public {
        vm.deal(address(this), 2 ether);
        market.fundMarket{value: 2 ether}(2 ether);
        assertEq(market.houseFloat(), 2 ether);

        vm.deal(USER, 1 ether);
        vm.prank(USER);
        market.commit{value: 1 ether}(0, 1 ether, WIN_SALT);
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
        market.postResult(OUTCOME_ID);

        uint256[10] memory signals = _buildSignals();
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
        market.claim(0, 0, WIN_SALT, 0, proof);
        assertEq(USER.balance, winnerBalanceBefore + expectedLiability);
        assertLt(market.houseFloat(), beforeFloat);
    }

    function testVerifyAndSettleRevertsWhenFloatUsedExceedsBalance() public {
        _prepareMarketWithFloat();
        vm.warp(commitDeadline + 1);
        market.lock();
        vm.prank(ORACLE);
        market.postResult(OUTCOME_ID);

        uint256[10] memory signals = _buildSignals();
        signals[4] = market.houseFloat() + market.userEscrow() + 1;
        uint256 netEscrow = market.userEscrow() - (market.userEscrow() * rakeManager.rakeBps()) / 10_000;
        uint256 netPool = netEscrow + market.houseFloat();
        vm.expectRevert(abi.encodeWithSelector(RevealMarket.LiabilityExceedsCoverage.selector, signals[4], netPool));
        market.verifyAndSettle("", signals);
    }

    function testVerifyAndSettleRevertsOnRakeMismatch() public {
        _prepareMarketWithFloat();
        vm.warp(commitDeadline + 1);
        market.lock();
        vm.prank(ORACLE);
        market.postResult(OUTCOME_ID);

        uint256[10] memory signals = _buildSignals();
        signals[5] = rakeManager.rakeBps() + 1;
        vm.expectRevert(RevealMarket.InvalidRakeBps.selector);
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
        market.postResult(OUTCOME_ID);

        uint256[10] memory signals = _buildSignals();
        market.verifyAndSettle("", signals);

        vm.prank(USER);
        bytes32[] memory proof = new bytes32[](0);
        market.claim(0, OUTCOME_ID, WIN_SALT, 0, proof);
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
        vm.prank(USER);
        vm.expectRevert(RevealMarket.ExceedsMarketSize.selector);
        market.commit{value: 2 ether}(OUTCOME_ID, 2 ether, WIN_SALT);
    }

    function testCommitmentRootMustMatchProof() public {
        _prepareMarketWithFloat();

        vm.warp(commitDeadline + 1);
        market.lock();
        vm.prank(ORACLE);
        market.postResult(OUTCOME_ID);

        uint256[10] memory signals = _buildSignals();
        signals[0] = uint256(keccak256("bad-root"));
        vm.expectRevert(RevealMarket.InvalidProofLayout.selector);
        market.verifyAndSettle("", signals);
    }

    function testInitializeRejectsExcessivePayoutMultiplier() public {
        RevealMarketHarness bad = new RevealMarketHarness();
        vm.expectRevert(RevealMarket.InvalidPayoutMultiplier.selector);
        RevealMarket.InitConfig memory cfg = RevealMarket.InitConfig({
            eventId: "EVT-BAD",
            commitDeadline: block.timestamp + 1 days,
            revealDeadline: block.timestamp + 2 days,
            oracle: ORACLE,
            verifier: address(verifier),
            rakeManager: address(rakeManager),
            treasury: address(TREASURY),
            guardian: address(this),
            rakeBpsOverride: 0,
            payoutMultiplier: 6e18,
            payoutCurve: RevealMarket.PayoutCurve.FixedOdds,
            maxMarketSize: 5 ether
        });
        bad.initialize(cfg);
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
        vm.prank(USER);
        market.commit{value: 1 ether}(OUTCOME_ID, 1 ether, WIN_SALT);
    }

    function _buildSignals() private returns (uint256[10] memory signals) {
        uint256 totalEscrow = market.userEscrow();
        uint256 rakeBps = rakeManager.rakeBps();
        uint256 rakeAmount = (totalEscrow * rakeBps) / 10_000;
        uint256 netEscrow = totalEscrow - rakeAmount;
        uint256 netPool = netEscrow + market.houseFloat();
        uint256 liability = (totalEscrow * market.payoutMultiplier()) / market.WAD();
        if (liability > netPool) {
            liability = netPool;
        }

        signals[0] = uint256(market.commitmentsRoot());
        signals[1] = market.marketId();
        signals[2] = OUTCOME_ID;
        signals[3] = totalEscrow;
        signals[4] = liability;
        signals[5] = rakeBps;
        signals[6] = totalEscrow; // assume YES pool for tests
        signals[7] = 0; // NO pool
        signals[8] = market.commitmentsCount();
        signals[9] = uint256(market.circuitHash());
    }

}
