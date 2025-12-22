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

    function _buildAuth(bytes32 commitment, uint256 nonce, uint256 expiry, address authUser)
        internal
        view
        returns (IRevealMarket.CommitAuth memory)
    {
        return IRevealMarket.CommitAuth({
            commitment: commitment,
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

    function _signAuth(bytes32 commitment, uint256 nonce, uint256 expiry) internal view returns (bytes memory sig) {
        IRevealMarket.CommitAuth memory auth = _buildAuth(commitment, nonce, expiry, user);
        return _signAuth(auth, user, block.chainid, authKey);
    }

    function _leaf(uint256 ticketId, uint256 outcomeId, uint256 amount, bytes32 salt, address leafUser)
        internal
        pure
        returns (bytes32)
    {
        return _poseidonLeaf(ticketId, outcomeId, amount, salt, leafUser);
    }

    function testNextTicketIdIncrementsWithCommits() external {
        assertEq(market.nextTicketId(), 0);
        bytes32 leaf0 = _leaf(0, 0, ticketSize, bytes32("salt0"), user);
        IRevealMarket.CommitAuth memory auth0 = IRevealMarket.CommitAuth({
            commitment: leaf0,
            user: user,
            nonce: 1,
            expiry: block.timestamp + 12 hours,
            ticketValue: ticketSize
        });
        vm.prank(relayer);
        relayerEscrow.commitOnBehalf(user, address(market), auth0, _signAuth(leaf0, auth0.nonce, auth0.expiry));
        assertEq(market.nextTicketId(), 1);

        bytes32 leaf1 = _leaf(1, 1, ticketSize, bytes32("salt1"), user);
        IRevealMarket.CommitAuth memory auth1 = IRevealMarket.CommitAuth({
            commitment: leaf1,
            user: user,
            nonce: 2,
            expiry: block.timestamp + 12 hours,
            ticketValue: ticketSize
        });
        vm.prank(relayer);
        relayerEscrow.commitOnBehalf(user, address(market), auth1, _signAuth(leaf1, auth1.nonce, auth1.expiry));
        assertEq(market.nextTicketId(), 2);
    }

    function testCommitEmitsAndTracksEscrowAndRake() external {
        bytes32 leaf = _leaf(0, 0, ticketSize, bytes32("salt"), user);
        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: leaf,
            user: user,
            nonce: 1,
            expiry: block.timestamp + 12 hours,
            ticketValue: ticketSize
        });
        bytes memory sig = _signAuth(leaf, auth.nonce, auth.expiry);

        uint256 expectedRake = (ticketSize * rakeBps) / 10_000;
        uint256 net = ticketSize - expectedRake;
        vm.expectEmit(true, false, false, true, address(market));
        emit RevealMarket.Committed(0, leaf, net);
        vm.prank(relayer);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
        assertEq(market.totalEscrow(), net, "totalEscrow");
        assertEq(market.rakeCollected(), expectedRake, "rakeCollected");
    }

    function testCommitRevertsOnWrongTicketSize() external {
        bytes32 leaf = _leaf(0, 0, ticketSize + 1, bytes32("salt"), user);
        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: leaf,
            user: user,
            nonce: 1,
            expiry: block.timestamp + 12 hours,
            ticketValue: ticketSize + 1
        });
        bytes memory sig = _signAuth(leaf, auth.nonce, auth.expiry);

        vm.prank(relayer);
        vm.expectRevert(RevealMarket.InvalidPayment.selector);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
    }

    function testCommitRevertsOnNonceReplay() external {
        bytes32 leaf = _leaf(0, 0, ticketSize, bytes32("salt"), user);
        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: leaf,
            user: user,
            nonce: 123,
            expiry: block.timestamp + 12 hours,
            ticketValue: ticketSize
        });
        bytes memory sig = _signAuth(leaf, auth.nonce, auth.expiry);
        vm.prank(relayer);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);

        vm.prank(relayer);
        vm.expectRevert(RevealMarket.CommitReplay.selector);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
    }

    function testCommitRevertsOnExpiry() external {
        bytes32 leaf = _leaf(0, 0, ticketSize, bytes32("salt"), user);
        uint256 pastExpiry = block.timestamp - 1;
        IRevealMarket.CommitAuth memory auth = _buildAuth(leaf, 1, pastExpiry, user);
        bytes memory sig = _signAuth(leaf, auth.nonce, auth.expiry);

        vm.prank(relayer);
        vm.expectRevert(RevealMarket.CommitExpired.selector);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
    }

    function testCommitWindowClosed() external {
        vm.warp(commitDeadline + 1);
        bytes32 leaf = _leaf(0, 0, ticketSize, bytes32("salt"), user);
        IRevealMarket.CommitAuth memory auth = _buildAuth(leaf, 1, block.timestamp + 12 hours, user);
        bytes memory sig = _signAuth(leaf, auth.nonce, auth.expiry);

        vm.prank(relayer);
        vm.expectRevert(RevealMarket.CommitWindowClosed.selector);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
    }

    function testCommitRevertsAtMaxCommitments() external {
        for (uint256 i = 0; i < maxCommitments; i++) {
            bytes32 leaf = _leaf(i, 0, ticketSize, bytes32("salt"), user);
            IRevealMarket.CommitAuth memory auth = _buildAuth(leaf, i + 1, block.timestamp + 12 hours, user);
            vm.prank(relayer);
            relayerEscrow.commitOnBehalf(user, address(market), auth, _signAuth(leaf, auth.nonce, auth.expiry));
        }
        bytes32 overflowLeaf = _leaf(99, 0, ticketSize, bytes32("salt"), user);
        IRevealMarket.CommitAuth memory overflowAuth = _buildAuth(overflowLeaf, 999, block.timestamp + 12 hours, user);
        vm.prank(relayer);
        vm.expectRevert(RevealMarket.MaxCommitmentsReached.selector);
        relayerEscrow.commitOnBehalf(
            user, address(market), overflowAuth, _signAuth(overflowLeaf, overflowAuth.nonce, overflowAuth.expiry)
        );
    }

    function testPoseidonLeafMatchesHarness() external {
        RevealMarketHarness harness = new RevealMarketHarness();
        bytes32 salt = bytes32(uint256(123));
        bytes32 expected = _poseidonLeaf(7, 1, ticketSize, salt, user);
        bytes32 actual = harness.computeLeaf(7, 1, ticketSize, salt, user);
        assertEq(actual, expected, "poseidon leaf mismatch");
    }

    function testCommitRevertsWhenSignatureUsesDifferentUser() external {
        bytes32 leaf = _leaf(0, 1, ticketSize, bytes32("salt-user"), user);
        IRevealMarket.CommitAuth memory auth = _buildAuth(leaf, 11, block.timestamp + 12 hours, user);
        address impostor = makeAddr("impostor");
        bytes memory sig = _signAuth(auth, impostor, block.chainid, authKey);

        vm.prank(relayer);
        vm.expectRevert(RevealMarket.InvalidSignature.selector);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
    }

    function testCommitRevertsWhenSignatureChainIdMismatch() external {
        bytes32 leaf = _leaf(0, 1, ticketSize, bytes32("salt-chain"), user);
        IRevealMarket.CommitAuth memory auth = _buildAuth(leaf, 12, block.timestamp + 12 hours, user);
        bytes memory sig = _signAuth(auth, user, block.chainid + 1, authKey);

        vm.prank(relayer);
        vm.expectRevert(RevealMarket.InvalidSignature.selector);
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

        bytes32 leaf = _leaf(0, 1, ticketSize, bytes32("salt-replay"), user);
        IRevealMarket.CommitAuth memory auth = _buildAuth(leaf, 21, block.timestamp + 12 hours, user);
        bytes memory sig = _signAuth(auth, user, block.chainid, authKey);

        vm.prank(relayer);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);

        vm.prank(relayer);
        vm.expectRevert(RevealMarket.InvalidSignature.selector);
        relayerEscrow.commitOnBehalf(user, address(market2), auth, sig);
    }
}

contract RevealMarketHarness is RevealMarket {
    function computeLeaf(uint256 ticketId, uint256 outcomeId, uint256 amount, bytes32 salt, address user)
        external
        pure
        returns (bytes32)
    {
        return _computeLeaf(ticketId, outcomeId, amount, salt, user);
    }
}
