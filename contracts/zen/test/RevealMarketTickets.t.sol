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

contract RevealMarketTicketsTest is Test, PoseidonTestUtils {
    RelayerEscrow private relayerEscrow;
    ProtocolPool private protocolPool;
    MarketFactory private factory;
    RevealMarket private implementation;
    MockVerifier private verifier;
    MockERC20 private token;
    RevealMarket private market;

    address private relayer = makeAddr("relayer");
    address private oracle = makeAddr("oracle");
    uint256 private authKey = 0xA11CE;
    address private authSigner = vm.addr(authKey);
    address private user = makeAddr("user");
    bytes32 private circuitHash = keccak256("settlement");
    uint256 private ticketSize = 0.1 ether;
    uint256 private protocolCap = 3 ether;
    uint256 private maxCommitments = 2;
    uint256 private rakeBps = 200; // 2%
    uint256 private commitDeadline;

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

        token.mint(user, 1 ether);
        vm.prank(user);
        token.approve(address(relayerEscrow), 1 ether);
        vm.prank(user);
        relayerEscrow.deposit(1 ether);
    }

    function _buildAuth(bytes32 commitment, uint256 ticketId, uint256 nonce, uint256 expiry, address authUser)
        internal
        view
        returns (IRevealMarket.CommitAuth memory)
    {
        return IRevealMarket.CommitAuth({
            commitment: commitment,
            ticketId: ticketId,
            user: authUser,
            nonce: nonce,
            expiry: expiry,
            ticketValue: ticketSize
        });
    }

    function _signAuth(
        IRevealMarket.CommitAuth memory auth,
        address digestUser,
        uint256 chainIdOverride,
        uint256 signerKey
    ) internal view returns (bytes memory sig) {
        bytes32 digest = MessageHashUtils.toEthSignedMessageHash(
            keccak256(
                abi.encodePacked(
                    address(market),
                    uint256(1),
                    auth.ticketId,
                    auth.commitment,
                    digestUser,
                    auth.nonce,
                    auth.expiry,
                    auth.ticketValue,
                    chainIdOverride
                )
            )
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(signerKey, digest);
        sig = abi.encodePacked(r, s, v);
    }

    function _signAuth(bytes32 commitment, uint256 ticketId, uint256 nonce, uint256 expiry)
        internal
        view
        returns (bytes memory sig)
    {
        IRevealMarket.CommitAuth memory auth = _buildAuth(commitment, ticketId, nonce, expiry, user);
        return _signAuth(auth, user, block.chainid, authKey);
    }

    function _leaf(uint256 ticketId, uint256 outcomeId, uint256 amount, uint256 payout, bytes32 salt, address leafUser)
        internal
        pure
        returns (bytes32)
    {
        return _poseidonLeaf(ticketId, outcomeId, amount, payout, salt, leafUser);
    }

    function testNextTicketIdIncrementsWithCommits() external {
        assertEq(market.nextTicketId(), 0);
        bytes32 leaf0 = _leaf(0, 0, ticketSize, ticketSize, _salt("salt0"), user);
        IRevealMarket.CommitAuth memory auth0 = IRevealMarket.CommitAuth({
            commitment: leaf0,
            ticketId: 0,
            user: user,
            nonce: 1,
            expiry: block.timestamp + 12 hours,
            ticketValue: ticketSize
        });
        _approveAndCommit(user, address(market), auth0, _signAuth(leaf0, auth0.ticketId, auth0.nonce, auth0.expiry));
        assertEq(market.nextTicketId(), 1);

        bytes32 leaf1 = _leaf(1, 1, ticketSize, ticketSize, _salt("salt1"), user);
        IRevealMarket.CommitAuth memory auth1 = IRevealMarket.CommitAuth({
            commitment: leaf1,
            ticketId: 1,
            user: user,
            nonce: 2,
            expiry: block.timestamp + 12 hours,
            ticketValue: ticketSize
        });
        _approveAndCommit(user, address(market), auth1, _signAuth(leaf1, auth1.ticketId, auth1.nonce, auth1.expiry));
        assertEq(market.nextTicketId(), 2);
    }

    function testPoseidonLeafMatchesVector() external pure {
        address vectorUser = address(0x1111111111111111111111111111111111111111);
        bytes32 salt = hex"2222222222222222222222222222222222222222222222222222222222222222";
        bytes32 expected = hex"1215e017c699d4aaaa120cfd688b4615013b6e0e3f56dbd0aa224a23582ee098";
        bytes32 leaf = _poseidonLeaf(42, 1, 123456789, 123456789, salt, vectorUser);
        assertEq(leaf, expected, "poseidon leaf mismatch");
    }

    function testCommitEmitsAndTracksEscrowAndRake() external {
        bytes32 leaf = _leaf(0, 0, ticketSize, ticketSize, _salt("salt"), user);
        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: leaf,
            ticketId: 0,
            user: user,
            nonce: 1,
            expiry: block.timestamp + 12 hours,
            ticketValue: ticketSize
        });
        bytes memory sig = _signAuth(leaf, auth.ticketId, auth.nonce, auth.expiry);

        uint256 expectedRake = (ticketSize * rakeBps) / 10_000;
        uint256 net = ticketSize - expectedRake;
        vm.prank(user);
        relayerEscrow.approveCommitAuthorization(address(market), auth);
        vm.expectEmit(true, false, false, true, address(market));
        emit RevealMarket.Committed(0, leaf, net);
        vm.prank(relayer);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
        assertEq(market.totalEscrow(), net, "totalEscrow");
        assertEq(market.rakeCollected(), expectedRake, "rakeCollected");
    }

    function testCommitRevertsOnWrongTicketSize() external {
        bytes32 leaf = _leaf(0, 0, ticketSize + 1, ticketSize + 1, _salt("salt"), user);
        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: leaf,
            ticketId: 0,
            user: user,
            nonce: 1,
            expiry: block.timestamp + 12 hours,
            ticketValue: ticketSize + 1
        });
        bytes memory sig = _signAuth(leaf, auth.ticketId, auth.nonce, auth.expiry);

        vm.prank(user);
        relayerEscrow.approveCommitAuthorization(address(market), auth);
        vm.expectRevert(RevealMarket.InvalidPayment.selector);
        vm.prank(relayer);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
    }

    function testCommitRevertsOnTicketIndexMismatch() external {
        bytes32 leaf = _leaf(1, 0, ticketSize, ticketSize, _salt("ticket-mismatch"), user);
        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: leaf,
            ticketId: 1,
            user: user,
            nonce: 404,
            expiry: block.timestamp + 12 hours,
            ticketValue: ticketSize
        });
        bytes memory sig = _signAuth(leaf, auth.ticketId, auth.nonce, auth.expiry);

        vm.prank(user);
        relayerEscrow.approveCommitAuthorization(address(market), auth);
        vm.expectRevert(RevealMarket.TicketIndexMismatch.selector);
        vm.prank(relayer);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
    }

    function testCommitRevertsWhenSignedTicketIdDiffersFromAuth() external {
        bytes32 leaf = _leaf(0, 0, ticketSize, ticketSize, _salt("ticket-sign-mismatch"), user);
        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: leaf,
            ticketId: 0,
            user: user,
            nonce: 505,
            expiry: block.timestamp + 12 hours,
            ticketValue: ticketSize
        });

        // Sign for a different ticket id than the auth payload sent on-chain.
        IRevealMarket.CommitAuth memory signedAuth = IRevealMarket.CommitAuth({
            commitment: auth.commitment,
            ticketId: 1,
            user: auth.user,
            nonce: auth.nonce,
            expiry: auth.expiry,
            ticketValue: auth.ticketValue
        });
        bytes memory sig = _signAuth(signedAuth, user, block.chainid, authKey);

        vm.prank(user);
        relayerEscrow.approveCommitAuthorization(address(market), auth);
        vm.expectRevert(RevealMarket.InvalidSignature.selector);
        vm.prank(relayer);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
    }

    function testCommitRevertsOnNonceReplay() external {
        bytes32 leaf = _leaf(0, 0, ticketSize, ticketSize, _salt("salt"), user);
        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: leaf,
            ticketId: 0,
            user: user,
            nonce: 123,
            expiry: block.timestamp + 12 hours,
            ticketValue: ticketSize
        });
        bytes memory sig = _signAuth(leaf, auth.ticketId, auth.nonce, auth.expiry);
        _approveAndCommit(user, address(market), auth, sig);

        IRevealMarket.CommitAuth memory replayAuth = IRevealMarket.CommitAuth({
            commitment: leaf, ticketId: 1, user: user, nonce: auth.nonce, expiry: auth.expiry, ticketValue: ticketSize
        });
        bytes memory replaySig =
            _signAuth(replayAuth.commitment, replayAuth.ticketId, replayAuth.nonce, replayAuth.expiry);

        vm.prank(user);
        relayerEscrow.approveCommitAuthorization(address(market), replayAuth);
        vm.expectRevert(RevealMarket.CommitReplay.selector);
        vm.prank(relayer);
        relayerEscrow.commitOnBehalf(user, address(market), replayAuth, replaySig);
    }

    function testCommitAllowsSameNonceDifferentUser() external {
        address user2 = makeAddr("user2");
        token.mint(user2, 1 ether);
        vm.prank(user2);
        token.approve(address(relayerEscrow), 1 ether);
        vm.prank(user2);
        relayerEscrow.deposit(1 ether);

        uint256 expiry = block.timestamp + 12 hours;
        bytes32 leaf0 = _leaf(0, 0, ticketSize, ticketSize, _salt("salt-a"), user);
        IRevealMarket.CommitAuth memory auth0 = _buildAuth(leaf0, 0, 42, expiry, user);
        bytes memory sig0 = _signAuth(auth0, user, block.chainid, authKey);
        _approveAndCommit(user, address(market), auth0, sig0);

        bytes32 leaf1 = _leaf(1, 1, ticketSize, ticketSize, _salt("salt-b"), user2);
        IRevealMarket.CommitAuth memory auth1 = _buildAuth(leaf1, 1, 42, expiry, user2);
        bytes memory sig1 = _signAuth(auth1, user2, block.chainid, authKey);
        _approveAndCommit(user2, address(market), auth1, sig1);

        assertEq(market.nextTicketId(), 2);
    }

    function testCommitRevertsOnExpiry() external {
        bytes32 leaf = _leaf(0, 0, ticketSize, ticketSize, _salt("salt"), user);
        uint256 pastExpiry = block.timestamp - 1;
        IRevealMarket.CommitAuth memory auth = _buildAuth(leaf, 0, 1, pastExpiry, user);
        bytes memory sig = _signAuth(leaf, auth.ticketId, auth.nonce, auth.expiry);

        vm.prank(user);
        relayerEscrow.approveCommitAuthorization(address(market), auth);
        vm.expectRevert(RevealMarket.CommitExpired.selector);
        vm.prank(relayer);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
    }

    function testCommitWindowClosed() external {
        vm.warp(commitDeadline + 1);
        bytes32 leaf = _leaf(0, 0, ticketSize, ticketSize, _salt("salt"), user);
        IRevealMarket.CommitAuth memory auth = _buildAuth(leaf, 0, 1, block.timestamp + 12 hours, user);
        bytes memory sig = _signAuth(leaf, auth.ticketId, auth.nonce, auth.expiry);

        vm.prank(user);
        relayerEscrow.approveCommitAuthorization(address(market), auth);
        vm.expectRevert(RevealMarket.CommitWindowClosed.selector);
        vm.prank(relayer);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
    }

    function testCommitRevertsAtMaxCommitments() external {
        for (uint256 i = 0; i < maxCommitments; i++) {
            bytes32 leaf = _leaf(i, 0, ticketSize, ticketSize, _salt("salt"), user);
            IRevealMarket.CommitAuth memory auth = _buildAuth(leaf, i, i + 1, block.timestamp + 12 hours, user);
            _approveAndCommit(user, address(market), auth, _signAuth(leaf, auth.ticketId, auth.nonce, auth.expiry));
        }
        bytes32 overflowLeaf = _leaf(99, 0, ticketSize, ticketSize, _salt("salt"), user);
        IRevealMarket.CommitAuth memory overflowAuth =
            _buildAuth(overflowLeaf, market.nextTicketId(), 999, block.timestamp + 12 hours, user);
        vm.prank(user);
        relayerEscrow.approveCommitAuthorization(address(market), overflowAuth);
        vm.expectRevert(RevealMarket.MaxCommitmentsReached.selector);
        vm.prank(relayer);
        relayerEscrow.commitOnBehalf(
            user,
            address(market),
            overflowAuth,
            _signAuth(overflowLeaf, overflowAuth.ticketId, overflowAuth.nonce, overflowAuth.expiry)
        );
    }

    function testPoseidonLeafMatchesHarness() external {
        RevealMarketHarness harness = new RevealMarketHarness();
        bytes32 salt = bytes32(uint256(123));
        bytes32 expected = _poseidonLeaf(7, 1, ticketSize, ticketSize, salt, user);
        bytes32 actual = harness.computeLeaf(7, 1, ticketSize, ticketSize, salt, user);
        assertEq(actual, expected, "poseidon leaf mismatch");
    }

    function testComputeLeafRejectsFieldOverflow() external {
        RevealMarketHarness harness = new RevealMarketHarness();
        uint256 fieldPrime = 21888242871839275222246405745257275088548364400416034343698204186575808495617;
        vm.expectRevert(RevealMarket.FieldElementOutOfRange.selector);
        harness.computeLeaf(fieldPrime, 1, ticketSize, ticketSize, bytes32(0), user);
    }

    function testCommitRevertsWhenSignatureUsesDifferentUser() external {
        bytes32 leaf = _leaf(0, 1, ticketSize, ticketSize, _salt("salt-user"), user);
        IRevealMarket.CommitAuth memory auth = _buildAuth(leaf, 0, 11, block.timestamp + 12 hours, user);
        address impostor = makeAddr("impostor");
        bytes memory sig = _signAuth(auth, impostor, block.chainid, authKey);

        vm.prank(user);
        relayerEscrow.approveCommitAuthorization(address(market), auth);
        vm.expectRevert(RevealMarket.InvalidSignature.selector);
        vm.prank(relayer);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
    }

    function testCommitRevertsWhenSignatureChainIdMismatch() external {
        bytes32 leaf = _leaf(0, 1, ticketSize, ticketSize, _salt("salt-chain"), user);
        IRevealMarket.CommitAuth memory auth = _buildAuth(leaf, 0, 12, block.timestamp + 12 hours, user);
        bytes memory sig = _signAuth(auth, user, block.chainid + 1, authKey);

        vm.prank(user);
        relayerEscrow.approveCommitAuthorization(address(market), auth);
        vm.expectRevert(RevealMarket.InvalidSignature.selector);
        vm.prank(relayer);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
    }

    function testCommitSignatureCannotReplayAcrossMarkets() external {
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
        RevealMarket market2 = RevealMarket(payable(factory.createMarket(params)));

        bytes32 leaf = _leaf(0, 1, ticketSize, ticketSize, _salt("salt-replay"), user);
        IRevealMarket.CommitAuth memory auth = _buildAuth(leaf, 0, 21, block.timestamp + 12 hours, user);
        bytes memory sig = _signAuth(auth, user, block.chainid, authKey);

        _approveAndCommit(user, address(market), auth, sig);

        vm.prank(user);
        relayerEscrow.approveCommitAuthorization(address(market2), auth);
        vm.expectRevert(RevealMarket.InvalidSignature.selector);
        vm.prank(relayer);
        relayerEscrow.commitOnBehalf(user, address(market2), auth, sig);
    }

    function _approveAndCommit(
        address commitUser,
        address marketAddr,
        IRevealMarket.CommitAuth memory auth,
        bytes memory sig
    ) internal {
        vm.prank(commitUser);
        relayerEscrow.approveCommitAuthorization(marketAddr, auth);
        vm.prank(relayer);
        relayerEscrow.commitOnBehalf(commitUser, marketAddr, auth, sig);
    }
}

contract RevealMarketHarness is RevealMarket {
    function computeLeaf(
        uint256 ticketId,
        uint256 outcomeId,
        uint256 amount,
        uint256 payout,
        bytes32 salt,
        address user
    ) external pure returns (bytes32) {
        return _computeLeaf(ticketId, outcomeId, amount, payout, salt, user);
    }
}
