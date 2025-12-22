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

contract RevealMarketBatchedSettlementTest is Test, PoseidonTestUtils {
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
    uint256 private ticketSize = 1 ether;
    uint256 private protocolCap = 1000 ether;
    uint256 private rakeBps = 100; // 1%
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
            maxCommitments: 0,
            authorizationSigner: authSigner,
            protocolLiabilityCap: protocolCap
        });

        market = RevealMarket(payable(factory.createMarket(params)));
    }

    function testVerifyAndSettleBatchedSumsTotals() external {
        uint256 totalTickets = BATCH_SIZE + 1;
        uint256 netTicket = ticketSize - (ticketSize * rakeBps) / 10_000;

        token.mint(user, totalTickets * ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), totalTickets * ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(totalTickets * ticketSize);

        bytes32[] memory batch0Leaves = new bytes32[](BATCH_SIZE);
        bytes32[] memory batch1Leaves = new bytes32[](1);

        for (uint256 i = 0; i < totalTickets; i++) {
            uint256 outcome = i < BATCH_SIZE ? 0 : 1;
            bytes32 leaf = _poseidonLeaf(i, outcome, netTicket, bytes32(i + 1), user);
            if (i < BATCH_SIZE) {
                batch0Leaves[i] = leaf;
            } else {
                batch1Leaves[0] = leaf;
            }
            IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
                commitment: leaf,
                user: user,
                nonce: i + 1,
                expiry: block.timestamp + 12 hours,
                ticketValue: ticketSize
            });
            bytes memory sig = _signAuth(auth, authKey);
            vm.prank(relayer);
            relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
        }

        vm.warp(commitDeadline + 1);
        bytes32 root0 = _buildBatchRoot(batch0Leaves, BATCH_SIZE);
        bytes32 root1 = _buildBatchRoot(batch1Leaves, 1);
        bytes32[] memory roots = new bytes32[](2);
        roots[0] = root0;
        roots[1] = root1;
        uint16[] memory counts = new uint16[](2);
        counts[0] = uint16(BATCH_SIZE);
        counts[1] = 1;

        vm.prank(oracle);
        market.lockBatches(roots, counts, "");
        vm.prank(oracle);
        market.postResult(0);

        uint256 poolYes0 = netTicket * BATCH_SIZE;
        uint256 poolNo0 = 0;
        uint256 poolYes1 = 0;
        uint256 poolNo1 = netTicket;

        bytes[] memory proofs = new bytes[](2);
        proofs[0] = "";
        proofs[1] = "";

        uint256[10][] memory signals = new uint256[10][](2);
        signals[0] = [
            uint256(root1),
            market.marketId(),
            uint256(0),
            poolYes1 + poolNo1,
            poolYes1,
            rakeBps,
            poolYes1,
            poolNo1,
            uint256(circuitHash),
            uint256(0)
        ];
        signals[1] = [
            uint256(root0),
            market.marketId(),
            uint256(0),
            poolYes0 + poolNo0,
            poolYes0,
            rakeBps,
            poolYes0,
            poolNo0,
            uint256(circuitHash),
            uint256(0)
        ];

        uint16[] memory batchIndexes = new uint16[](2);
        batchIndexes[0] = 1;
        batchIndexes[1] = 0;

        vm.prank(oracle);
        market.verifyAndSettleBatched(proofs, signals, batchIndexes);

        assertEq(market.totalEscrow(), netTicket * totalTickets, "totalEscrow matches");
        assertEq(market.totalLiability(), poolYes0, "totalLiability matches winning pool");
        assertEq(market.poolTotalYes(), poolYes0, "poolYes matches");
        assertEq(market.poolTotalNo(), poolNo1, "poolNo matches");
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
}
