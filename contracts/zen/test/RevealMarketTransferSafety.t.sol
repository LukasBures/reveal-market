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
import {ToggleFeeERC20} from "./mocks/ToggleFeeERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {PoseidonTestUtils} from "./utils/PoseidonTestUtils.sol";

contract RevealMarketTransferSafetyTest is Test, PoseidonTestUtils {
    ToggleFeeERC20 private token;
    RelayerEscrow private relayerEscrow;
    ProtocolPool private protocolPool;
    MarketFactory private factory;
    RevealMarket private implementation;
    MockVerifier private verifier;
    RevealMarket private market;

    uint256 private relayerKey = 0xBEEF;
    address private relayer = vm.addr(relayerKey);
    address private oracle = makeAddr("oracle");
    uint256 private authKey = 0xA11CE;
    address private authSigner = vm.addr(authKey);
    address private user = makeAddr("user");
    bytes32 private circuitHash = keccak256("settlement");
    uint256 private ticketSize = 1 ether;
    uint256 private rakeBps = 200;
    uint256 private commitDeadline;

    function setUp() external {
        token = new ToggleFeeERC20();
        relayerEscrow = new RelayerEscrow(relayer, IERC20(address(token)));
        protocolPool = new ProtocolPool(address(this), IERC20(address(token)));
        verifier = new MockVerifier(circuitHash);
        implementation = new RevealMarket();
        factory = new MarketFactory(address(implementation), protocolPool, relayerEscrow, address(token), address(this));
        factory.setGlobalRakeBps(rakeBps);

        protocolPool.setMarketFactory(address(factory));
        vm.prank(relayer);
        relayerEscrow.setMarketFactory(address(factory));
        factory.setVerifierApproval(address(verifier), true);

        commitDeadline = block.timestamp + 1 days;
        MarketFactory.CreateMarketParams memory params = MarketFactory.CreateMarketParams({
            oracle: oracle,
            verifier: address(verifier),
            circuitHash: circuitHash,
            commitDeadline: commitDeadline,
            fixedTicketSize: ticketSize,
            maxCommitments: 8,
            authorizationSigner: authSigner,
            protocolLiabilityCap: 2 ether
        });
        market = RevealMarket(payable(factory.createMarket(params)));

        token.mint(address(this), 1_000 ether);
        token.approve(address(protocolPool), 1_000 ether);
        protocolPool.deposit(1_000 ether);
    }

    function testClaimRevertsIfTokenBecomesFeeOnTransfer() external {
        bytes32 salt = _salt("claim-fee");
        uint256 netTicket = _netTicket();
        bytes32 leaf = _poseidonLeaf(0, 1, netTicket, netTicket, salt, user);
        _depositAndCommit(leaf, 1);

        vm.warp(commitDeadline + 1);
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = _buildBatchRoot(_wrapLeaf(leaf), 1);
        uint16[] memory counts = new uint16[](1);
        counts[0] = 1;
        bytes memory relayerSig = _signRelayer(roots, counts);
        vm.prank(oracle);
        market.lockBatches(roots, counts, relayerSig);
        vm.prank(oracle);
        market.postResult(1);

        uint256[10] memory signals = [
            uint256(roots[0]),
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

        bytes32[] memory proof = _buildMerkleProof(_wrapLeaf(leaf), 1, 0);
        token.setFeeBps(100);
        vm.expectRevert(RevealMarket.FeeOnTransferNotSupported.selector);
        vm.prank(relayer);
        market.claim(user, 0, 1, netTicket, netTicket, salt, proof);
    }

    function testRefundRevertsIfTokenBecomesFeeOnTransfer() external {
        bytes32 salt = _salt("refund-fee");
        uint256 netTicket = _netTicket();
        bytes32 leaf = _poseidonLeaf(0, 0, netTicket, netTicket, salt, user);
        _depositAndCommit(leaf, 2);

        vm.warp(commitDeadline + 1);
        factory.enableMarketRefunds(address(market));

        token.setFeeBps(100);
        vm.expectRevert(RevealMarket.FeeOnTransferNotSupported.selector);
        vm.prank(user);
        market.refundSelf(0, 0, netTicket, netTicket, salt, new bytes32[](0));
    }

    function testClaimRevertsIfTokenChargesSenderSurcharge() external {
        bytes32 salt = _salt("claim-sender-surcharge");
        uint256 netTicket = _netTicket();
        bytes32 leaf = _poseidonLeaf(0, 1, netTicket, netTicket, salt, user);
        _depositAndCommit(leaf, 3);

        vm.warp(commitDeadline + 1);
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = _buildBatchRoot(_wrapLeaf(leaf), 1);
        uint16[] memory counts = new uint16[](1);
        counts[0] = 1;
        bytes memory relayerSig = _signRelayer(roots, counts);
        vm.prank(oracle);
        market.lockBatches(roots, counts, relayerSig);
        vm.prank(oracle);
        market.postResult(1);

        uint256[10] memory signals = [
            uint256(roots[0]),
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

        bytes32[] memory proof = _buildMerkleProof(_wrapLeaf(leaf), 1, 0);
        token.mint(address(market), 1 ether);
        token.setFeeBps(100);
        token.setSenderSurchargeMode(true);
        vm.expectRevert(RevealMarket.FeeOnTransferNotSupported.selector);
        vm.prank(relayer);
        market.claim(user, 0, 1, netTicket, netTicket, salt, proof);
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
        bytes memory sig = _signAuth(auth);
        vm.prank(relayer);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
    }

    function _signAuth(IRevealMarket.CommitAuth memory auth) private view returns (bytes memory) {
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
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(authKey, digest);
        return abi.encodePacked(r, s, v);
    }

    function _signRelayer(bytes32[] memory roots, uint16[] memory counts) private view returns (bytes memory) {
        bytes32 digest = MessageHashUtils.toEthSignedMessageHash(
            keccak256(abi.encode(address(market), address(factory), market.marketId(), roots, counts, block.chainid))
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(relayerKey, digest);
        return abi.encodePacked(r, s, v);
    }

    function _netTicket() private view returns (uint256) {
        return ticketSize - (ticketSize * rakeBps) / 10_000;
    }

    function _wrapLeaf(bytes32 leaf) private pure returns (bytes32[] memory leaves) {
        leaves = new bytes32[](1);
        leaves[0] = leaf;
    }
}
