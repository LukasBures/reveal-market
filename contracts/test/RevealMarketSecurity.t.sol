// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

import {RevealMarket} from "../src/RevealMarket.sol";
import {Verifier} from "../src/Verifier.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {ReentrantRakeManager} from "./mocks/ReentrantRakeManager.sol";

contract RevealMarketSecurityTest is Test {
    RevealMarket private market;
    Verifier private verifier;
    MockERC20 private collateral;
    ReentrantRakeManager private rakeManager;

    address private constant WINNER = address(0x1111);
    address private constant LOSER = address(0x2222);
    bytes32 private constant WIN_OUTCOME_HASH = keccak256(bytes("HOME_WIN"));
    bytes32 private constant LOSE_OUTCOME_HASH = keccak256(bytes("AWAY_WIN"));
    bytes32 private constant ALT_OUTCOME_HASH = keccak256(bytes("TAMPER"));
    bytes32 private constant WIN_SALT = bytes32(uint256(0xA1));
    bytes32 private constant LOSE_SALT = bytes32(uint256(0xB2));
    uint256 private constant STAKE = 100e6;
    address payable private constant TREASURY = payable(address(0xBEEF));
    string private constant EVENT_ID = "SECURITY";

    uint256 private commitDeadline;
    uint256 private revealDeadline;

    function setUp() public {
        market = new RevealMarket();
        verifier = new Verifier();
        collateral = new MockERC20("USD Coin", "USDC", 6);
        rakeManager = new ReentrantRakeManager(market);

        commitDeadline = block.timestamp + 1 days;
        revealDeadline = commitDeadline + 1 days;

        market.initialize(
            EVENT_ID,
            commitDeadline,
            revealDeadline,
            address(this), // oracle placeholder
            address(verifier),
            address(rakeManager),
            TREASURY,
            address(collateral),
            address(rakeManager),
            0
        );

        _commit(WINNER, WIN_SALT, WIN_OUTCOME_HASH, STAKE);
        _commit(LOSER, LOSE_SALT, LOSE_OUTCOME_HASH, STAKE);

        vm.warp(commitDeadline + 1);
        market.lock();
    }

    function testReentrancyDuringEmergencySettlementIsBlocked() public {
        rakeManager.setAttackEmergency(ALT_OUTCOME_HASH, STAKE / 2);

        vm.expectRevert(ReentrancyGuard.ReentrancyGuardReentrantCall.selector);
        rakeManager.triggerSettlement(WIN_OUTCOME_HASH, STAKE);

        assertEq(uint256(market.phase()), uint256(RevealMarket.Phase.Locked));
        assertEq(market.winningOutcomeHash(), bytes32(0));
        assertEq(market.winningPool(), 0);

        rakeManager.clearAttack();
        rakeManager.triggerSettlement(WIN_OUTCOME_HASH, STAKE);

        assertEq(uint256(market.phase()), uint256(RevealMarket.Phase.Settled));
        assertEq(market.winningOutcomeHash(), WIN_OUTCOME_HASH);
        assertEq(market.winningPool(), STAKE);
    }

    function testReentrancyCancellingDuringSettlementIsBlocked() public {
        string memory reason = "malicious cancel";
        rakeManager.setAttackCancel(reason);

        vm.expectRevert(RevealMarket.SettlementInProgress.selector);
        rakeManager.triggerSettlement(WIN_OUTCOME_HASH, STAKE);

        assertEq(uint256(market.phase()), uint256(RevealMarket.Phase.Locked));
        assertTrue(!market.claimsPaused());
        assertTrue(!market.commitsPaused());

        rakeManager.clearAttack();
        rakeManager.triggerSettlement(WIN_OUTCOME_HASH, STAKE);

        assertEq(uint256(market.phase()), uint256(RevealMarket.Phase.Settled));
        assertEq(market.winningOutcomeHash(), WIN_OUTCOME_HASH);
    }

    function _commit(address user, bytes32 salt, bytes32 outcomeHash, uint256 stake) private {
        collateral.mint(user, stake);
        vm.prank(user);
        collateral.approve(address(market), stake);
        bytes32 ticketHash = keccak256(abi.encodePacked(user, outcomeHash, salt));
        vm.prank(user);
        market.commit(ticketHash, stake);
    }
}
