// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

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

contract RevealMarketRefundsTest is Test, PoseidonTestUtils {
    RelayerEscrow private relayerEscrow;
    ProtocolPool private protocolPool;
    MarketFactory private factory;
    RevealMarket private implementation;
    MockVerifier private verifier;
    MockERC20 private token;
    RevealMarket private market;

    uint256 private relayerKey = 0xBEEF;
    address private relayerOwner = vm.addr(relayerKey);
    address private oracle = makeAddr("oracle");
    uint256 private authKey = 0xA11CE;
    address private authSigner = vm.addr(authKey);
    address private user = makeAddr("user");
    address private stranger = makeAddr("stranger");
    bytes32 private circuitHash = keccak256("settlement");
    uint256 private ticketSize = 1 ether;
    uint256 private protocolCap = 3 ether;
    uint256 private maxCommitments = 8;
    uint256 private rakeBps = 200; // 2%
    uint256 private commitDeadline;

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
        factory.setVerifierApproval(address(verifier), true);

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

        token.mint(address(this), 1_000 ether);
        token.approve(address(protocolPool), 1_000 ether);
        protocolPool.deposit(1_000 ether);
    }

    function testEnableRefundsRequiresCommitDeadline() external {
        vm.expectRevert(RevealMarket.RefundsUnavailable.selector);
        factory.enableMarketRefunds(address(market));
    }

    function testEnableRefundsStillRequiresDeadlineWhenPaused() external {
        factory.setMarketCommitsPaused(address(market), true);
        vm.expectRevert(RevealMarket.RefundsUnavailable.selector);
        factory.enableMarketRefunds(address(market));
    }

    function testRefundFlowAfterEnable() external {
        bytes32 salt = _salt("refund-salt");
        bytes32 leaf = _leaf(0, 1, ticketSize, ticketSize, salt, user);
        _depositAndCommit(leaf, 1);

        vm.warp(commitDeadline + 1);
        factory.enableMarketRefunds(address(market));

        assertEq(uint8(market.phase()), uint8(IRevealMarket.Phase.Cancelled));
        assertTrue(market.commitsPaused(), "commits paused");
        assertTrue(market.claimsPaused(), "claims paused");

        uint256 fullTicket = ticketSize;
        market.refund(user, 0, 1, ticketSize, ticketSize, salt, new bytes32[](0));
        assertEq(token.balanceOf(user), fullTicket, "refund credited");

        vm.expectRevert(RevealMarket.TicketAlreadyClaimed.selector);
        market.refund(user, 0, 1, ticketSize, ticketSize, salt, new bytes32[](0));
    }

    function testRefundAllowsRelayerOwnerAssistance() external {
        bytes32 salt = _salt("refund-assisted");
        bytes32 leaf = _leaf(0, 1, ticketSize, ticketSize, salt, user);
        _depositAndCommit(leaf, 1);

        vm.warp(commitDeadline + 1);
        factory.enableMarketRefunds(address(market));

        vm.prank(relayerOwner);
        market.refund(user, 0, 1, ticketSize, ticketSize, salt, new bytes32[](0));
        assertEq(token.balanceOf(user), ticketSize, "relayer-assisted refund credited");
    }

    function testRefundRequiresEnable() external {
        bytes32 salt = _salt("refund-disabled");
        bytes32 leaf = _leaf(0, 1, ticketSize, ticketSize, salt, user);
        _depositAndCommit(leaf, 1);

        vm.expectRevert(RevealMarket.RefundsNotEnabled.selector);
        market.refund(user, 0, 1, ticketSize, ticketSize, salt, new bytes32[](0));
    }

    function testRefundUnauthorized() external {
        bytes32 salt = _salt("refund-unauth");
        bytes32 leaf = _leaf(0, 1, ticketSize, ticketSize, salt, user);
        _depositAndCommit(leaf, 1);

        vm.warp(commitDeadline + 1);
        factory.enableMarketRefunds(address(market));

        vm.prank(user);
        vm.expectRevert(RevealMarket.NotAuthorized.selector);
        market.refund(user, 0, 1, ticketSize, ticketSize, salt, new bytes32[](0));
    }

    function testRefundSelfAfterEnable() external {
        bytes32 salt = _salt("refund-self");
        bytes32 leaf = _leaf(0, 1, ticketSize, ticketSize, salt, user);
        _depositAndCommit(leaf, 1);

        vm.warp(commitDeadline + 1);
        factory.enableMarketRefunds(address(market));

        uint256 fullTicket = ticketSize;
        vm.prank(user);
        market.refundSelf(0, 1, ticketSize, ticketSize, salt, new bytes32[](0));
        assertEq(token.balanceOf(user), fullTicket, "self refund credited");

        vm.prank(user);
        vm.expectRevert(RevealMarket.TicketAlreadyClaimed.selector);
        market.refundSelf(0, 1, ticketSize, ticketSize, salt, new bytes32[](0));
    }

    function testRefundTicketAllowsPermissionlessExecution() external {
        bytes32 salt = _salt("refund-ticket");
        bytes32 leaf = _leaf(0, 1, ticketSize, ticketSize, salt, user);
        _depositAndCommit(leaf, 91);

        vm.warp(commitDeadline + 1);
        factory.enableMarketRefunds(address(market));

        vm.prank(stranger);
        market.refundTicket(0);
        assertEq(token.balanceOf(user), ticketSize, "ticket owner refunded");
    }

    function testRefundIgnoresMerkleProofAfterLockedTimeoutCancel() external {
        bytes32 salt = _salt("refund-fallback");
        bytes32 leaf = _leaf(0, 0, ticketSize, ticketSize, salt, user);
        _depositAndCommit(leaf, 92);

        vm.warp(commitDeadline + 1);
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = bytes32(uint256(123)); // intentionally invalid for stored commitment
        uint16[] memory counts = new uint16[](1);
        counts[0] = 1;
        bytes memory relayerSig = _signRelayer(roots, counts);
        vm.prank(oracle);
        market.lockBatches(roots, counts, relayerSig);

        vm.warp(block.timestamp + market.SETTLEMENT_TIMEOUT_SECONDS());
        factory.enableMarketRefunds(address(market));

        vm.prank(user);
        market.refundSelf(0, 0, ticketSize, ticketSize, salt, new bytes32[](0));
        assertEq(token.balanceOf(user), ticketSize, "refund fallback succeeds");
    }

    function testRefundSelfRequiresEnable() external {
        bytes32 salt = _salt("refund-self-disabled");
        bytes32 leaf = _leaf(0, 1, ticketSize, ticketSize, salt, user);
        _depositAndCommit(leaf, 1);

        vm.prank(user);
        vm.expectRevert(RevealMarket.RefundsNotEnabled.selector);
        market.refundSelf(0, 1, ticketSize, ticketSize, salt, new bytes32[](0));
    }

    function testEnableRefundsRequiresLockedTimeoutBeforeResult() external {
        bytes32 salt = _salt("locked-timeout");
        bytes32 leaf = _leaf(0, 0, ticketSize, ticketSize, salt, user);
        _depositAndCommit(leaf, 1);

        vm.warp(commitDeadline + 1);
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = _buildBatchRoot(_wrapLeaf(leaf), 1);
        uint16[] memory counts = new uint16[](1);
        counts[0] = 1;
        bytes memory relayerSig = _signRelayer(roots, counts);
        vm.prank(oracle);
        market.lockBatches(roots, counts, relayerSig);

        vm.expectRevert(RevealMarket.RefundsUnavailable.selector);
        factory.enableMarketRefunds(address(market));

        vm.warp(block.timestamp + market.SETTLEMENT_TIMEOUT_SECONDS());
        factory.enableMarketRefunds(address(market));
        assertEq(uint8(market.phase()), uint8(IRevealMarket.Phase.Cancelled));
    }

    function _depositAndCommit(bytes32 commitment, uint256 nonce) internal {
        token.mint(user, ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(ticketSize);

        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: commitment,
            ticketId: market.nextTicketId(),
            user: user,
            nonce: nonce,
            expiry: block.timestamp + 12 hours,
            ticketValue: ticketSize
        });
        bytes memory sig = _signAuth(auth, authKey);
        vm.prank(relayerOwner);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
    }

    function _signAuth(IRevealMarket.CommitAuth memory auth, uint256 privKey) private view returns (bytes memory) {
        bytes32 digest = MessageHashUtils.toEthSignedMessageHash(
            keccak256(
                abi.encodePacked(
                    address(market),
                    market.marketId(),
                    auth.ticketId,
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

    function _signRelayer(bytes32[] memory roots, uint16[] memory counts) private view returns (bytes memory) {
        bytes32 digest = MessageHashUtils.toEthSignedMessageHash(
            keccak256(abi.encode(address(market), address(factory), market.marketId(), roots, counts, block.chainid))
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(relayerKey, digest);
        return abi.encodePacked(r, s, v);
    }

    function _leaf(uint256 ticketId, uint256 outcomeId, uint256 amount, uint256 payout, bytes32 salt, address leafUser)
        internal
        pure
        returns (bytes32)
    {
        return _poseidonLeaf(ticketId, outcomeId, amount, payout, salt, leafUser);
    }

    function _wrapLeaf(bytes32 leaf) private pure returns (bytes32[] memory leaves) {
        leaves = new bytes32[](1);
        leaves[0] = leaf;
    }
}
