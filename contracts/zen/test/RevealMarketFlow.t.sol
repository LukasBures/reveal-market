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
import {PoseidonTestUtils} from "./utils/PoseidonTestUtils.sol";

contract RevealMarketFlowTest is Test, PoseidonTestUtils {
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

    function _leaf(uint256 ticketId, uint256 outcomeId, uint256 amount, uint256 payout, bytes32 salt, address leafUser)
        internal
        pure
        returns (bytes32)
    {
        return _poseidonLeaf(ticketId, outcomeId, amount, payout, salt, leafUser);
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
        uint256 rakePerTicket = (ticketSize * rakeBps) / 10_000;
        uint256 netAmount = ticketSize - rakePerTicket;
        uint256 payoutAmount = netAmount + 0.1 ether;
        uint256 outcome = 1;
        bytes32 leaf = _leaf(0, outcome, netAmount, payoutAmount, salt, user);
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
        assertEq(market.totalEscrow(), netAmount, "escrow matches net ticket");

        vm.warp(commitDeadline + 1);
        bytes32[] memory leaves = new bytes32[](1);
        leaves[0] = leaf;
        bytes32 root = _buildBatchRoot(leaves, 1);
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = root;
        uint16[] memory counts = new uint16[](1);
        counts[0] = 1;
        vm.startPrank(oracle);
        market.lockBatches(roots, counts, "");
        market.postResult(outcome);

        uint256[10] memory signals = [
            uint256(root),
            uint256(1),
            outcome,
            netAmount,
            payoutAmount,
            rakeBps,
            uint256(0),
            netAmount,
            uint256(circuitHash),
            uint256(0)
        ];

        market.verifyAndSettle("", signals);
        vm.stopPrank();

        assertEq(uint8(market.phase()), uint8(IRevealMarket.Phase.Settled));
        assertEq(protocolPool.consumedLiability(address(market)), payoutAmount - netAmount, "top-up recorded");

        // Wrong user should fail because user is bound into the commitment leaf
        address impostor = makeAddr("impostor");
        vm.prank(relayer);
        vm.expectRevert(RevealMarket.InvalidMerkleProof.selector);
        market.claim(impostor, 0, outcome, netAmount, payoutAmount, salt, _buildMerkleProof(leaves, 1, 0));

        vm.prank(relayer);
        market.claim(user, 0, outcome, netAmount, payoutAmount, salt, _buildMerkleProof(leaves, 1, 0));

        assertEq(uint8(market.phase()), uint8(IRevealMarket.Phase.Settled));
        assertEq(relayerEscrow.balances(user), depositAmount - ticketSize, "escrow debited once");
        assertEq(token.balanceOf(user), payoutAmount, "winnings sent to user");

        // protocol pool retains rake and any unused bankroll
        uint256 expectedRake = (ticketSize * rakeBps) / 10_000;
        assertApproxEqAbs(
            token.balanceOf(address(protocolPool)),
            5 ether + expectedRake - (payoutAmount - netAmount),
            2
        );
    }

    function testClaimDeadlineSweepUnclaimed() external {
        uint256 depositAmount = 3 ether;
        token.mint(user, depositAmount);
        vm.prank(user);
        token.approve(address(relayerEscrow), depositAmount);
        vm.prank(user);
        relayerEscrow.deposit(depositAmount);

        bytes32 salt = keccak256("sweep-salt");
        uint256 rakePerTicket = (ticketSize * rakeBps) / 10_000;
        uint256 netAmount = ticketSize - rakePerTicket;
        uint256 payoutAmount = netAmount + 0.1 ether;
        uint256 outcome = 1;
        bytes32 leaf = _leaf(0, outcome, netAmount, payoutAmount, salt, user);
        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: leaf,
            user: user,
            nonce: 9,
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

        vm.warp(commitDeadline + 1);
        bytes32[] memory leaves = new bytes32[](1);
        leaves[0] = leaf;
        bytes32 root = _buildBatchRoot(leaves, 1);
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = root;
        uint16[] memory counts = new uint16[](1);
        counts[0] = 1;
        vm.startPrank(oracle);
        market.lockBatches(roots, counts, "");
        market.postResult(outcome);

        uint256[10] memory signals = [
            uint256(root),
            uint256(1),
            outcome,
            netAmount,
            payoutAmount,
            rakeBps,
            uint256(0),
            netAmount,
            uint256(circuitHash),
            uint256(0)
        ];

        market.verifyAndSettle("", signals);
        vm.stopPrank();

        uint256 deadline = market.claimDeadline();
        assertGt(deadline, 0, "claim deadline set");
        vm.warp(deadline + 1);

        vm.prank(relayer);
        vm.expectRevert(RevealMarket.ClaimWindowClosed.selector);
        market.claim(user, 0, outcome, netAmount, payoutAmount, salt, _buildMerkleProof(leaves, 1, 0));

        uint256 marketBalance = token.balanceOf(address(market));
        uint256 poolBefore = token.balanceOf(address(protocolPool));
        factory.sweepUnclaimed(address(market), address(protocolPool));

        assertTrue(market.claimsSwept(), "claims swept");
        assertTrue(market.claimsPaused(), "claims paused");
        assertEq(token.balanceOf(address(market)), 0, "market drained");
        assertEq(token.balanceOf(address(protocolPool)), poolBefore + marketBalance, "sweep to pool");
    }
}
