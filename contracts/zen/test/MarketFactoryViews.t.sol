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

contract MarketFactoryViewsTest is Test {
    MarketFactory private factory;
    ProtocolPool private protocolPool;
    RelayerEscrow private relayerEscrow;
    RevealMarket private implementation;
    MockVerifier private verifier;
    MockERC20 private token;

    address private oracle = makeAddr("oracle");
    address private owner = makeAddr("owner");
    address private signer = makeAddr("signer");
    bytes32 private circuitHash = keccak256("view-circuit");

    function setUp() external {
        token = new MockERC20();
        relayerEscrow = new RelayerEscrow(owner, IERC20(address(token)));
        protocolPool = new ProtocolPool(owner, IERC20(address(token)));
        verifier = new MockVerifier(circuitHash);
        implementation = new RevealMarket();
        factory = new MarketFactory(address(implementation), protocolPool, relayerEscrow, address(token), owner);

        vm.prank(owner);
        protocolPool.setMarketFactory(address(factory));
        vm.prank(owner);
        relayerEscrow.setMarketFactory(address(factory));

        MarketFactory.CreateMarketParams memory params = MarketFactory.CreateMarketParams({
            oracle: oracle,
            verifier: address(verifier),
            circuitHash: circuitHash,
            commitDeadline: block.timestamp + 1 days,
            fixedTicketSize: 0.1 ether,
            maxCommitments: 5,
            authorizationSigner: signer,
            protocolLiabilityCap: 1 ether
        });

        vm.prank(owner);
        factory.createMarket(params);
    }

    function testPredictMarketAddressMatchesDeployed() external view {
        address deployed = factory.marketForId(1);
        address predicted = factory.predictMarketAddress(1);
        assertEq(deployed, predicted, "predict matches deployment");
    }

    function testGetMarketParamsReturnsInitState() external view {
        MarketFactory.MarketParams memory params = factory.getMarketParams(1);
        assertEq(params.marketId, 1);
        assertEq(params.market, factory.marketForId(1));
        assertEq(params.oracle, oracle);
        assertEq(params.verifier, address(verifier));
        assertEq(params.circuitHash, circuitHash);
        assertEq(params.ticketSize, 0.1 ether);
        assertEq(params.maxCommitments, 5);
        assertEq(params.authorizationSigner, signer);
        assertEq(params.protocolLiabilityCap, 1 ether);
        assertEq(params.rakeBps, factory.globalRakeBps());
        assertEq(params.relayerEscrow, address(relayerEscrow));
        assertEq(params.protocolPool, address(protocolPool));
        assertGt(params.commitDeadline, block.timestamp);
    }

    function testGetMarketParamsRevertsOnUnknownMarket() external {
        vm.expectRevert(MarketFactory.UnknownMarket.selector);
        factory.getMarketParams(99);
    }

    function testCreateMarketEmitsMarketCreated() external {
        MarketFactory.CreateMarketParams memory params = MarketFactory.CreateMarketParams({
            oracle: oracle,
            verifier: address(verifier),
            circuitHash: circuitHash,
            commitDeadline: block.timestamp + 2 days,
            fixedTicketSize: 0.1 ether,
            maxCommitments: 5,
            authorizationSigner: signer,
            protocolLiabilityCap: 1 ether
        });

        address predicted = factory.predictMarketAddress(2);
        vm.expectEmit(true, true, true, true, address(factory));
        emit MarketFactory.MarketCreated(2, predicted, oracle, circuitHash, 0.1 ether, params.commitDeadline, 1 ether);
        vm.prank(owner);
        factory.createMarket(params);
    }
}
