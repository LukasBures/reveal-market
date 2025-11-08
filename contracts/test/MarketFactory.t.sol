// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {Vm} from "forge-std/Vm.sol";

import {MarketFactory} from "../src/MarketFactory.sol";
import {RevealMarket} from "../src/RevealMarket.sol";
import {RakeManager} from "../src/RakeManager.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {MockVerifier} from "./mocks/MockVerifier.sol";

contract MarketFactoryTest is Test {
    MarketFactory private factory;
    RevealMarket private implementation;
    RakeManager private rakeManager;
    MockVerifier private verifier;
    MockERC20 private collateralToken;

    string private constant OUTCOME = "TEAM_A";
    bytes32 private constant OUTCOME_HASH = keccak256(bytes(OUTCOME));
    bytes32 private constant WIN_SALT = bytes32(uint256(111));
    bytes32 private constant LOSE_SALT = bytes32(uint256(222));
    address private constant USER = address(0xFEED);
    address private constant OTHER = address(0xDADA);

    address private constant ORACLE = address(0x1234);
    address payable private constant TREASURY = payable(address(0x5678));

    function setUp() public {
        implementation = new RevealMarket();
        rakeManager = new RakeManager(address(this), TREASURY, 100);
        verifier = new MockVerifier();
        collateralToken = new MockERC20("USD Coin", "USDC", 6);
        factory = new MarketFactory(
            address(implementation), address(rakeManager), TREASURY, address(verifier), address(collateralToken)
        );
        assertEq(factory.defaultCollateral(), address(collateralToken));
        assertTrue(factory.isCollateralAllowed(address(collateralToken)));
        assertTrue(factory.isCollateralAllowed(address(0)));
    }

    // -----------------------------------------------------------------------
    // CREATE MARKET
    // -----------------------------------------------------------------------
    function testCreateMarketDeploysClone() public {
        uint256 commitDeadline = block.timestamp + 1 days;
        uint256 revealDeadline = commitDeadline + 1 days;

        // Record emitted events during execution
        vm.recordLogs();

        address market =
            factory.createMarket("E-1", commitDeadline, revealDeadline, ORACLE, address(collateralToken), 0);

        // Fetch logs and check the MarketCreated event manually
        Vm.Log[] memory entries = vm.getRecordedLogs();
        bool found = false;
        for (uint256 i = 0; i < entries.length; i++) {
            if (entries[i].topics[0] == keccak256("MarketCreated(address,string,uint256,uint256,address,uint256)")) {
                found = true;
                // Decode the indexed market address
                address emittedMarket = address(uint160(uint256(entries[i].topics[1])));
                assertEq(emittedMarket, market, "MarketCreated event has wrong market param");
                (uint256 emittedCommit, uint256 emittedReveal, address emittedCollateral, uint256 emittedRake) =
                    abi.decode(entries[i].data, (uint256, uint256, address, uint256));
                assertEq(emittedCommit, commitDeadline);
                assertEq(emittedReveal, revealDeadline);
                assertEq(emittedCollateral, address(collateralToken));
                assertEq(emittedRake, 0);
                break;
            }
        }
        assertTrue(found, "MarketCreated event not emitted");

        // Validate that factory registered the market
        assertTrue(factory.isMarket(market));
        assertEq(factory.getMarkets().length, 1);

        // Validate deployed clone
        RevealMarket clone = RevealMarket(payable(market));
        assertEq(clone.oracle(), ORACLE);
        assertEq(uint256(clone.phase()), uint256(RevealMarket.Phase.Commit));
        assertEq(clone.rakeManager(), address(rakeManager));
        assertEq(clone.treasury(), TREASURY);
        assertEq(clone.collateral(), address(collateralToken));
        assertEq(clone.guardian(), factory.guardian());
        assertEq(clone.appliedRakeBps(), rakeManager.rakeBps());
    }

    function testCreateMarketWithCustomRakeOverride() public {
        uint256 commitDeadline = block.timestamp + 2 days;
        uint256 revealDeadline = commitDeadline + 1 days;

        uint256 customRake = 150;
        address market = factory.createMarket(
            "E-CUSTOM", commitDeadline, revealDeadline, ORACLE, address(collateralToken), customRake
        );

        RevealMarket clone = RevealMarket(payable(market));
        assertEq(clone.appliedRakeBps(), customRake);
    }

    function testCreateMarketRevertsWhenRakeAboveMax() public {
        uint256 commitDeadline = block.timestamp + 1 days;
        uint256 revealDeadline = commitDeadline + 1 days;
        vm.expectRevert(MarketFactory.InvalidRakeBps.selector);
        factory.createMarket("E-BAD-RAKE", commitDeadline, revealDeadline, ORACLE, address(collateralToken), 500);
    }

    function testCreateMarketRevertsOnInvalidDeadlines() public {
        vm.expectRevert(MarketFactory.InvalidDeadlines.selector);
        factory.createMarket("E-2", block.timestamp, block.timestamp + 1 days, ORACLE, address(collateralToken), 0);

        uint256 commitDeadline = block.timestamp + 1 days;
        vm.expectRevert(MarketFactory.InvalidDeadlines.selector);
        factory.createMarket("E-3", commitDeadline, commitDeadline, ORACLE, address(collateralToken), 0);
    }

    function testCreateMarketFallsBackToDefaultCollateral() public {
        uint256 commitDeadline = block.timestamp + 2 days;
        uint256 revealDeadline = commitDeadline + 1 days;

        address market = factory.createMarket("E-DEFAULT", commitDeadline, revealDeadline, ORACLE, address(0), 0);

        RevealMarket clone = RevealMarket(payable(market));
        assertEq(clone.collateral(), address(collateralToken));
    }

    function testCreateMarketRevertsOnZeroOracle() public {
        uint256 commitDeadline = block.timestamp + 1 days;
        uint256 revealDeadline = commitDeadline + 1 days;
        vm.expectRevert(MarketFactory.ZeroAddress.selector);
        factory.createMarket("E-4", commitDeadline, revealDeadline, address(0), address(collateralToken), 0);
    }

    // -----------------------------------------------------------------------
    // ADMIN SETTERS
    // -----------------------------------------------------------------------
    function testAdminSetters() public {
        address newImplementation = address(new RevealMarket());
        factory.setImplementation(newImplementation);
        assertEq(factory.implementation(), newImplementation);

        address newRakeManager = address(new RakeManager(address(this), TREASURY, 50));
        factory.setRakeManager(newRakeManager);
        assertEq(factory.rakeManager(), newRakeManager);

        address newVerifier = address(new MockVerifier());
        factory.setVerifier(newVerifier);
        assertEq(factory.verifier(), newVerifier);

        address newTreasury = address(0x9012);
        factory.setTreasury(newTreasury);
        assertEq(factory.treasury(), newTreasury);

        MockERC20 altCollateral = new MockERC20("AltUSD", "ALT", 6);
        factory.setCollateralStatus(address(altCollateral), true);
        factory.setDefaultCollateral(address(altCollateral));
        assertEq(factory.defaultCollateral(), address(altCollateral));
    }

    function testSettersRevertOnZero() public {
        vm.expectRevert(MarketFactory.ZeroAddress.selector);
        factory.setImplementation(address(0));

        vm.expectRevert(MarketFactory.ZeroAddress.selector);
        factory.setRakeManager(address(0));

        vm.expectRevert(MarketFactory.ZeroAddress.selector);
        factory.setVerifier(address(0));

        vm.expectRevert(MarketFactory.ZeroAddress.selector);
        factory.setTreasury(address(0));
    }

    // -----------------------------------------------------------------------
    // COLLATERAL / ALLOWLIST
    // -----------------------------------------------------------------------
    function testCreateMarketWithNativeCollateral() public {
        factory.setDefaultCollateral(address(0));
        uint256 commitDeadline = block.timestamp + 2 days;
        uint256 revealDeadline = commitDeadline + 1 days;

        address market = factory.createMarket("E-NATIVE", commitDeadline, revealDeadline, ORACLE, address(0), 0);
        RevealMarket clone = RevealMarket(payable(market));
        assertEq(clone.collateral(), address(0));
    }

    function testSetDefaultCollateralRequiresWhitelist() public {
        MockERC20 alt = new MockERC20("Alt", "ALT", 6);
        vm.expectRevert(abi.encodeWithSelector(MarketFactory.CollateralNotAllowed.selector, address(alt)));
        factory.setDefaultCollateral(address(alt));

        vm.expectEmit(true, false, false, true);
        emit MarketFactory.CollateralStatusUpdated(address(alt), true);
        factory.setCollateralStatus(address(alt), true);
        assertTrue(factory.isCollateralAllowed(address(alt)));

        vm.expectEmit(true, false, false, false);
        emit MarketFactory.DefaultCollateralUpdated(address(alt));
        factory.setDefaultCollateral(address(alt));
        assertEq(factory.defaultCollateral(), address(alt));
    }

    function testCannotDisableDefaultCollateral() public {
        vm.expectRevert(MarketFactory.CannotDisableDefaultCollateral.selector);
        factory.setCollateralStatus(address(collateralToken), false);
        assertTrue(factory.isCollateralAllowed(address(collateralToken)));
    }

    function testAllowlistPauseBlocksChanges() public {
        vm.expectEmit(true, false, false, true);
        emit MarketFactory.AllowlistPauseSet(true, address(this));
        factory.setAllowlistPaused(true);

        vm.expectRevert(MarketFactory.AllowlistPaused.selector);
        factory.setCollateralStatus(address(collateralToken), true);

        vm.expectRevert(MarketFactory.AllowlistPaused.selector);
        factory.setDefaultCollateral(address(collateralToken));

        factory.setAllowlistPaused(false);
        factory.setCollateralStatus(address(0x1234), true);
    }

    function testGuardianCanPauseAllowlist() public {
        address newGuardian = address(0xBEEF);
        factory.setGuardian(newGuardian);
        vm.prank(newGuardian);
        vm.expectEmit(true, false, false, true);
        emit MarketFactory.AllowlistPauseSet(true, newGuardian);
        factory.setAllowlistPaused(true);
        vm.prank(newGuardian);
        factory.setAllowlistPaused(false);
    }

    function testNonGuardianCannotPauseAllowlist() public {
        vm.expectRevert(MarketFactory.NotGuardianOrOwner.selector);
        vm.prank(address(0xCAFE));
        factory.setAllowlistPaused(true);
    }

    function testSetGuardianRequiresNonZero() public {
        vm.expectRevert(MarketFactory.ZeroAddress.selector);
        factory.setGuardian(address(0));
    }

    function testCreateMarketRevertsForBlockedCollateral() public {
        MockERC20 alt = new MockERC20("Alt", "ALT", 6);
        factory.setCollateralStatus(address(alt), true);
        factory.setDefaultCollateral(address(alt));
        factory.setCollateralStatus(address(collateralToken), false);

        uint256 commitDeadline = block.timestamp + 1 days;
        uint256 revealDeadline = commitDeadline + 1 days;

        vm.expectRevert(abi.encodeWithSelector(MarketFactory.CollateralNotAllowed.selector, address(collateralToken)));
        factory.createMarket("E-BLOCK", commitDeadline, revealDeadline, ORACLE, address(collateralToken), 0);
    }

    // -----------------------------------------------------------------------
    // MARKET-SPECIFIC CONTROLS
    // -----------------------------------------------------------------------
    function testSetMarketGuardian() public {
        RevealMarket market = _deployDefaultMarket("E-GUARD");
        address newGuardian = address(0x9090);
        vm.expectEmit(true, true, false, false);
        emit MarketFactory.MarketGuardianUpdated(address(market), newGuardian);
        factory.setMarketGuardian(address(market), newGuardian);
        assertEq(market.guardian(), newGuardian);
    }

    function testSetMarketPauses() public {
        RevealMarket market = _deployDefaultMarket("E-PAUSE");
        vm.expectEmit(true, false, false, true);
        emit MarketFactory.MarketPaused(address(market), true, true, address(this));
        factory.setMarketPauses(address(market), true, true);
        assertTrue(market.commitsPaused());
        assertTrue(market.claimsPaused());
    }

    // -----------------------------------------------------------------------
    // GLOBAL PAUSES
    // -----------------------------------------------------------------------
    function testGlobalCommitPauseBlocksCommit() public {
        RevealMarket market = _deployDefaultMarket("E-GLOBAL-COMMIT");
        factory.setGlobalCommitPaused(true);
        assertTrue(factory.globalCommitPaused());
        _mintAndApprove(market, USER, 100e6);
        bytes32 ticketHash = keccak256(abi.encodePacked(USER, OUTCOME_HASH, WIN_SALT));
        vm.prank(USER);
        vm.expectRevert(RevealMarket.CommitPaused.selector);
        market.commit(ticketHash, 100e6);
        factory.setGlobalCommitPaused(false);
        assertTrue(!factory.globalCommitPaused());
        vm.prank(USER);
        market.commit(ticketHash, 100e6);
    }

    function testGlobalClaimPauseBlocksClaim() public {
        RevealMarket market = _deployDefaultMarket("E-GLOBAL-CLAIM");
        _commitPair(market, USER, OTHER, 100e6);

        vm.warp(market.commitDeadline() + 1);
        market.lock();
        vm.prank(ORACLE);
        market.postResult(OUTCOME_HASH);
        uint256[4] memory pubSignals = _buildSignals(market, 100e6, OUTCOME_HASH);
        market.verifyProof(new bytes(0), pubSignals);

        factory.setGlobalClaimPaused(true);
        assertTrue(factory.globalClaimPaused());
        vm.prank(USER);
        vm.expectRevert(RevealMarket.ClaimPaused.selector);
        market.claim(0, OUTCOME, WIN_SALT);
        factory.setGlobalClaimPaused(false);
        assertTrue(!factory.globalClaimPaused());
        uint256 before = collateralToken.balanceOf(USER);
        vm.prank(USER);
        market.claim(0, OUTCOME, WIN_SALT);
        assertGt(collateralToken.balanceOf(USER), before);
    }

    // -----------------------------------------------------------------------
    // HELPERS
    // -----------------------------------------------------------------------
    function _deployDefaultMarket(string memory eventId) private returns (RevealMarket) {
        uint256 commitDeadline = block.timestamp + 3 days;
        uint256 revealDeadline = commitDeadline + 1 days;
        address marketAddr =
            factory.createMarket(eventId, commitDeadline, revealDeadline, ORACLE, address(collateralToken), 0);
        return RevealMarket(payable(marketAddr));
    }

    function _mintAndApprove(RevealMarket market, address user, uint256 amount) private {
        collateralToken.mint(user, amount);
        vm.prank(user);
        collateralToken.approve(address(market), amount);
    }

    function _commitPair(RevealMarket market, address winner, address loser, uint256 amount) private {
        _mintAndApprove(market, winner, amount);
        bytes32 winHash = keccak256(abi.encodePacked(winner, OUTCOME_HASH, WIN_SALT));
        vm.prank(winner);
        market.commit(winHash, amount);

        _mintAndApprove(market, loser, amount);
        bytes32 loseHash = keccak256(abi.encodePacked(loser, keccak256(bytes("TEAM_B")), LOSE_SALT));
        vm.prank(loser);
        market.commit(loseHash, amount);
    }

    function _buildSignals(RevealMarket market, uint256 winningPool, bytes32 outcomeHash)
        private
        view
        returns (uint256[4] memory signals)
    {
        signals[0] = winningPool;
        signals[1] = market.totalPool();
        signals[2] = uint256(outcomeHash);
        signals[3] = market.CIRCUIT_VERSION();
    }
}
