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

contract RevealMarketGuardsTest is Test, PoseidonTestUtils {
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
    uint256 private protocolCap = 3 ether;
    uint256 private maxCommitments = 8;
    uint256 private rakeBps = 200;
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

    function testLockRevertsUseLockBatches() external {
        vm.prank(oracle);
        vm.expectRevert(RevealMarket.UseLockBatches.selector);
        market.lock();
    }

    function testLockBatchesRejectsBeforeDeadline() external {
        (bytes32 leaf,,,) = _commitTicket(1, _salt("before-deadline"));
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = _buildBatchRoot(_wrapLeaf(leaf), 1);
        uint16[] memory counts = new uint16[](1);
        counts[0] = 1;

        vm.expectRevert(RevealMarket.CommitWindowClosed.selector);
        vm.prank(oracle);
        market.lockBatches(roots, counts, "");
    }

    function testLockBatchesRejectsEmptyCommitments() external {
        vm.warp(commitDeadline + 1);
        vm.expectRevert(RevealMarket.NothingToLock.selector);
        vm.prank(oracle);
        market.lockBatches(new bytes32[](0), new uint16[](0), "");
    }

    function testLockBatchesRejectsMismatchedCounts() external {
        (bytes32 leaf,,,) = _commitTicket(1, _salt("mismatch"));
        vm.warp(commitDeadline + 1);
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = _buildBatchRoot(_wrapLeaf(leaf), 1);
        uint16[] memory counts = new uint16[](2);
        counts[0] = 1;
        counts[1] = 0;

        vm.expectRevert(RevealMarket.BatchCountMismatch.selector);
        vm.prank(oracle);
        market.lockBatches(roots, counts, "");
    }

    function testLockBatchesRejectsBatchSizeExceeded() external {
        (bytes32 leaf,,,) = _commitTicket(1, _salt("oversize"));
        vm.warp(commitDeadline + 1);
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = _buildBatchRoot(_wrapLeaf(leaf), 1);
        uint16[] memory counts = new uint16[](1);
        counts[0] = _toUint16(BATCH_SIZE + 1);

        vm.expectRevert(RevealMarket.BatchSizeExceeded.selector);
        vm.prank(oracle);
        market.lockBatches(roots, counts, "");
    }

    function testLockBatchesRejectsTotalMismatch() external {
        (bytes32 leaf,,,) = _commitTicket(1, _salt("total-mismatch"));
        vm.warp(commitDeadline + 1);
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = _buildBatchRoot(_wrapLeaf(leaf), 1);
        uint16[] memory counts = new uint16[](1);
        counts[0] = 2;

        vm.expectRevert(RevealMarket.BatchCountMismatch.selector);
        vm.prank(oracle);
        market.lockBatches(roots, counts, "");
    }

    function testLockBatchesRejectsInvalidRelayerSignature() external {
        (bytes32 leaf,,,) = _commitTicket(1, _salt("bad-sig"));
        vm.warp(commitDeadline + 1);
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = _buildBatchRoot(_wrapLeaf(leaf), 1);
        uint16[] memory counts = new uint16[](1);
        counts[0] = 1;
        bytes memory sig = _signRelayer(roots, counts, 0xBADD);

        vm.expectRevert(RevealMarket.InvalidRelayerSignature.selector);
        vm.prank(oracle);
        market.lockBatches(roots, counts, sig);
    }

    function testLockBatchesAcceptsRelayerSignature() external {
        (bytes32 leaf,,,) = _commitTicket(1, _salt("good-sig"));
        vm.warp(commitDeadline + 1);
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = _buildBatchRoot(_wrapLeaf(leaf), 1);
        uint16[] memory counts = new uint16[](1);
        counts[0] = 1;
        bytes memory sig = _signRelayer(roots, counts, relayerKey);

        vm.prank(oracle);
        market.lockBatches(roots, counts, sig);
        assertEq(uint8(market.phase()), uint8(IRevealMarket.Phase.Locked));
    }

    function testVerifyAndSettleRevertsWithoutResult() external {
        (bytes32 leaf,, uint256 netAmount, uint256 payout) = _commitTicket(1, _salt("no-result"));
        bytes32 root = _lockSingle(leaf, "");
        uint256[10] memory signals = _signals(root, 1, netAmount, payout);

        vm.expectRevert(RevealMarket.ResultMissing.selector);
        vm.prank(oracle);
        market.verifyAndSettle("", signals);
    }

    function testVerifyAndSettleRevertsOnTotalsMismatch() external {
        (bytes32 leaf,, uint256 netAmount, uint256 payout) = _commitTicket(1, _salt("totals"));
        bytes32 root = _lockAndPost(leaf, 1);
        uint256[10] memory signals = _signals(root, 1, netAmount + 1, payout);

        vm.expectRevert(RevealMarket.TotalsMismatch.selector);
        vm.prank(oracle);
        market.verifyAndSettle("", signals);
    }

    function testVerifyAndSettleRevertsOnRakeMismatch() external {
        (bytes32 leaf,, uint256 netAmount, uint256 payout) = _commitTicket(1, _salt("rake"));
        bytes32 root = _lockAndPost(leaf, 1);
        uint256[10] memory signals = _signals(root, 1, netAmount, payout);
        signals[5] = signals[5] + 1;

        vm.expectRevert(RevealMarket.RakeMismatch.selector);
        vm.prank(oracle);
        market.verifyAndSettle("", signals);
    }

    function testVerifyAndSettleRevertsOnCircuitHashMismatch() external {
        (bytes32 leaf,, uint256 netAmount, uint256 payout) = _commitTicket(1, _salt("circuit"));
        bytes32 root = _lockAndPost(leaf, 1);
        uint256[10] memory signals = _signals(root, 1, netAmount, payout);
        signals[8] = uint256(keccak256("bad"));

        vm.expectRevert(RevealMarket.CircuitHashMismatch.selector);
        vm.prank(oracle);
        market.verifyAndSettle("", signals);
    }

    function testVerifyAndSettleRevertsOnPaddingMismatch() external {
        (bytes32 leaf,, uint256 netAmount, uint256 payout) = _commitTicket(1, _salt("padding"));
        bytes32 root = _lockAndPost(leaf, 1);
        uint256[10] memory signals = _signals(root, 1, netAmount, payout);
        signals[9] = 1;

        vm.expectRevert(RevealMarket.PaddingMismatch.selector);
        vm.prank(oracle);
        market.verifyAndSettle("", signals);
    }

    function testVerifyAndSettleRevertsOnInvalidProof() external {
        (bytes32 leaf,, uint256 netAmount, uint256 payout) = _commitTicket(1, _salt("proof"));
        bytes32 root = _lockAndPost(leaf, 1);
        verifier.setShouldVerify(false);
        uint256[10] memory signals = _signals(root, 1, netAmount, payout);

        vm.expectRevert(RevealMarket.InvalidProof.selector);
        vm.prank(oracle);
        market.verifyAndSettle("", signals);
    }

    function testClaimRevertsWrongOutcome() external {
        (bytes32 leaf, bytes32[] memory leaves, uint256 netAmount, uint256 payout) =
            _commitTicket(1, _salt("claim-outcome"));
        bytes32 root = _lockAndPost(leaf, 1);
        uint256[10] memory signals = _signals(root, 1, netAmount, payout);
        vm.prank(oracle);
        market.verifyAndSettle("", signals);

        vm.expectRevert(RevealMarket.WrongOutcome.selector);
        vm.prank(relayerOwner);
        market.claim(user, 0, 0, netAmount, payout, _salt("claim-outcome"), _buildMerkleProof(leaves, 1, 0));
    }

    function testClaimRevertsWhenPaused() external {
        (bytes32 leaf, bytes32[] memory leaves, uint256 netAmount, uint256 payout) =
            _commitTicket(1, _salt("claim-pause"));
        bytes32 root = _lockAndPost(leaf, 1);
        uint256[10] memory signals = _signals(root, 1, netAmount, payout);
        vm.prank(oracle);
        market.verifyAndSettle("", signals);

        vm.prank(address(factory));
        market.setClaimsPaused(true);

        vm.expectRevert(RevealMarket.ClaimsPaused.selector);
        vm.prank(relayerOwner);
        market.claim(user, 0, 1, netAmount, payout, _salt("claim-pause"), _buildMerkleProof(leaves, 1, 0));
    }

    function testEnableRefundsRejectsAfterSettlement() external {
        (bytes32 leaf,, uint256 netAmount, uint256 payout) = _commitTicket(1, _salt("refund-after"));
        bytes32 root = _lockAndPost(leaf, 1);
        uint256[10] memory signals = _signals(root, 1, netAmount, payout);
        vm.prank(oracle);
        market.verifyAndSettle("", signals);

        vm.expectRevert(RevealMarket.InvalidPhase.selector);
        vm.prank(relayerOwner);
        market.enableRefunds();
    }

    function testRefundRevertsInvalidLeaf() external {
        (, , uint256 netAmount, uint256 payout) = _commitTicket(1, _salt("refund-leaf"));
        vm.warp(commitDeadline + 1);
        vm.prank(relayerOwner);
        market.enableRefunds();

        vm.expectRevert(RevealMarket.InvalidMerkleProof.selector);
        vm.prank(relayerOwner);
        market.refund(user, 0, 1, netAmount, payout, _salt("wrong-salt"), new bytes32[](0));
    }

    function _commitTicket(uint256 outcome, bytes32 salt)
        internal
        returns (bytes32 leaf, bytes32[] memory leaves, uint256 netAmount, uint256 payoutAmount)
    {
        uint256 rake = (ticketSize * rakeBps) / 10_000;
        netAmount = ticketSize - rake;
        payoutAmount = netAmount;
        leaf = _poseidonLeaf(0, outcome, netAmount, payoutAmount, salt, user);
        leaves = _wrapLeaf(leaf);

        token.mint(user, ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(ticketSize);

        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: leaf,
            user: user,
            nonce: 1,
            expiry: block.timestamp + 12 hours,
            ticketValue: ticketSize
        });
        bytes memory sig = _signAuth(auth, authKey);
        vm.prank(relayerOwner);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);
    }

    function _lockSingle(bytes32 leaf, bytes memory relayerSig) internal returns (bytes32 root) {
        bytes32[] memory roots = new bytes32[](1);
        uint16[] memory counts = new uint16[](1);
        counts[0] = 1;
        vm.warp(commitDeadline + 1);
        roots[0] = _buildBatchRoot(_wrapLeaf(leaf), 1);

        vm.prank(oracle);
        market.lockBatches(roots, counts, relayerSig);
        return roots[0];
    }

    function _lockAndPost(bytes32 leaf, uint256 outcome) internal returns (bytes32 root) {
        root = _lockSingle(leaf, "");
        vm.prank(oracle);
        market.postResult(outcome);
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
            rakeBps,
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

    function _signRelayer(bytes32[] memory roots, uint16[] memory counts, uint256 privKey)
        private
        view
        returns (bytes memory)
    {
        bytes32 digest = MessageHashUtils.toEthSignedMessageHash(
            keccak256(abi.encode(market.marketId(), roots, counts, block.chainid))
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(privKey, digest);
        return abi.encodePacked(r, s, v);
    }

    function _wrapLeaf(bytes32 leaf) private pure returns (bytes32[] memory leaves) {
        leaves = new bytes32[](1);
        leaves[0] = leaf;
    }

    function _toUint16(uint256 value) private pure returns (uint16) {
        require(value <= type(uint16).max, "uint16 overflow");
        return uint16(value);
    }
}
