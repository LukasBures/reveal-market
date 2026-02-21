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

contract RevealMarketBatchedSettlementFuzzTest is Test, PoseidonTestUtils {
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
        factory.setVerifierApproval(address(verifier), true);

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

        token.mint(address(this), 2_000 ether);
        token.approve(address(protocolPool), 2_000 ether);
        protocolPool.deposit(2_000 ether);
    }

    function testFuzzBatchedSettlementTotals(uint8 batchCountRaw, uint8 lastBatchSizeRaw) external {
        uint256 batchCount = bound(uint256(batchCountRaw), 1, 2);
        uint256 lastBatchSize = bound(uint256(lastBatchSizeRaw), 1, 10);
        uint256 totalTickets = (batchCount - 1) * BATCH_SIZE + lastBatchSize;
        uint256 netTicket = _netTicket();

        token.mint(user, totalTickets * ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), totalTickets * ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(totalTickets * ticketSize);

        bytes32[][] memory batchLeaves = new bytes32[][](batchCount);
        uint256 ticketId = 0;
        for (uint256 batchIndex = 0; batchIndex < batchCount; batchIndex++) {
            uint256 batchSize = batchIndex == batchCount - 1 ? lastBatchSize : BATCH_SIZE;
            batchLeaves[batchIndex] = new bytes32[](batchSize);
            for (uint256 i = 0; i < batchSize; i++) {
                bytes32 leaf = _poseidonLeaf(ticketId, 0, netTicket, netTicket, bytes32(ticketId + 1), user);
                batchLeaves[batchIndex][i] = leaf;
                IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
                    commitment: leaf,
                    ticketId: ticketId,
                    user: user,
                    nonce: ticketId + 1,
                    expiry: block.timestamp + 12 hours,
                    ticketValue: ticketSize
                });
                bytes memory sig = _signAuth(auth, authKey);
                vm.prank(user);
                relayerEscrow.approveCommitAuthorization(address(market), auth);
                vm.prank(relayerOwner);
                relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
                ticketId++;
            }
        }

        vm.warp(commitDeadline + 1);
        bytes32[] memory roots = new bytes32[](batchCount);
        uint16[] memory counts = new uint16[](batchCount);
        for (uint256 i = 0; i < batchCount; i++) {
            roots[i] = _buildBatchRoot(batchLeaves[i], batchLeaves[i].length);
            counts[i] = _toUint16(batchLeaves[i].length);
        }
        bytes memory relayerSig = _signRelayer(roots, counts);

        vm.prank(oracle);
        market.lockBatches(roots, counts, relayerSig);
        vm.prank(oracle);
        market.postResult(0);

        bytes[] memory proofs = new bytes[](batchCount);
        uint256[10][] memory signals = new uint256[10][](batchCount);
        uint16[] memory batchIndexes = new uint16[](batchCount);

        for (uint256 i = 0; i < batchCount; i++) {
            uint256 poolYes = netTicket * uint256(counts[i]);
            signals[i] = [
                uint256(roots[i]),
                market.marketId(),
                uint256(0),
                poolYes,
                poolYes,
                rakeBps,
                poolYes,
                uint256(0),
                uint256(circuitHash),
                uint256(0)
            ];
            proofs[i] = "";
            batchIndexes[i] = _toUint16(i);
        }

        vm.prank(oracle);
        market.verifyAndSettleBatched(proofs, signals, batchIndexes);

        assertEq(market.totalEscrow(), netTicket * totalTickets, "totalEscrow");
        assertEq(market.totalLiability(), netTicket * totalTickets, "totalLiability");
        assertEq(market.poolTotalYes(), netTicket * totalTickets, "poolYes");
        assertEq(market.poolTotalNo(), 0, "poolNo");
    }

    function _netTicket() internal view returns (uint256) {
        return ticketSize - (ticketSize * rakeBps) / 10_000;
    }

    function _toUint16(uint256 value) private pure returns (uint16) {
        require(value <= type(uint16).max, "uint16 overflow");
        // casting to uint16 is safe because we guard the upper bound above
        // forge-lint: disable-next-line(unsafe-typecast)
        return uint16(value);
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
}
