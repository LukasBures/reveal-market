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
    bytes32 private constant OUTCOME_HASH = keccak256("HOME");
    bytes32 private constant WIN_SALT = bytes32(uint256(555));
    bytes32 private constant LOSE_SALT = bytes32(uint256(777));
    uint256 private proofNonce;

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
        bytes32 winHash = keccak256(abi.encodePacked(WINNER, OUTCOME_HASH, WIN_SALT));
        vm.prank(WINNER);
        market.commit{value: 1 ether}(winHash, 1 ether);

        // pause commits globally
        factory.setGlobalCommitPaused(true);
        vm.deal(LOSER, 1 ether);
        bytes32 loseHash = keccak256(abi.encodePacked(LOSER, keccak256("AWAY"), LOSE_SALT));
        vm.prank(LOSER);
        vm.expectRevert(RevealMarket.CommitPaused.selector);
        market.commit{value: 1 ether}(loseHash, 1 ether);
        factory.setGlobalCommitPaused(false);

        // guardian pause claims
        factory.setMarketPauses(marketAddr, false, true);
        assertTrue(market.claimsPaused());

        vm.warp(params.commitDeadline + 1);
        market.lock();
        vm.prank(ORACLE);
        market.postResult(OUTCOME_HASH);

        uint256[12] memory signals = _buildSignals(market, 1 ether);
        market.verifyAndSettle("", signals);

        // unblock claims
        factory.setMarketPauses(marketAddr, false, false);
        uint256 winnerBalanceBefore = WINNER.balance;
        vm.prank(WINNER);
        bytes32[] memory proof = new bytes32[](0);
        market.claim(0, "HOME", WIN_SALT, proof);
        assertGt(WINNER.balance, winnerBalanceBefore);

        // guardian rotation
        factory.setMarketGuardian(marketAddr, address(0xBEEF));
        vm.prank(address(0xBEEF));
        market.setClaimPaused(true);
        assertTrue(market.claimsPaused());
    }

    function _buildSignals(RevealMarket market, uint256 winningStake)
        internal
        returns (uint256[12] memory signals)
    {
        uint256 grossPool = market.userEscrow() + market.houseFloat();
        uint256 rakeAmount = (market.userEscrow() * rakeManager.rakeBps()) / 10_000;
        uint256 netEscrow = market.userEscrow() - rakeAmount;
        uint256 grossPayout = (winningStake * market.payoutMultiplier()) / market.WAD();
        uint256 liability = grossPayout;

        signals[0] = winningStake;
        signals[1] = liability;
        signals[2] = grossPool;
        signals[3] = rakeAmount;
        signals[4] = market.payoutMultiplier();
        signals[5] = uint256(OUTCOME_HASH);
        signals[6] = market.CIRCUIT_VERSION();
        signals[7] = ++proofNonce;
        signals[8] = uint256(uint160(address(market)));
        signals[9] = liability > netEscrow ? liability - netEscrow : 0;
        signals[10] = uint256(market.commitmentsRoot());
        signals[11] = uint256(keccak256(abi.encodePacked(WINNER, OUTCOME_HASH, WIN_SALT)));
    }
}
