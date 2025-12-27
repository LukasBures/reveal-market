// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

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
        factory = new MarketFactory(address(implementation), pool, relayer, address(token), owner);
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
