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

contract RevealMarketBatchedSettlementGuardsTest is Test, PoseidonTestUtils {
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

    function testVerifyAndSettleBatchedRejectsDuplicateBatchIndex() external {
        _commitTickets(2);
        vm.warp(commitDeadline + 1);

        bytes32[] memory roots = new bytes32[](2);
        roots[0] = _buildBatchRoot(_wrapLeaf(_poseidonLeaf(0, 0, _netTicket(), _netTicket(), _salt("a"), user)), 1);
        roots[1] = _buildBatchRoot(_wrapLeaf(_poseidonLeaf(1, 0, _netTicket(), _netTicket(), _salt("b"), user)), 1);
        uint16[] memory counts = new uint16[](2);
        counts[0] = 1;
        counts[1] = 1;
        vm.prank(oracle);
        market.lockBatches(roots, counts, "");
        vm.prank(oracle);
        market.postResult(0);

        bytes[] memory proofs = new bytes[](2);
        proofs[0] = "";
        proofs[1] = "";
        uint256[10][] memory signals = new uint256[10][](2);
        signals[0] = _signals(roots[0], 0, _netTicket(), _netTicket());
        signals[1] = _signals(roots[1], 0, _netTicket(), _netTicket());
        uint16[] memory batchIndexes = new uint16[](2);
        batchIndexes[0] = 0;
        batchIndexes[1] = 0;

        vm.expectRevert(RevealMarket.InvalidBatchIndex.selector);
        vm.prank(oracle);
        market.verifyAndSettleBatched(proofs, signals, batchIndexes);
    }

    function testVerifyAndSettleBatchedRejectsMissingBatchProof() external {
        _commitTickets(2);
        vm.warp(commitDeadline + 1);

        bytes32[] memory roots = new bytes32[](2);
        roots[0] = _buildBatchRoot(_wrapLeaf(_poseidonLeaf(0, 0, _netTicket(), _netTicket(), _salt("a"), user)), 1);
        roots[1] = _buildBatchRoot(_wrapLeaf(_poseidonLeaf(1, 0, _netTicket(), _netTicket(), _salt("b"), user)), 1);
        uint16[] memory counts = new uint16[](2);
        counts[0] = 1;
        counts[1] = 1;
        vm.prank(oracle);
        market.lockBatches(roots, counts, "");
        vm.prank(oracle);
        market.postResult(0);

        bytes[] memory proofs = new bytes[](1);
        proofs[0] = "";
        uint256[10][] memory signals = new uint256[10][](1);
        signals[0] = _signals(roots[0], 0, _netTicket(), _netTicket());
        uint16[] memory batchIndexes = new uint16[](1);
        batchIndexes[0] = 0;

        vm.expectRevert(RevealMarket.BatchProofLengthMismatch.selector);
        vm.prank(oracle);
        market.verifyAndSettleBatched(proofs, signals, batchIndexes);
    }

    function testVerifyAndSettleBatchedRejectsCircuitHashMismatch() external {
        _commitTickets(1);
        vm.warp(commitDeadline + 1);

        bytes32[] memory roots = new bytes32[](1);
        roots[0] = _buildBatchRoot(_wrapLeaf(_poseidonLeaf(0, 0, _netTicket(), _netTicket(), _salt("a"), user)), 1);
        uint16[] memory counts = new uint16[](1);
        counts[0] = 1;
        vm.prank(oracle);
        market.lockBatches(roots, counts, "");
        vm.prank(oracle);
        market.postResult(0);

        bytes[] memory proofs = new bytes[](1);
        proofs[0] = "";
        uint256[10][] memory signals = new uint256[10][](1);
        signals[0] = _signals(roots[0], 0, _netTicket(), _netTicket());
        signals[0][8] = uint256(keccak256("bad-circuit"));
        uint16[] memory batchIndexes = new uint16[](1);
        batchIndexes[0] = 0;

        vm.expectRevert(RevealMarket.CircuitHashMismatch.selector);
        vm.prank(oracle);
        market.verifyAndSettleBatched(proofs, signals, batchIndexes);
    }

    function testVerifyAndSettleBatchedRejectsTotalsMismatch() external {
        _commitTickets(1);
        vm.warp(commitDeadline + 1);

        bytes32[] memory roots = new bytes32[](1);
        roots[0] = _buildBatchRoot(_wrapLeaf(_poseidonLeaf(0, 0, _netTicket(), _netTicket(), _salt("a"), user)), 1);
        uint16[] memory counts = new uint16[](1);
        counts[0] = 1;
        vm.prank(oracle);
        market.lockBatches(roots, counts, "");
        vm.prank(oracle);
        market.postResult(0);

        bytes[] memory proofs = new bytes[](1);
        proofs[0] = "";
        uint256[10][] memory signals = new uint256[10][](1);
        signals[0] = _signals(roots[0], 0, _netTicket() + 1, _netTicket());
        uint16[] memory batchIndexes = new uint16[](1);
        batchIndexes[0] = 0;

        vm.expectRevert(RevealMarket.TotalsMismatch.selector);
        vm.prank(oracle);
        market.verifyAndSettleBatched(proofs, signals, batchIndexes);
    }

    function testVerifyAndSettleBatchedRejectsRakeMismatch() external {
        _commitTickets(1);
        vm.warp(commitDeadline + 1);

        bytes32[] memory roots = new bytes32[](1);
        roots[0] = _buildBatchRoot(_wrapLeaf(_poseidonLeaf(0, 0, _netTicket(), _netTicket(), _salt("a"), user)), 1);
        uint16[] memory counts = new uint16[](1);
        counts[0] = 1;
        vm.prank(oracle);
        market.lockBatches(roots, counts, "");
        vm.prank(oracle);
        market.postResult(0);

        bytes[] memory proofs = new bytes[](1);
        proofs[0] = "";
        uint256[10][] memory signals = new uint256[10][](1);
        signals[0] = _signals(roots[0], 0, _netTicket(), _netTicket());
        signals[0][5] = signals[0][5] + 1;
        uint16[] memory batchIndexes = new uint16[](1);
        batchIndexes[0] = 0;

        vm.expectRevert(RevealMarket.RakeMismatch.selector);
        vm.prank(oracle);
        market.verifyAndSettleBatched(proofs, signals, batchIndexes);
    }

    function testVerifyAndSettleBatchedRejectsInvalidProof() external {
        _commitTickets(1);
        vm.warp(commitDeadline + 1);

        bytes32[] memory roots = new bytes32[](1);
        roots[0] = _buildBatchRoot(_wrapLeaf(_poseidonLeaf(0, 0, _netTicket(), _netTicket(), _salt("a"), user)), 1);
        uint16[] memory counts = new uint16[](1);
        counts[0] = 1;
        vm.prank(oracle);
        market.lockBatches(roots, counts, "");
        vm.prank(oracle);
        market.postResult(0);

        verifier.setShouldVerify(false);

        bytes[] memory proofs = new bytes[](1);
        proofs[0] = "";
        uint256[10][] memory signals = new uint256[10][](1);
        signals[0] = _signals(roots[0], 0, _netTicket(), _netTicket());
        uint16[] memory batchIndexes = new uint16[](1);
        batchIndexes[0] = 0;

        vm.expectRevert(RevealMarket.InvalidProof.selector);
        vm.prank(oracle);
        market.verifyAndSettleBatched(proofs, signals, batchIndexes);
    }

    function _commitTickets(uint256 count) internal {
        uint256 netAmount = _netTicket();
        token.mint(user, count * ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), count * ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(count * ticketSize);

        for (uint256 i = 0; i < count; i++) {
            bytes32 leaf = _poseidonLeaf(i, 0, netAmount, netAmount, bytes32(i + 1), user);
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
    }

    function _netTicket() internal view returns (uint256) {
        return ticketSize - (ticketSize * market.rakeBps()) / 10_000;
    }

    function _signals(bytes32 root, uint256 outcome, uint256 totalEscrow_, uint256 totalLiability_)
        internal
        view
        returns (uint256[10] memory signals)
    {
        uint256 poolYes = outcome == 0 ? totalEscrow_ : 0;
        uint256 poolNo = outcome == 1 ? totalEscrow_ : 0;
        signals = [
            uint256(root),
            market.marketId(),
            outcome,
            totalEscrow_,
            totalLiability_,
            market.rakeBps(),
            poolYes,
            poolNo,
            uint256(circuitHash),
            uint256(0)
        ];
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

    function _wrapLeaf(bytes32 leaf) private pure returns (bytes32[] memory leaves) {
        leaves = new bytes32[](1);
        leaves[0] = leaf;
    }
}
