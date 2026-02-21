// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {Test} from "forge-std/Test.sol";

import {MarketFactory} from "../src/MarketFactory.sol";
import {ProtocolPool} from "../src/ProtocolPool.sol";
import {RelayerEscrow} from "../src/RelayerEscrow.sol";
import {RevealMarket} from "../src/RevealMarket.sol";
import {MockVerifier} from "./mocks/MockVerifier.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

contract MarketFactoryGuardsTest is Test {
    MarketFactory private factory;
    ProtocolPool private pool;
    RelayerEscrow private relayer;
    RevealMarket private implementation;
    MockVerifier private verifier;
    MockERC20 private token;

    address private owner = makeAddr("owner");
    address private oracle = makeAddr("oracle");
    address private signer = makeAddr("signer");
    bytes32 private circuitHash = keccak256("factory");

    function setUp() external {
        token = new MockERC20();
        pool = new ProtocolPool(owner, IERC20(address(token)));
        relayer = new RelayerEscrow(owner, IERC20(address(token)));
        implementation = new RevealMarket();
        verifier = new MockVerifier(circuitHash);
        verifier.transferOwnership(owner);
        factory = new MarketFactory(address(implementation), pool, relayer, address(token), owner);

        vm.prank(owner);
        pool.setMarketFactory(address(factory));
        vm.prank(owner);
        relayer.setMarketFactory(address(factory));
        vm.prank(owner);
        factory.setVerifierApproval(address(verifier), true);
    }

    function testCreateMarketRevertsWhenPaused() external {
        vm.prank(owner);
        factory.setFactoryPaused(true);
        vm.prank(owner);
        vm.expectRevert(MarketFactory.FactoryPausedErr.selector);
        factory.createMarket(_params(block.timestamp + 1 days));
    }

    function testCreateMarketRevertsOnBadDeadline() external {
        vm.prank(owner);
        vm.expectRevert(MarketFactory.InvalidDeadlines.selector);
        factory.createMarket(_params(block.timestamp));
    }

    function testCreateMarketRevertsOnBadSigner() external {
        MarketFactory.CreateMarketParams memory params = _params(block.timestamp + 1 days);
        params.authorizationSigner = address(0);
        vm.prank(owner);
        vm.expectRevert(MarketFactory.InvalidSigner.selector);
        factory.createMarket(params);
    }

    function testCreateMarketRevertsOnBadOracle() external {
        MarketFactory.CreateMarketParams memory params = _params(block.timestamp + 1 days);
        params.oracle = address(0);
        vm.prank(owner);
        vm.expectRevert(MarketFactory.InvalidOracle.selector);
        factory.createMarket(params);
    }

    function testCreateMarketRevertsOnBadVerifier() external {
        MarketFactory.CreateMarketParams memory params = _params(block.timestamp + 1 days);
        params.verifier = address(0);
        vm.prank(owner);
        vm.expectRevert(MarketFactory.InvalidVerifier.selector);
        factory.createMarket(params);
    }

    function testCreateMarketRevertsOnBadTicketSize() external {
        MarketFactory.CreateMarketParams memory params = _params(block.timestamp + 1 days);
        params.fixedTicketSize = 0;
        vm.prank(owner);
        vm.expectRevert(MarketFactory.InvalidTicketSize.selector);
        factory.createMarket(params);
    }

    function testCreateMarketRevertsOnUnsupportedCommitmentCap() external {
        MarketFactory.CreateMarketParams memory params = _params(block.timestamp + 1 days);
        params.maxCommitments = (uint256(type(uint16).max) + 1) * 256 + 1;
        vm.prank(owner);
        vm.expectRevert(RevealMarket.MaxCommitmentsUnsupported.selector);
        factory.createMarket(params);
    }

    function testCreateMarketRevertsWhenVerifierNotApproved() external {
        MockVerifier otherVerifier = new MockVerifier(keccak256("other"));
        MarketFactory.CreateMarketParams memory params = _params(block.timestamp + 1 days);
        params.verifier = address(otherVerifier);
        params.circuitHash = otherVerifier.circuitHash();

        vm.prank(owner);
        vm.expectRevert(MarketFactory.VerifierNotApproved.selector);
        factory.createMarket(params);
    }

    function testSetVerifierApprovalRequiresOwnerCoupling() external {
        MockVerifier foreignVerifier = new MockVerifier(keccak256("foreign"));
        vm.prank(owner);
        vm.expectRevert(MarketFactory.VerifierOwnerMismatch.selector);
        factory.setVerifierApproval(address(foreignVerifier), true);
    }

    function testSetVerifierApprovalPinsKeyHashPerAddress() external {
        vm.prank(owner);
        factory.setVerifierApproval(address(verifier), false);

        verifier.setVerifyingKeyHash(keccak256("rotated-key"));

        vm.prank(owner);
        vm.expectRevert(MarketFactory.VerifierDrift.selector);
        factory.setVerifierApproval(address(verifier), true);
    }

    function testSetGlobalRakeBpsRejectsTooHigh() external {
        vm.prank(owner);
        vm.expectRevert(MarketFactory.InvalidRakeBps.selector);
        factory.setGlobalRakeBps(20_000);
    }

    function testSyncMarketRakeRequiresKnownMarket() external {
        vm.prank(owner);
        vm.expectRevert(MarketFactory.UnknownMarket.selector);
        factory.syncMarketRake(makeAddr("unknown"));
    }

    function testPauseMarketRequiresKnownMarket() external {
        vm.prank(owner);
        vm.expectRevert(MarketFactory.UnknownMarket.selector);
        factory.setMarketCommitsPaused(makeAddr("unknown"), true);

        vm.prank(owner);
        vm.expectRevert(MarketFactory.UnknownMarket.selector);
        factory.setMarketClaimsPaused(makeAddr("unknown"), true);
    }

    function testSetRelayerCommitsPausedFromFactory() external {
        vm.prank(owner);
        factory.setRelayerCommitsPaused(true);
    }

    function testSetRelayerCommitsPausedSkipsFailingHistoricalRelayer() external {
        vm.prank(owner);
        factory.createMarket(_params(block.timestamp + 1 days));

        RevertingRelayerStub failing = new RevertingRelayerStub(IERC20(address(token)), address(factory));
        vm.prank(owner);
        factory.setRelayerEscrow(RelayerEscrow(payable(address(failing))));
        vm.prank(owner);
        factory.setRelayerEscrow(relayer);

        vm.prank(owner);
        factory.setRelayerCommitsPaused(true);
        assertTrue(relayer.commitsPaused(), "active relayer paused");
    }

    function testSetRelayerCommitsPausedContinuesIfActiveRelayerFails() external {
        vm.prank(owner);
        address marketAddress = factory.createMarket(_params(block.timestamp + 1 days));

        RevertingRelayerStub failing = new RevertingRelayerStub(IERC20(address(token)), address(factory));
        vm.prank(owner);
        factory.updateMarketRelayer(marketAddress, RelayerEscrow(payable(address(failing))));

        vm.prank(owner);
        factory.setRelayerCommitsPaused(true);
    }

    function testSetRelayerCommitsPausedBatchPausesActiveRelayer() external {
        vm.prank(owner);
        factory.createMarket(_params(block.timestamp + 1 days));

        vm.prank(owner);
        factory.setRelayerCommitsPausedBatch(true, 0, 1);
        assertTrue(relayer.commitsPaused(), "active relayer paused");
    }

    function testSetRelayerCommitsPausedBatchRangeGuards() external {
        uint256 maxBatch = factory.MAX_RELAYER_PAUSE_BATCH();

        vm.prank(owner);
        vm.expectRevert(MarketFactory.InvalidPauseRange.selector);
        factory.setRelayerCommitsPausedBatch(true, 0, 0);

        vm.prank(owner);
        vm.expectRevert(MarketFactory.PauseBatchTooLarge.selector);
        factory.setRelayerCommitsPausedBatch(true, 0, maxBatch + 1);

        vm.prank(owner);
        factory.createMarket(_params(block.timestamp + 1 days));

        vm.prank(owner);
        vm.expectRevert(MarketFactory.InvalidPauseRange.selector);
        factory.setRelayerCommitsPausedBatch(true, 1, 1);

        vm.prank(owner);
        vm.expectRevert(MarketFactory.InvalidPauseRange.selector);
        factory.setRelayerCommitsPausedBatch(true, 0, 2);
    }

    function testSetRelayerCommitsPausedChunksLargeActiveSets() external {
        uint256 totalRelayers = factory.MAX_RELAYER_PAUSE_BATCH() + 1;
        for (uint256 i = 0; i < totalRelayers; ++i) {
            RelayerEscrow nextRelayer = new RelayerEscrow(owner, IERC20(address(token)));
            vm.prank(owner);
            nextRelayer.setMarketFactory(address(factory));
            vm.prank(owner);
            factory.setRelayerEscrow(nextRelayer);
            vm.prank(owner);
            factory.createMarket(_params(block.timestamp + 2 days + i));
        }

        vm.prank(owner);
        factory.setRelayerCommitsPaused(true);

        address first = factory.activeRelayers(0);
        address last = factory.activeRelayers(totalRelayers - 1);
        assertTrue(RelayerEscrow(payable(first)).commitsPaused(), "first active relayer paused");
        assertTrue(RelayerEscrow(payable(last)).commitsPaused(), "last active relayer paused");
    }

    function testUpdateMarketRelayerSkipsFailedUnregister() external {
        vm.prank(owner);
        address marketAddress = factory.createMarket(_params(block.timestamp + 1 days));

        RevertingRelayerStub failing = new RevertingRelayerStub(IERC20(address(token)), address(factory));
        vm.prank(owner);
        factory.updateMarketRelayer(marketAddress, RelayerEscrow(payable(address(failing))));

        RelayerEscrow nextRelayer = new RelayerEscrow(owner, IERC20(address(token)));
        vm.prank(owner);
        nextRelayer.setMarketFactory(address(factory));

        vm.prank(owner);
        factory.updateMarketRelayer(marketAddress, nextRelayer);
        assertEq(RevealMarket(payable(marketAddress)).relayerEscrow(), address(nextRelayer));
    }

    function testUpdateMarketRelayerSelfRotationDoesNotStrandOldRelayer() external {
        vm.prank(owner);
        address marketAddress = factory.createMarket(_params(block.timestamp + 1 days));

        vm.prank(owner);
        factory.updateMarketRelayer(marketAddress, relayer);

        RelayerEscrow nextRelayer = new RelayerEscrow(owner, IERC20(address(token)));
        vm.prank(owner);
        nextRelayer.setMarketFactory(address(factory));
        vm.prank(owner);
        factory.updateMarketRelayer(marketAddress, nextRelayer);

        assertEq(factory.activeRelayers(0), address(nextRelayer));
        vm.expectRevert();
        factory.activeRelayers(1);
    }

    function _params(uint256 deadline) private view returns (MarketFactory.CreateMarketParams memory) {
        return MarketFactory.CreateMarketParams({
            oracle: oracle,
            verifier: address(verifier),
            circuitHash: circuitHash,
            commitDeadline: deadline,
            fixedTicketSize: 1 ether,
            maxCommitments: 8,
            authorizationSigner: signer,
            protocolLiabilityCap: 1 ether
        });
    }
}

contract RevertingRelayerStub {
    IERC20 public immutable COLLATERAL_TOKEN;
    address public immutable marketFactory;

    constructor(IERC20 token, address factory) {
        COLLATERAL_TOKEN = token;
        marketFactory = factory;
    }

    function registerMarket(address) external pure {}

    function unregisterMarket(address) external pure {
        revert("stale relayer");
    }

    function setCommitsPaused(bool) external pure {
        revert("stale relayer");
    }
}
