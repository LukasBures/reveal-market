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

contract RevealMarketBatchInvariantTest is Test, PoseidonTestUtils {
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

    function testFuzzBatchCountsMatchCommitments(uint8 commitCountRaw) external {
        uint256 commitCount = bound(uint256(commitCountRaw), 1, 32);
        uint256 netTicket = _netTicket();

        token.mint(user, commitCount * ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), commitCount * ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(commitCount * ticketSize);

        bytes32[] memory leaves = new bytes32[](commitCount);
        for (uint256 i = 0; i < commitCount; i++) {
            bytes32 leaf = _poseidonLeaf(i, 0, netTicket, netTicket, bytes32(i + 1), user);
            leaves[i] = leaf;
            IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
                commitment: leaf,
                user: user,
                nonce: i + 1,
                expiry: block.timestamp + 12 hours,
                ticketValue: ticketSize
            });
            bytes memory sig = _signAuth(auth, authKey);
            vm.prank(relayerOwner);
            relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
        }

        vm.warp(commitDeadline + 1);
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = _buildBatchRoot(leaves, commitCount);
        uint16[] memory counts = new uint16[](1);
        counts[0] = uint16(commitCount);

        vm.prank(oracle);
        market.lockBatches(roots, counts, "");

        assertEq(market.batchCounts(0), uint16(commitCount), "batchCount");
        assertEq(market.nextTicketId(), commitCount, "commitments length");
    }

    function _netTicket() internal view returns (uint256) {
        return ticketSize - (ticketSize * rakeBps) / 10_000;
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
