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

contract RevealMarketEventsTest is Test, PoseidonTestUtils {
    RelayerEscrow private relayerEscrow;
    ProtocolPool private protocolPool;
    MarketFactory private factory;
    RevealMarket private implementation;
    MockVerifier private verifier;
    MockERC20 private token;
    RevealMarket private market;

    address private relayerOwner = makeAddr("relayer");
    address private oracle = makeAddr("oracle");
    uint256 private authKey = 0xA11CE;
    address private authSigner = vm.addr(authKey);
    address private user = makeAddr("user");
    bytes32 private circuitHash = keccak256("settlement");
    uint256 private ticketSize = 1 ether;
    uint256 private commitDeadline;
    uint256 private rakeBps = 200;

    function setUp() external {
        token = new MockERC20();
        relayerEscrow = new RelayerEscrow(relayerOwner, IERC20(address(token)));
        protocolPool = new ProtocolPool(address(this), IERC20(address(token)));
        verifier = new MockVerifier(circuitHash);
        implementation = new RevealMarket();
        factory = new MarketFactory(address(implementation), protocolPool, relayerEscrow, address(token), address(this));
        factory.setGlobalRakeBps(rakeBps);

        protocolPool.setMarketFactory(address(factory));
        vm.prank(relayerOwner);
        relayerEscrow.setMarketFactory(address(factory));

        commitDeadline = block.timestamp + 1 days;
        MarketFactory.CreateMarketParams memory params = MarketFactory.CreateMarketParams({
            oracle: oracle,
            verifier: address(verifier),
            circuitHash: circuitHash,
            commitDeadline: commitDeadline,
            fixedTicketSize: ticketSize,
            maxCommitments: 0,
            authorizationSigner: authSigner,
            protocolLiabilityCap: 1000 ether
        });

        market = RevealMarket(payable(factory.createMarket(params)));
    }

    function testLockBatchesEmitsLocked() external {
        bytes32 leaf = _commitTicket(_salt("lock"));
        vm.warp(commitDeadline + 1);
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = _buildBatchRoot(_wrapLeaf(leaf), 1);
        uint16[] memory counts = new uint16[](1);
        counts[0] = 1;

        vm.expectEmit(true, false, false, true, address(market));
        emit RevealMarket.Locked(roots[0], 1);
        vm.prank(oracle);
        market.lockBatches(roots, counts, "");
    }

    function testPostResultEmits() external {
        bytes32 leaf = _commitTicket(_salt("result"));
        _lockSingleBatch(leaf);

        vm.expectEmit(true, false, false, true, address(market));
        emit RevealMarket.ResultPosted(1);
        vm.prank(oracle);
        market.postResult(1);
    }

    function testVerifyAndSettleEmitsSettled() external {
        bytes32 leaf = _commitTicket(_salt("settle"));
        bytes32 root = _lockSingleBatch(leaf);

        vm.prank(oracle);
        market.postResult(1);

        uint256 netTicket = _netTicket();
        uint256[10] memory signals = [
            uint256(root),
            market.marketId(),
            uint256(1),
            netTicket,
            netTicket,
            rakeBps,
            uint256(0),
            netTicket,
            uint256(circuitHash),
            uint256(0)
        ];

        uint256 expectedRake = (ticketSize * rakeBps) / 10_000;
        vm.expectEmit(false, false, false, true, address(market));
        emit RevealMarket.Settled(netTicket, expectedRake, 0, 0, netTicket);
        vm.prank(oracle);
        market.verifyAndSettle("", signals);
    }

    function testClaimEmitsClaimed() external {
        bytes32 leaf = _commitTicket(_salt("claim"));
        bytes32 root = _lockSingleBatch(leaf);
        vm.prank(oracle);
        market.postResult(1);

        uint256 netTicket = _netTicket();
        uint256[10] memory signals = [
            uint256(root),
            market.marketId(),
            uint256(1),
            netTicket,
            netTicket,
            rakeBps,
            uint256(0),
            netTicket,
            uint256(circuitHash),
            uint256(0)
        ];
        vm.prank(oracle);
        market.verifyAndSettle("", signals);

        bytes32[] memory leaves = new bytes32[](1);
        leaves[0] = leaf;
        bytes32[] memory proof = _buildMerkleProof(leaves, 1, 0);

        vm.expectEmit(true, true, true, true, address(market));
        emit RevealMarket.Claimed(relayerOwner, user, 0, netTicket);
        vm.prank(relayerOwner);
        market.claim(user, 0, 1, netTicket, netTicket, _salt("claim"), proof);
    }

    function testExtendClaimDeadlineEmits() external {
        uint256 newDeadline = block.timestamp + 30 days;
        vm.expectEmit(false, false, false, true, address(market));
        emit RevealMarket.ClaimDeadlineExtended(newDeadline);
        vm.prank(address(factory));
        market.extendClaimDeadline(newDeadline);
    }

    function testSweepUnclaimedEmits() external {
        bytes32 leaf = _commitTicket(_salt("sweep"));
        bytes32 root = _lockSingleBatch(leaf);
        vm.prank(oracle);
        market.postResult(1);

        uint256 netTicket = _netTicket();
        uint256[10] memory signals = [
            uint256(root),
            market.marketId(),
            uint256(1),
            netTicket,
            netTicket,
            rakeBps,
            uint256(0),
            netTicket,
            uint256(circuitHash),
            uint256(0)
        ];
        vm.prank(oracle);
        market.verifyAndSettle("", signals);

        uint256 deadline = market.claimDeadline();
        vm.warp(deadline + 1);
        vm.expectEmit(true, false, false, true, address(market));
        emit RevealMarket.ClaimsSwept(address(protocolPool), netTicket);
        vm.prank(address(factory));
        market.sweepUnclaimed(address(protocolPool));
    }

    function testPauseEvents() external {
        vm.expectEmit(false, false, false, true, address(market));
        emit RevealMarket.CommitsPausedSet(true);
        vm.prank(address(factory));
        market.setCommitsPaused(true);

        vm.expectEmit(false, false, false, true, address(market));
        emit RevealMarket.ClaimsPausedSet(true);
        vm.prank(address(factory));
        market.setClaimsPaused(true);
    }

    function testRefundEvents() external {
        _commitTicket(_salt("refund"));
        vm.warp(commitDeadline + 1);

        vm.expectEmit(true, false, false, true, address(market));
        emit RevealMarket.RefundsEnabled(relayerOwner);
        vm.prank(relayerOwner);
        market.enableRefunds();

        vm.expectEmit(true, true, true, true, address(market));
        emit RevealMarket.Refunded(relayerOwner, user, 0, _netTicket());
        vm.prank(relayerOwner);
        market.refund(user, 0, 1, _netTicket(), _netTicket(), _salt("refund"), new bytes32[](0));
    }

    function _commitTicket(bytes32 salt) internal returns (bytes32 leaf) {
        leaf = _poseidonLeaf(0, 1, _netTicket(), _netTicket(), salt, user);
        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: leaf,
            user: user,
            nonce: 1,
            expiry: block.timestamp + 12 hours,
            ticketValue: ticketSize
        });
        bytes memory sig = _signAuth(auth, authKey);

        token.mint(user, ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(ticketSize);

        vm.prank(relayerOwner);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
    }

    function _netTicket() internal view returns (uint256) {
        return ticketSize - (ticketSize * rakeBps) / 10_000;
    }

    function _lockSingleBatch(bytes32 leaf) internal returns (bytes32 root) {
        vm.warp(commitDeadline + 1);
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = _buildBatchRoot(_wrapLeaf(leaf), 1);
        uint16[] memory counts = new uint16[](1);
        counts[0] = 1;
        vm.prank(oracle);
        market.lockBatches(roots, counts, "");
        return roots[0];
    }

    function _signAuth(IRevealMarket.CommitAuth memory auth, uint256 privKey) private view returns (bytes memory) {
        bytes32 digest = MessageHashUtils.toEthSignedMessageHash(
            keccak256(
                abi.encodePacked(
                    address(market),
                    market.marketId(),
                    auth.commitment,
                    auth.user,
                    auth.nonce,
                    auth.expiry,
                    auth.ticketValue,
                    block.chainid
                )
            )
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(privKey, digest);
        return abi.encodePacked(r, s, v);
    }

    function _wrapLeaf(bytes32 leaf) private pure returns (bytes32[] memory leaves) {
        leaves = new bytes32[](1);
        leaves[0] = leaf;
    }
}
