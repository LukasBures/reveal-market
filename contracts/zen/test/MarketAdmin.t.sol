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

contract MarketAdminTest is Test {
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
    uint256 private commitDeadline;
    uint256 private revealDeadline;

    function setUp() external {
        token = new MockERC20();
        relayerEscrow = new RelayerEscrow(relayerOwner, IERC20(address(token)));
        protocolPool = new ProtocolPool(address(this), IERC20(address(token)));
        verifier = new MockVerifier(circuitHash);
        implementation = new RevealMarket();
        factory = new MarketFactory(address(implementation), protocolPool, relayerEscrow, address(token), address(this));

        protocolPool.setMarketFactory(address(factory));
        vm.prank(relayerOwner);
        relayerEscrow.setMarketFactory(address(factory));

        commitDeadline = block.timestamp + 1 days;
        revealDeadline = commitDeadline + 1 days;

        MarketFactory.CreateMarketParams memory params = MarketFactory.CreateMarketParams({
            oracle: oracle,
            verifier: address(verifier),
            circuitHash: circuitHash,
            commitDeadline: commitDeadline,
            revealDeadline: revealDeadline,
            fixedTicketSize: ticketSize,
            maxCommitments: maxCommitments,
            authorizationSigner: authSigner,
            protocolLiabilityCap: protocolCap
        });

        market = RevealMarket(payable(factory.createMarket(params)));
    }

    function testAuthorizationSignerRotationDuringCommit() external {
        uint256 newKey = 0xBEEF;
        address newSigner = vm.addr(newKey);
        vm.prank(address(this));
        factory.updateAuthorizationSigner(address(market), newSigner);
        assertEq(market.authorizationSigner(), newSigner, "signer rotated");

        IRevealMarket.CommitAuth memory auth =
            IRevealMarket.CommitAuth({commitment: keccak256("leaf"), nonce: 1, expiry: block.timestamp + 4 hours});

        token.mint(user, ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(ticketSize);

        bytes memory badSig = _signAuth(auth, authKey);
        vm.expectRevert(RelayerEscrow.CommitFailed.selector);
        vm.prank(relayerOwner);
        relayerEscrow.commitOnBehalf(user, address(market), auth, badSig);

        bytes memory goodSig = _signAuth(auth, newKey);
        vm.prank(relayerOwner);
        relayerEscrow.commitOnBehalf(user, address(market), auth, goodSig);
        assertEq(market.totalEscrow(), ticketSize - (ticketSize * market.rakeBps()) / 10_000, "commit succeeded");
    }

    function testOracleRotation() external {
        IRevealMarket.CommitAuth memory auth =
            IRevealMarket.CommitAuth({commitment: keccak256("leaf2"), nonce: 2, expiry: block.timestamp + 4 hours});
        token.mint(user, ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(ticketSize);
        bytes memory sig = _signAuth(auth, authKey);
        vm.prank(relayerOwner);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);

        address newOracle = makeAddr("newOracle");
        vm.prank(address(this));
        factory.updateOracle(address(market), newOracle);
        assertEq(market.oracle(), newOracle);

        vm.warp(commitDeadline + 1);
        vm.prank(oracle);
        vm.expectRevert(RevealMarket.NotOracle.selector);
        market.lock();

        vm.prank(newOracle);
        market.lock();
    }

    function testRelayerRotationAllowsNewRelayer() external {
        RelayerEscrow newRelayer = new RelayerEscrow(makeAddr("newRelayerOwner"), IERC20(address(token)));
        vm.prank(newRelayer.owner());
        newRelayer.setMarketFactory(address(factory));

        vm.prank(address(this));
        factory.updateMarketRelayer(address(market), newRelayer);
        assertEq(market.relayerEscrow(), address(newRelayer));

        IRevealMarket.CommitAuth memory auth =
            IRevealMarket.CommitAuth({commitment: keccak256("leaf3"), nonce: 3, expiry: block.timestamp + 4 hours});
        token.mint(user, ticketSize);
        vm.prank(user);
        token.approve(address(newRelayer), ticketSize);
        vm.prank(user);
        newRelayer.deposit(ticketSize);
        bytes memory sig = _signAuth(auth, authKey);

        vm.prank(newRelayer.owner());
        newRelayer.commitOnBehalf(user, address(market), auth, sig);
        assertEq(market.totalEscrow(), ticketSize - (ticketSize * market.rakeBps()) / 10_000);

        vm.expectRevert(RevealMarket.NotRelayer.selector);
        vm.prank(makeAddr("stranger"));
        market.commitWithAuthorization(auth, sig);
    }

    function testProtocolLiabilityCapUpdateStopsAfterSettlement() external {
        uint256 newCap = 5 ether;
        vm.prank(address(this));
        factory.updateProtocolLiabilityCap(address(market), newCap);
        assertEq(market.protocolLiabilityCap(), newCap);
        assertEq(protocolPool.liabilityCap(address(market)), newCap);

        IRevealMarket.CommitAuth memory auth =
            IRevealMarket.CommitAuth({commitment: keccak256("leaf4"), nonce: 4, expiry: block.timestamp + 4 hours});
        token.mint(user, ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(ticketSize);
        bytes memory sig = _signAuth(auth, authKey);
        vm.prank(relayerOwner);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);

        vm.warp(commitDeadline + 1);
        vm.prank(oracle);
        market.lock();
        vm.prank(oracle);
        market.postResult(1);

        uint256 netTicket = ticketSize - (ticketSize * market.rakeBps()) / 10_000;
        uint256[10] memory signals = [
            uint256(market.commitmentsRoot()),
            uint256(1),
            uint256(1),
            netTicket,
            netTicket,
            market.rakeBps(),
            netTicket,
            uint256(0),
            uint256(circuitHash),
            uint256(0)
        ];

        vm.prank(oracle);
        market.verifyAndSettle("", signals);

        vm.prank(address(this));
        vm.expectRevert(RevealMarket.InvalidPhase.selector);
        factory.updateProtocolLiabilityCap(address(market), newCap + 1);
    }

    function _signAuth(IRevealMarket.CommitAuth memory auth, uint256 privKey) private view returns (bytes memory) {
        bytes32 digest = MessageHashUtils.toEthSignedMessageHash(
            keccak256(abi.encode(address(market), market.marketId(), auth.commitment, auth.nonce, auth.expiry))
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(privKey, digest);
        return abi.encodePacked(r, s, v);
    }
}
