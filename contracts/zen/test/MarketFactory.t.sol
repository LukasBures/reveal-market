// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {MarketFactory} from "../src/MarketFactory.sol";
import {RevealMarket} from "../src/RevealMarket.sol";
import {RakeManager} from "../src/RakeManager.sol";
import {MockVerifier} from "./mocks/MockVerifier.sol";

contract MarketFactoryTest is Test {
    MarketFactory private factory;
    RevealMarket private implementation;
    RakeManager private rakeManager;
    MockVerifier private verifier;

    address payable private constant TREASURY = payable(address(0xBEEF));
    address private constant ORACLE = address(0xA11CE);
    address private constant USER = address(0xCAFE);
    address private constant NEW_OWNER = address(0xB0B);

    uint256 private commitDeadline;
    uint256 private revealDeadline;

    function setUp() public {
        implementation = new RevealMarket();
        rakeManager = new RakeManager(address(this), TREASURY, 100);
        verifier = new MockVerifier();
        factory = new MarketFactory(address(implementation), address(rakeManager), TREASURY, address(verifier));

        commitDeadline = block.timestamp + 1 days;
        revealDeadline = commitDeadline + 1 days;
    }

    function testCreateMarketDeploysCloneWithFloat() public {
        MarketFactory.CreateMarketParams memory params = _defaultParams();
        params.floatAmount = 1 ether;

        address marketAddr;
        vm.deal(address(this), params.floatAmount);
        marketAddr = factory.createMarket{value: params.floatAmount}(params);

        RevealMarket market = RevealMarket(payable(marketAddr));
        assertTrue(factory.isMarket(marketAddr));
        assertEq(market.oracle(), ORACLE);
        assertEq(market.guardian(), factory.guardian());
        assertEq(market.payoutMultiplier(), params.payoutMultiplier);
        assertEq(factory.marketFloatAllocation(marketAddr), params.floatAmount);
        assertEq(market.houseFloat(), params.floatAmount);
    }

    function testSeedMarketFloatRestricted() public {
        address marketAddr = _deploy();
        vm.deal(USER, 1 ether);
        vm.prank(USER);
        vm.expectRevert(MarketFactory.NotTreasuryOrOwner.selector);
        factory.seedMarketFloat{value: 1 ether}(marketAddr, 1 ether);

        vm.deal(address(this), 1 ether);
        factory.seedMarketFloat{value: 1 ether}(marketAddr, 1 ether);
        assertEq(factory.marketFloatAllocation(marketAddr), 1 ether);
    }

    function testRiskLimitsBlockUnsafeLiability() public {
        factory.setRiskLimits(0, 1 ether, 10 ether);
        MarketFactory.CreateMarketParams memory params = _defaultParams();
        params.payoutMultiplier = 2e18;
        params.floatAmount = 2 ether;
        vm.deal(address(this), params.floatAmount);
        address marketAddr = factory.createMarket{value: params.floatAmount}(params);
        RevealMarket market = RevealMarket(payable(marketAddr));

        vm.deal(USER, 1 ether);
        vm.prank(USER);
        vm.expectRevert(MarketFactory.MarketLiabilityExceeded.selector);
        market.commit{value: 1 ether}(0, 1 ether, bytes32(uint256(1)));
    }

    function testPerMarketSizeLimitEnforced() public {
        MarketFactory.CreateMarketParams memory params = _defaultParams();
        params.maxMarketSize = 2 ether;
        params.floatAmount = 1 ether;
        vm.deal(address(this), params.floatAmount);
        address marketAddr = factory.createMarket{value: params.floatAmount}(params);
        RevealMarket market = RevealMarket(payable(marketAddr));
        assertEq(factory.marketSizeLimit(marketAddr), params.maxMarketSize);

        vm.deal(USER, 2 ether);
        vm.prank(USER);
        market.commit{value: 1 ether}(0, 1 ether, bytes32(uint256(5)));

        vm.deal(USER, 1 ether);
        vm.prank(USER);
        vm.expectRevert(RevealMarket.ExceedsMarketSize.selector);
        market.commit{value: 1 ether}(0, 1 ether, bytes32(uint256(6)));
    }

    function testGlobalPausesPropagateToMarkets() public {
        address marketAddr = _deploy();
        RevealMarket market = RevealMarket(payable(marketAddr));

        vm.deal(address(this), 1 ether);
        market.fundMarket{value: 1 ether}(1 ether);

        factory.setGlobalCommitPaused(true);
        vm.deal(USER, 1 ether);
        vm.prank(USER);
        vm.expectRevert(RevealMarket.CommitPaused.selector);
        market.commit{value: 1 ether}(0, 1 ether, bytes32(uint256(2)));

        factory.setGlobalCommitPaused(false);
        vm.prank(USER);
        market.commit{value: 1 ether}(0, 1 ether, bytes32(uint256(2)));
    }

    function testSetRiskLimitsRevertsWhenExistingExposureTooHigh() public {
        MarketFactory.CreateMarketParams memory params = _defaultParams();
        params.payoutMultiplier = 1e18;
        address marketAddr = factory.createMarket(params);
        RevealMarket market = RevealMarket(payable(marketAddr));

        vm.deal(address(this), 1 ether);
        market.fundMarket{value: 1 ether}(1 ether);
        vm.deal(USER, 1 ether);
        vm.prank(USER);
        market.commit{value: 1 ether}(0, 1 ether, bytes32(uint256(3)));

        vm.expectRevert(MarketFactory.GlobalLiabilityExceeded.selector);
        factory.setRiskLimits(0, 0, 0.5 ether);
    }

    function testCreateMarketRejectsZeroOracle() public {
        MarketFactory.CreateMarketParams memory params = _defaultParams();
        params.oracle = address(0);
        vm.expectRevert(MarketFactory.ZeroAddress.selector);
        factory.createMarket(params);
    }

    function testCreateMarketRejectsExcessiveRakeOverride() public {
        MarketFactory.CreateMarketParams memory params = _defaultParams();
        params.rakeBpsOverride = rakeManager.MAX_RAKE_BPS() + 1;
        vm.expectRevert(MarketFactory.InvalidRakeBps.selector);
        factory.createMarket(params);
    }

    function testOwnershipTransferTwoStep() public {
        factory.transferOwnership(NEW_OWNER);
        assertEq(factory.pendingOwner(), NEW_OWNER);

        vm.prank(NEW_OWNER);
        factory.acceptOwnership();
        assertEq(factory.owner(), NEW_OWNER);

        // New owner can update guardian to themselves.
        vm.prank(NEW_OWNER);
        factory.setGuardian(NEW_OWNER);
        assertEq(factory.guardian(), NEW_OWNER);

        // Previous guardian/owner can no longer toggle pauses.
        vm.expectRevert(MarketFactory.NotGuardianOrOwner.selector);
        vm.prank(address(this));
        factory.setGlobalCommitPaused(true);
    }

    // helpers
    function _defaultParams() private view returns (MarketFactory.CreateMarketParams memory params) {
        params.eventId = "EVT-1";
        params.commitDeadline = commitDeadline;
        params.revealDeadline = revealDeadline;
        params.oracle = ORACLE;
        params.rakeBpsOverride = 0;
        params.payoutMultiplier = 1e18;
        params.payoutCurve = RevealMarket.PayoutCurve.FixedOdds;
        params.floatAmount = 0;
        params.maxMarketSize = 0;
    }

    function _deploy() private returns (address) {
        MarketFactory.CreateMarketParams memory params = _defaultParams();
        return factory.createMarket(params);
    }
}
