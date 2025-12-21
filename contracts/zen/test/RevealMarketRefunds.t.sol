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

contract RevealMarketRefundsTest is Test {
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
    }

    function testEnableRefundsRequiresCommitDeadline() external {
        vm.prank(relayerOwner);
        vm.expectRevert(RevealMarket.RefundsUnavailable.selector);
        market.enableRefunds();
    }

    function testRefundFlowAfterEnable() external {
        bytes32 salt = keccak256("refund-salt");
        bytes32 leaf = _leaf(0, 1, ticketSize, salt, user);
        _depositAndCommit(leaf, 1);

        vm.warp(commitDeadline + 1);
        vm.prank(relayerOwner);
        market.enableRefunds();

        assertEq(uint8(market.phase()), uint8(IRevealMarket.Phase.Cancelled));
        assertTrue(market.commitsPaused(), "commits paused");
        assertTrue(market.claimsPaused(), "claims paused");

        uint256 netTicket = ticketSize - (ticketSize * rakeBps) / 10_000;
        vm.prank(relayerOwner);
        market.refund(user, 0, 1, ticketSize, salt, new bytes32[](0));
        assertEq(token.balanceOf(user), netTicket, "refund credited");

        vm.prank(relayerOwner);
        vm.expectRevert(RevealMarket.TicketAlreadyClaimed.selector);
        market.refund(user, 0, 1, ticketSize, salt, new bytes32[](0));
    }

    function testRefundRequiresEnable() external {
        bytes32 salt = keccak256("refund-disabled");
        bytes32 leaf = _leaf(0, 1, ticketSize, salt, user);
        _depositAndCommit(leaf, 1);

        vm.prank(relayerOwner);
        vm.expectRevert(RevealMarket.RefundsNotEnabled.selector);
        market.refund(user, 0, 1, ticketSize, salt, new bytes32[](0));
    }

    function testRefundUnauthorized() external {
        bytes32 salt = keccak256("refund-unauth");
        bytes32 leaf = _leaf(0, 1, ticketSize, salt, user);
        _depositAndCommit(leaf, 1);

        vm.warp(commitDeadline + 1);
        market.enableRefunds();

        vm.prank(user);
        vm.expectRevert(RevealMarket.NotAuthorized.selector);
        market.refund(user, 0, 1, ticketSize, salt, new bytes32[](0));
    }

    function _depositAndCommit(bytes32 commitment, uint256 nonce) internal {
        token.mint(user, ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(ticketSize);

        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: commitment,
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

    function _leaf(uint256 ticketId, uint256 outcomeId, uint256 amount, bytes32 salt, address leafUser)
        internal
        pure
        returns (bytes32)
    {
        return keccak256(abi.encodePacked(ticketId, outcomeId, amount, keccak256(abi.encodePacked(leafUser, salt))));
    }
}
