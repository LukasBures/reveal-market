// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {MarketFactory} from "../src/MarketFactory.sol";
import {RevealMarket} from "../src/RevealMarket.sol";
import {RakeManager} from "../src/RakeManager.sol";
import {MockVerifier} from "./mocks/MockVerifier.sol";

contract FactoryLifecycleTest is Test {
    MarketFactory private factory;
    RevealMarket private implementation;
    RakeManager private rakeManager;
    MockVerifier private verifier;

    address payable private constant TREASURY = payable(address(0xAAAA));
    address private constant ORACLE = address(0xABCD);
    address private constant WINNER = address(0x1111);
    address private constant LOSER = address(0x2222);
    uint256 private constant OUTCOME_ID = 0;
    bytes32 private constant WIN_SALT = bytes32(uint256(555));
    bytes32 private constant LOSE_SALT = bytes32(uint256(777));

    function setUp() public {
        implementation = new RevealMarket();
        rakeManager = new RakeManager(address(this), TREASURY, 100);
        verifier = new MockVerifier();
        factory = new MarketFactory(address(implementation), address(rakeManager), TREASURY, address(verifier));
    }

    function testLifecycleWithPausesAndGuardian() public {
        MarketFactory.CreateMarketParams memory params;
        params.eventId = "INTEGRATION";
        params.commitDeadline = block.timestamp + 1 days;
        params.revealDeadline = params.commitDeadline + 1 days;
        params.oracle = ORACLE;
        params.payoutMultiplier = 15e17; // 1.5x
        params.payoutCurve = RevealMarket.PayoutCurve.FixedOdds;
        params.floatAmount = 1 ether;

        vm.deal(address(this), params.floatAmount);
        address marketAddr = factory.createMarket{value: params.floatAmount}(params);
        RevealMarket market = RevealMarket(payable(marketAddr));

        // commit winner with coverage provided by float
        vm.deal(WINNER, 1 ether);
        vm.prank(WINNER);
        market.commit{value: 1 ether}(OUTCOME_ID, 1 ether, WIN_SALT);

        // pause commits globally
        factory.setGlobalCommitPaused(true);
        vm.deal(LOSER, 1 ether);
        vm.prank(LOSER);
        vm.expectRevert(RevealMarket.CommitPaused.selector);
        market.commit{value: 1 ether}(OUTCOME_ID, 1 ether, LOSE_SALT);
        factory.setGlobalCommitPaused(false);

        // guardian pause claims
        factory.setMarketPauses(marketAddr, false, true);
        assertTrue(market.claimsPaused());

        vm.warp(params.commitDeadline + 1);
        market.lock();
        vm.prank(ORACLE);
        market.postResult(OUTCOME_ID);

        uint256[10] memory signals = _buildSignals(market);
        market.verifyAndSettle("", signals);

        // unblock claims
        factory.setMarketPauses(marketAddr, false, false);
        uint256 winnerBalanceBefore = WINNER.balance;
        vm.prank(WINNER);
        bytes32[] memory proof = new bytes32[](0);
        market.claim(0, OUTCOME_ID, WIN_SALT, 0, proof);
        assertGt(WINNER.balance, winnerBalanceBefore);

        // guardian rotation
        factory.setMarketGuardian(marketAddr, address(0xBEEF));
        vm.prank(address(0xBEEF));
        market.setClaimPaused(true);
        assertTrue(market.claimsPaused());
    }

    function _buildSignals(RevealMarket market) internal view returns (uint256[10] memory signals) {
        uint256 totalEscrow = market.userEscrow();
        uint256 rakeBps = rakeManager.rakeBps();
        uint256 rakeAmount = (totalEscrow * rakeBps) / 10_000;
        uint256 netEscrow = totalEscrow - rakeAmount;
        uint256 netPool = netEscrow + market.houseFloat();
        uint256 liability = totalEscrow * market.payoutMultiplier() / market.WAD();
        if (liability > netPool) {
            liability = netPool;
        }

        signals[0] = uint256(market.commitmentsRoot());
        signals[1] = market.marketId();
        signals[2] = OUTCOME_ID;
        signals[3] = totalEscrow;
        signals[4] = liability;
        signals[5] = rakeBps;
        signals[6] = totalEscrow;
        signals[7] = 0;
        signals[8] = market.commitmentsCount();
        signals[9] = uint256(market.circuitHash());
    }

}
