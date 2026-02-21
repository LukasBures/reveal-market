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

contract RevealMarketOracleClaimFallbackTest is Test, PoseidonTestUtils {
    RelayerEscrow private relayerEscrow;
    ProtocolPool private protocolPool;
    MarketFactory private factory;
    RevealMarket private implementation;
    MockVerifier private verifier;
    MockERC20 private token;
    RevealMarket private market;

    uint256 private relayerKey = 0xBEEF;
    address private relayer = vm.addr(relayerKey);
    uint256 private oracleKey = 0xCAFE;
    address private oracle = vm.addr(oracleKey);
    uint256 private authKey = 0xA11CE;
    address private authSigner = vm.addr(authKey);
    address private user = makeAddr("user");
    bytes32 private circuitHash = keccak256("settlement");
    uint256 private ticketSize = 1 ether;
    uint256 private commitDeadline;

    function setUp() external {
        token = new MockERC20();
        relayerEscrow = new RelayerEscrow(relayer, IERC20(address(token)));
        protocolPool = new ProtocolPool(address(this), IERC20(address(token)));
        verifier = new MockVerifier(circuitHash);
        implementation = new RevealMarket();
        factory = new MarketFactory(address(implementation), protocolPool, relayerEscrow, address(token), address(this));

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
            protocolLiabilityCap: 3 ether
        });
        market = RevealMarket(payable(factory.createMarket(params)));

        token.mint(address(this), 10 ether);
        token.approve(address(protocolPool), 10 ether);
        protocolPool.deposit(10 ether);
    }

    function testClaimWithOracleAuthorizationPaysRecordedOwnerWithoutMerkleProof() external {
        (bytes32 leaf, bytes32 salt, uint256 netTicket, uint256 payout) = _commitSingleTicket();
        _lockAndSettle(leaf, netTicket, payout);

        vm.prank(relayer);
        vm.expectRevert(RevealMarket.InvalidMerkleProof.selector);
        market.claim(user, 0, 1, netTicket, payout, salt, new bytes32[](0));

        uint256 expiry = block.timestamp + 1 hours;
        bytes memory oracleSig = _signOracleClaim(0, payout, expiry, user);

        vm.prank(makeAddr("executor"));
        market.claimWithOracleAuthorization(0, payout, expiry, oracleSig);
        assertEq(token.balanceOf(user), payout, "user received fallback payout");
    }

    function testClaimWithOracleAuthorizationRejectsInvalidSignature() external {
        (bytes32 leaf,, uint256 netTicket, uint256 payout) = _commitSingleTicket();
        _lockAndSettle(leaf, netTicket, payout);

        uint256 expiry = block.timestamp + 1 hours;
        bytes memory badSig = _signClaimDigest(0, payout, expiry, user, authKey);
        vm.expectRevert(RevealMarket.InvalidSignature.selector);
        market.claimWithOracleAuthorization(0, payout, expiry, badSig);
    }

    function testClaimWithOracleAuthorizationRejectsExpiredAuthorization() external {
        (bytes32 leaf,, uint256 netTicket, uint256 payout) = _commitSingleTicket();
        _lockAndSettle(leaf, netTicket, payout);

        uint256 expiry = block.timestamp + 5 minutes;
        bytes memory oracleSig = _signOracleClaim(0, payout, expiry, user);
        vm.warp(expiry + 1);
        vm.expectRevert(RevealMarket.OracleAuthorizationExpired.selector);
        market.claimWithOracleAuthorization(0, payout, expiry, oracleSig);
    }

    function _commitSingleTicket() internal returns (bytes32 leaf, bytes32 salt, uint256 netTicket, uint256 payout) {
        uint256 rake = (ticketSize * market.rakeBps()) / 10_000;
        netTicket = ticketSize - rake;
        payout = netTicket + 0.15 ether;
        salt = _salt("fallback-claim");
        leaf = _poseidonLeaf(0, 1, netTicket, payout, salt, user);

        token.mint(user, ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(ticketSize);

        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: leaf,
            ticketId: 0,
            user: user,
            nonce: 1,
            expiry: block.timestamp + 12 hours,
            ticketValue: ticketSize
        });
        vm.prank(user);
        relayerEscrow.approveCommitAuthorization(address(market), auth);
        bytes memory signature = _signAuth(auth);
        vm.prank(relayer);
        relayerEscrow.commitOnBehalf(user, address(market), auth, signature);
    }

    function _lockAndSettle(bytes32 leaf, uint256 netTicket, uint256 payout) internal {
        vm.warp(commitDeadline + 1);
        bytes32[] memory leaves = new bytes32[](1);
        leaves[0] = leaf;
        bytes32 root = _buildBatchRoot(leaves, 1);
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = root;
        uint16[] memory counts = new uint16[](1);
        counts[0] = 1;
        bytes memory relayerSig = _signRelayer(roots, counts);

        vm.startPrank(oracle);
        market.lockBatches(roots, counts, relayerSig);
        market.postResult(1);

        uint256[10] memory signals = [
            uint256(root),
            market.marketId(),
            uint256(1),
            netTicket,
            payout,
            market.rakeBps(),
            uint256(0),
            payout,
            uint256(circuitHash),
            uint256(0)
        ];
        market.verifyAndSettle("", signals);
        vm.stopPrank();
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

    function _signOracleClaim(uint256 ticketId, uint256 payout, uint256 expiry, address ticketOwner)
        private
        view
        returns (bytes memory)
    {
        return _signClaimDigest(ticketId, payout, expiry, ticketOwner, oracleKey);
    }

    function _signClaimDigest(uint256 ticketId, uint256 payout, uint256 expiry, address ticketOwner, uint256 signerKey)
        private
        view
        returns (bytes memory)
    {
        bytes32 digest = MessageHashUtils.toEthSignedMessageHash(
            keccak256(
                abi.encode(
                    address(market),
                    market.marketId(),
                    ticketId,
                    ticketOwner,
                    uint256(1),
                    payout,
                    expiry,
                    block.chainid,
                    "CLAIM_ORACLE_V1"
                )
            )
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(signerKey, digest);
        return abi.encodePacked(r, s, v);
    }
}
