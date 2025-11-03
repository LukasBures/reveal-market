// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

import {MarketFactory} from "../src/MarketFactory.sol";
import {RevealMarket} from "../src/RevealMarket.sol";
import {RakeManager} from "../src/RakeManager.sol";
import {Verifier} from "../src/Verifier.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

contract FactoryLifecycleTest is Test {
    MarketFactory private factory;
    RevealMarket private implementation;
    RakeManager private rakeManager;
    Verifier private verifier;
    MockERC20 private collateralToken;

    address private constant ORACLE = address(0xABCD);
    address payable private constant TREASURY = payable(address(0xAAAA));
    address private constant USER = address(0x1111);
    address private constant OTHER = address(0x2222);

    string private constant EVENT_ID = "INTEGRATION";
    string private constant OUTCOME = "HOME";
    bytes32 private constant OUTCOME_HASH = keccak256(bytes(OUTCOME));
    bytes32 private constant WIN_SALT = bytes32(uint256(555));
    bytes32 private constant LOSE_SALT = bytes32(uint256(777));

    function setUp() public {
        implementation = new RevealMarket();
        rakeManager = new RakeManager(address(this), TREASURY, 100);
        verifier = new Verifier();
        collateralToken = new MockERC20("USD Coin", "USDC", 6);
        factory = new MarketFactory(
            address(implementation),
            address(rakeManager),
            TREASURY,
            address(verifier),
            address(collateralToken)
        );
    }

    function testFullLifecycleWithGuardianPauses() public {
        uint256 commitDeadline = block.timestamp + 1 days;
        uint256 revealDeadline = commitDeadline + 1 days;

        // Deploy new market via factory (no metadata arg anymore)
        address marketAddr = factory.createMarket(
            EVENT_ID,
            commitDeadline,
            revealDeadline,
            ORACLE,
            address(collateralToken),
            0
        );

        RevealMarket market = RevealMarket(payable(marketAddr));
        assertEq(market.appliedRakeBps(), rakeManager.rakeBps());

        // User commits
        _mintAndApprove(market, USER, 100e6);
        bytes32 userHash = keccak256(abi.encodePacked(USER, OUTCOME_HASH, WIN_SALT));
        vm.prank(USER);
        market.commit(userHash, 100e6);

        // Global commit pause
        factory.setGlobalCommitPaused(true);
        _mintAndApprove(market, OTHER, 100e6);
        bytes32 otherHash = keccak256(abi.encodePacked(OTHER, keccak256(bytes("AWAY")), LOSE_SALT));
        vm.prank(OTHER);
        vm.expectRevert(RevealMarket.CommitPaused.selector);
        market.commit(otherHash, 100e6);
        factory.setGlobalCommitPaused(false);

        // Allow commit again
        vm.prank(OTHER);
        market.commit(otherHash, 100e6);

        // Lock market
        vm.warp(commitDeadline + 1);
        market.lock();

        // Guardian control — pause/unpause claims
        factory.setMarketPauses(marketAddr, false, true);
        assertTrue(market.claimsPaused());

        // Post result & verify proof
        vm.prank(ORACLE);
        market.postResult(OUTCOME_HASH);
        uint256[4] memory pubSignals;
        pubSignals[0] = 100e6;
        market.verifyProof(new bytes(0), pubSignals);

        // Global claim pause
        factory.setGlobalClaimPaused(true);
        vm.prank(USER);
        vm.expectRevert(RevealMarket.ClaimPaused.selector);
        market.claim(0, OUTCOME, WIN_SALT);

        // Unpause and finalize claim
        factory.setGlobalClaimPaused(false);
        factory.setMarketPauses(marketAddr, false, false);

        uint256 winnerBalanceBefore = collateralToken.balanceOf(USER);
        vm.prank(USER);
        market.claim(0, OUTCOME, WIN_SALT);
        assertGt(collateralToken.balanceOf(USER), winnerBalanceBefore);

        // Update guardian and verify control
        factory.setMarketGuardian(marketAddr, address(0xBEEF));
        vm.prank(address(0xBEEF));
        market.setClaimPaused(true);
        assertTrue(market.claimsPaused());
    }

    function _mintAndApprove(RevealMarket market, address user, uint256 amount) internal {
        collateralToken.mint(user, amount);
        vm.prank(user);
        collateralToken.approve(address(market), amount);
    }
}
