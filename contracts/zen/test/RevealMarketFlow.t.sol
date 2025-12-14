// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {MessageHashUtils} from "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

import {MarketFactory} from "../src/MarketFactory.sol";
import {ProtocolPool} from "../src/ProtocolPool.sol";
import {RelayerEscrow} from "../src/RelayerEscrow.sol";
import {RevealMarket} from "../src/RevealMarket.sol";
import {IRevealMarket} from "../src/interfaces/IRevealMarket.sol";
import {MockVerifier} from "./mocks/MockVerifier.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

contract RevealMarketFlowTest is Test {
    RelayerEscrow private relayerEscrow;
    ProtocolPool private protocolPool;
    MarketFactory private factory;
    RevealMarket private implementation;
    MockVerifier private verifier;
    MockERC20 private token;

    address private relayer = makeAddr("relayer");
    address private oracle = makeAddr("oracle");
    uint256 private authKey = 0xA11CE;
    address private authSigner = vm.addr(authKey);
    address private user = makeAddr("user");
    bytes32 private circuitHash = keccak256("settlement");
    uint256 private ticketSize = 1 ether;
    uint256 private protocolCap = 3 ether;
    uint256 private maxCommitments = 8;
    uint256 private rakeBps = 100; // 1%
    uint256 private commitDeadline;
    RevealMarket private market;

    function _leaf(uint256 ticketId, uint256 outcomeId, uint256 amount, bytes32 salt, address leafUser)
        internal
        pure
        returns (bytes32)
    {
        return keccak256(abi.encodePacked(ticketId, outcomeId, amount, keccak256(abi.encodePacked(leafUser, salt))));
    }

    function setUp() external {
        token = new MockERC20();
        relayerEscrow = new RelayerEscrow(relayer, IERC20(address(token)));
        protocolPool = new ProtocolPool(address(this), IERC20(address(token)));
        verifier = new MockVerifier(circuitHash);
        implementation = new RevealMarket();
        factory = new MarketFactory(address(implementation), protocolPool, relayerEscrow, address(token), address(this));
        factory.setGlobalRakeBps(rakeBps);

        protocolPool.setMarketFactory(address(factory));
        vm.prank(relayer);
        relayerEscrow.setMarketFactory(address(factory));

        commitDeadline = block.timestamp + 1 days;

        MarketFactory.CreateMarketParams memory params = MarketFactory.CreateMarketParams({
            oracle: oracle,
            verifier: address(verifier),
            circuitHash: circuitHash,
            commitDeadline: commitDeadline,
            fixedTicketSize: ticketSize,
            maxCommitments: maxCommitments,
            authorizationSigner: authSigner,
            protocolLiabilityCap: protocolCap
        });

        market = RevealMarket(payable(factory.createMarket(params)));
        token.mint(address(this), 5 ether);
        token.approve(address(protocolPool), 5 ether);
        protocolPool.deposit(5 ether);
    }

    function testFullLifecycleWithTopUpAndClaim() external {
        uint256 depositAmount = 3 ether;
        token.mint(user, depositAmount);
        vm.prank(user);
        token.approve(address(relayerEscrow), depositAmount);
        vm.prank(user);
        relayerEscrow.deposit(depositAmount);

        bytes32 salt = keccak256("salt");
        uint256 payoutAmount = 2 ether;
        uint256 outcome = 1;
        bytes32 leaf = _leaf(0, outcome, payoutAmount, salt, user);
        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: leaf,
            user: user,
            nonce: 1,
            expiry: block.timestamp + 12 hours,
            ticketValue: ticketSize
        });

        bytes32 digest = MessageHashUtils.toEthSignedMessageHash(
            keccak256(
                abi.encodePacked(
                    address(market),
                    uint256(1),
                    auth.commitment,
                    auth.user,
                    auth.nonce,
                    auth.expiry,
                    auth.ticketValue,
                    block.chainid
                )
            )
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(authKey, digest);
        bytes memory signature = abi.encodePacked(r, s, v);

        vm.prank(relayer);
        relayerEscrow.commitOnBehalf(user, address(market), auth, signature);

        assertEq(relayerEscrow.balances(user), depositAmount - ticketSize, "user balance debited");
        uint256 rakePerTicket = (ticketSize * rakeBps) / 10_000;
        uint256 netTicket = ticketSize - rakePerTicket;
        assertEq(market.totalEscrow(), netTicket, "escrow matches net ticket");

        vm.warp(commitDeadline + 1);
        vm.prank(oracle);
        market.lock();

        vm.prank(oracle);
        market.postResult(outcome);

        uint256[10] memory signals = [
            uint256(market.commitmentsRoot()),
            uint256(1),
            outcome,
            ticketSize - (ticketSize * rakeBps) / 10_000,
            payoutAmount,
            rakeBps,
            payoutAmount,
            uint256(0),
            uint256(circuitHash),
            uint256(0)
        ];

        vm.prank(oracle);
        market.verifyAndSettle("", signals);

        assertEq(uint8(market.phase()), uint8(IRevealMarket.Phase.Settled));
        uint256 expectedDraw = payoutAmount - netTicket;
        assertApproxEqAbs(protocolPool.consumedLiability(address(market)), expectedDraw, 1);

        // Wrong user should fail because user is bound into the commitment leaf
        address impostor = makeAddr("impostor");
        vm.prank(relayer);
        vm.expectRevert(RevealMarket.InvalidMerkleProof.selector);
        market.claim(impostor, 0, outcome, payoutAmount, salt, new bytes32[](0));

        vm.prank(relayer);
        market.claim(user, 0, outcome, payoutAmount, salt, new bytes32[](0));

        assertEq(uint8(market.phase()), uint8(IRevealMarket.Phase.Settled));
        assertEq(relayerEscrow.balances(user), depositAmount - ticketSize, "escrow debited once");
        assertEq(token.balanceOf(user), payoutAmount, "winnings sent to user");

        // protocol pool retains rake and any unused bankroll
        uint256 expectedRake = (ticketSize * rakeBps) / 10_000;
        assertEq(protocolPool.consumedLiability(address(market)), expectedDraw, "top-up tracked");
        assertApproxEqAbs(token.balanceOf(address(protocolPool)), 5 ether - expectedDraw + expectedRake, 2);
    }
}
