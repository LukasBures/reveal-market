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

    uint256 private relayerKey = 0xBEEF;
    address private relayer = vm.addr(relayerKey);
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

    function testVerifyAndSettleBatchedRejectsDuplicateBatchIndex() external {
        _commitTickets(2);
        vm.warp(commitDeadline + 1);

        bytes32[] memory leaves = new bytes32[](2);
        leaves[0] = _poseidonLeaf(0, 0, _netTicket(), _netTicket(), bytes32(uint256(1)), user);
        leaves[1] = _poseidonLeaf(1, 0, _netTicket(), _netTicket(), bytes32(uint256(2)), user);
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = _buildBatchRoot(leaves, 2);
        uint16[] memory counts = new uint16[](1);
        counts[0] = 2;
        bytes memory relayerSig = _signRelayer(roots, counts);
        vm.prank(oracle);
        market.lockBatches(roots, counts, relayerSig);
        vm.prank(oracle);
        market.postResult(0);

        bytes[] memory proofs = new bytes[](2);
        proofs[0] = "";
        proofs[1] = "";
        uint256[10][] memory signals = new uint256[10][](2);
        signals[0] = _signals(roots[0], 0, _netTicket() * 2, _netTicket() * 2);
        signals[1] = _signals(roots[0], 0, _netTicket() * 2, _netTicket() * 2);
        uint16[] memory batchIndexes = new uint16[](2);
        batchIndexes[0] = 0;
        batchIndexes[1] = 0;

        vm.expectRevert(RevealMarket.BatchAlreadyVerified.selector);
        vm.prank(oracle);
        market.verifyAndSettleBatched(proofs, signals, batchIndexes);
    }

    function testVerifyAndSettleBatchedRejectsMissingBatchProof() external {
        _commitTickets(1);
        vm.warp(commitDeadline + 1);

        bytes32[] memory roots = new bytes32[](1);
        roots[0] =
            _buildBatchRoot(_wrapLeaf(_poseidonLeaf(0, 0, _netTicket(), _netTicket(), bytes32(uint256(1)), user)), 1);
        uint16[] memory counts = new uint16[](1);
        counts[0] = 1;
        bytes memory relayerSig = _signRelayer(roots, counts);
        vm.prank(oracle);
        market.lockBatches(roots, counts, relayerSig);
        vm.prank(oracle);
        market.postResult(0);

        bytes[] memory proofs = new bytes[](0);
        uint256[10][] memory signals = new uint256[10][](0);
        uint16[] memory batchIndexes = new uint16[](0);
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
        bytes memory relayerSig = _signRelayer(roots, counts);
        vm.prank(oracle);
        market.lockBatches(roots, counts, relayerSig);
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
        bytes memory relayerSig = _signRelayer(roots, counts);
        vm.prank(oracle);
        market.lockBatches(roots, counts, relayerSig);
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
        bytes memory relayerSig = _signRelayer(roots, counts);
        vm.prank(oracle);
        market.lockBatches(roots, counts, relayerSig);
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
        bytes memory relayerSig = _signRelayer(roots, counts);
        vm.prank(oracle);
        market.lockBatches(roots, counts, relayerSig);
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

    function testRefreshAfterPartialBatchedSettlementCannotResetProgress() external {
        if (_isCoverage()) {
            return;
        }

        (bytes32[] memory roots, uint16[] memory counts, uint256 netTicket, uint256 batchSize) =
            _lockTwoBatchesAndPostResult();

        _verifySingleBatch(roots[0], 0, netTicket * batchSize, netTicket * batchSize);
        assertEq(market.settledBatchCount(), 1, "first batch accepted");

        verifier.setVerifyingKeyHash(keccak256("rotated-key"));
        bytes[] memory stalledProofs = new bytes[](1);
        stalledProofs[0] = "";
        uint256[10][] memory stalledSignals = new uint256[10][](1);
        stalledSignals[0] = _signals(roots[1], 0, netTicket, netTicket);
        uint16[] memory stalledIndexes = new uint16[](1);
        stalledIndexes[0] = 1;
        vm.expectRevert(RevealMarket.VerifierNotApproved.selector);
        vm.prank(oracle);
        market.verifyAndSettleBatched(stalledProofs, stalledSignals, stalledIndexes);

        vm.expectRevert(MarketFactory.VerifierDrift.selector);
        factory.setVerifierApproval(address(verifier), true);
        vm.expectRevert(MarketFactory.VerifierDrift.selector);
        factory.refreshMarketLockedVerifierKey(address(market));

        assertEq(market.settledBatchCount(), 1, "progress unchanged");
        assertTrue(market.batchProofVerified(0), "batch 0 remains verified");
        assertFalse(market.batchProofVerified(1), "batch 1 not verified");

        assertEq(counts[0], _toUint16(batchSize), "batch size unchanged");
        assertEq(roots.length, 2, "batch roots unchanged");
    }

    function testEnableRefundsAfterPartialBatchedSettlementTimeout() external {
        if (_isCoverage()) {
            return;
        }

        (bytes32[] memory roots,, uint256 netTicket, uint256 batchSize) = _lockTwoBatchesAndPostResult();
        _verifySingleBatch(roots[0], 0, netTicket * batchSize, netTicket * batchSize);
        assertEq(market.settledBatchCount(), 1, "partial progress");

        vm.expectRevert(RevealMarket.RefundsUnavailable.selector);
        factory.enableMarketRefunds(address(market));

        vm.warp(block.timestamp + market.SETTLEMENT_TIMEOUT_SECONDS());
        factory.enableMarketRefunds(address(market));
        assertEq(uint8(market.phase()), uint8(IRevealMarket.Phase.Cancelled), "fallback to cancelled");
    }

    function _lockTwoBatchesAndPostResult()
        internal
        returns (bytes32[] memory roots, uint16[] memory counts, uint256 netTicket, uint256 batchSize)
    {
        batchSize = BATCH_SIZE;
        bytes32[] memory batch0Leaves;
        bytes32[] memory batch1Leaves;
        (batch0Leaves, batch1Leaves, netTicket) = _commitTwoBatchTickets();
        vm.warp(commitDeadline + 1);

        roots = new bytes32[](2);
        roots[0] = _buildBatchRoot(batch0Leaves, batchSize);
        roots[1] = _buildBatchRoot(batch1Leaves, 1);
        counts = new uint16[](2);
        counts[0] = _toUint16(batchSize);
        counts[1] = 1;
        bytes memory relayerSig = _signRelayer(roots, counts);

        vm.prank(oracle);
        market.lockBatches(roots, counts, relayerSig);
        vm.prank(oracle);
        market.postResult(0);
    }

    function _commitTwoBatchTickets()
        internal
        returns (bytes32[] memory batch0Leaves, bytes32[] memory batch1Leaves, uint256 netTicket)
    {
        uint256 totalTickets = BATCH_SIZE + 1;
        netTicket = _netTicket();
        token.mint(user, totalTickets * ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), totalTickets * ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(totalTickets * ticketSize);

        batch0Leaves = new bytes32[](BATCH_SIZE);
        batch1Leaves = new bytes32[](1);
        for (uint256 i = 0; i < totalTickets; ++i) {
            bytes32 leaf = _poseidonLeaf(i, 0, netTicket, netTicket, bytes32(i + 1), user);
            if (i < BATCH_SIZE) {
                batch0Leaves[i] = leaf;
            } else {
                batch1Leaves[0] = leaf;
            }

            IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
                commitment: leaf,
                ticketId: i,
                user: user,
                nonce: i + 1,
                expiry: block.timestamp + 12 hours,
                ticketValue: ticketSize
            });
            bytes memory sig = _signAuth(auth, authKey);
            vm.prank(user);
            relayerEscrow.approveCommitAuthorization(address(market), auth);
            vm.prank(relayer);
            relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
        }
    }

    function _verifySingleBatch(bytes32 root, uint16 batchIndex, uint256 totalEscrow_, uint256 totalLiability_)
        internal
    {
        bytes[] memory proofs = new bytes[](1);
        proofs[0] = "";
        uint256[10][] memory signals = new uint256[10][](1);
        signals[0] = _signals(root, 0, totalEscrow_, totalLiability_);
        uint16[] memory batchIndexes = new uint16[](1);
        batchIndexes[0] = batchIndex;
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
                ticketId: i,
                user: user,
                nonce: i + 1,
                expiry: block.timestamp + 12 hours,
                ticketValue: ticketSize
            });
            bytes memory sig = _signAuth(auth, authKey);
            vm.prank(user);
            relayerEscrow.approveCommitAuthorization(address(market), auth);
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

    function _wrapLeaf(bytes32 leaf) private pure returns (bytes32[] memory leaves) {
        leaves = new bytes32[](1);
        leaves[0] = leaf;
    }

    function _toUint16(uint256 value) private pure returns (uint16) {
        require(value <= type(uint16).max, "uint16 overflow");
        // casting to uint16 is safe because we guard the upper bound above
        // forge-lint: disable-next-line(unsafe-typecast)
        return uint16(value);
    }

    function _isCoverage() private view returns (bool) {
        return vm.envOr("RM_COVERAGE", false);
    }
}
