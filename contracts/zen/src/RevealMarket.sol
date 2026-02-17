// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {MessageHashUtils} from "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

import {IProtocolPool} from "./interfaces/IProtocolPool.sol";
import {IRevealMarket} from "./interfaces/IRevealMarket.sol";
import {IVerifier} from "./interfaces/IVerifier.sol";
import {PoseidonT3} from "./crypto/PoseidonT3.sol";
import {RelayerEscrow} from "./RelayerEscrow.sol";

interface IOwnable {
    function owner() external view returns (address);
}

/// @notice Minimal commit/reveal market using fixed-size tickets and ZK-verified settlement.
contract RevealMarket is IRevealMarket, ReentrancyGuard {
    using SafeERC20 for IERC20;
    using ECDSA for bytes32;

    uint256 public constant BATCH_SIZE = 256;
    uint8 public constant MERKLE_DEPTH = 8;
    uint256 public constant CLAIM_WINDOW_SECONDS = 180 days;

    struct InitParams {
        address factory;
        address protocolPool;
        address relayerEscrow;
        address oracle;
        address verifier;
        bytes32 circuitHash;
        address collateralToken;
        uint256 commitDeadline;
        uint256 ticketSize;
        uint256 maxCommitments;
        address authorizationSigner;
        uint256 protocolLiabilityCap;
        uint256 marketId;
        uint256 rakeBps;
    }

    address public factory;
    address public protocolPool;
    address public relayerEscrow;
    address public oracle;
    address public verifier;
    bytes32 public circuitHash;
    address public collateralToken;
    uint256 public override commitDeadline;
    uint256 public ticketSize;
    uint256 public maxCommitments;
    address public override authorizationSigner;
    uint256 public protocolLiabilityCap;
    uint256 public override marketId;
    uint256 public rakeBps;

    Phase public override phase;
    bytes32 public commitmentsRoot;
    bytes32[] public batchRoots;
    uint16[] public batchCounts;
    uint256 public totalEscrow;
    uint256 public totalLiability;
    uint256 public rakeAmount;
    uint256 public rakeCollected;
    bool public commitsPaused;
    bool public claimsPaused;
    uint256 public poolTotalYes;
    uint256 public poolTotalNo;
    uint256 public claimedLiability;
    uint256 public claimDeadline;
    bool public claimsSwept;
    uint256 public protocolTopUp;
    uint256 public winningOutcomeId;
    bool public resultPosted;
    bool private initialized;

    bytes32[] private commitments;
    mapping(address => mapping(uint256 => bool)) public usedCommitNonces;
    mapping(uint256 => bool) public claimedTickets;

    event Committed(uint256 indexed ticketId, bytes32 commitment, uint256 totalEscrow);
    event Locked(bytes32 commitmentsRoot, uint256 ticketCount);
    event ResultPosted(uint256 indexed winningOutcomeId);
    event Settled(uint256 totalLiability, uint256 rakeAmount, uint256 protocolTopUp, uint256 poolYes, uint256 poolNo);
    event Claimed(address indexed relayer, address indexed user, uint256 indexed ticketId, uint256 amount);
    event ClaimDeadlineExtended(uint256 newDeadline);
    event ClaimsSwept(address indexed recipient, uint256 amount);
    event CommitsPausedSet(bool paused);
    event ClaimsPausedSet(bool paused);
    event RefundsEnabled(address indexed caller);
    event Refunded(address indexed caller, address indexed user, uint256 indexed ticketId, uint256 amount);
    event AuthorizationSignerUpdated(address indexed signer);
    event OracleUpdated(address indexed oracle);
    event RelayerEscrowUpdated(address indexed relayer);
    event ProtocolLiabilityCapUpdated(uint256 newCap);

    error AlreadyInitialized();
    error NotRelayer();
    error NotAuthorized();
    error NotOracle();
    error InvalidPhase();
    error CommitWindowClosed();
    error CommitExpired();
    error CommitReplay();
    error InvalidSignature();
    error InvalidPayment();
    error MaxCommitmentsReached();
    error NothingToLock();
    error ResultMissing();
    error InvalidProof();
    error CircuitHashMismatch();
    error TotalsMismatch();
    error PaddingMismatch();
    error LiabilityExceedsCoverage();
    error InsufficientCoverage();
    error WrongOutcome();
    error TicketAlreadyClaimed();
    error InvalidMerkleProof();
    error OverClaimed();
    error InvalidOutcome();
    error ResultAlreadyPosted();
    error InvalidInit();
    error RakeMismatch();
    error NotFactory();
    error CommitsPaused();
    error ClaimsPaused();
    error DeadlineExtendOnly();
    error ClaimWindowClosed();
    error ClaimWindowOpen();
    error ClaimsAlreadySwept();
    error RakeLocked();
    error InvalidAddress();
    error RefundsNotEnabled();
    error RefundsUnavailable();
    error UseLockBatches();
    error BatchCountMismatch();
    error BatchSizeExceeded();
    error InvalidBatchIndex();
    error BatchProofLengthMismatch();
    error InvalidRelayerSignature();

    modifier onlyRelayer() {
        _onlyRelayer();
        _;
    }

    modifier onlyRelayerOrFactoryOwner() {
        _onlyRelayerOrFactoryOwner();
        _;
    }

    modifier onlyOracle() {
        _onlyOracle();
        _;
    }

    modifier onlyFactory() {
        _onlyFactory();
        _;
    }

    function _onlyRelayer() internal view {
        address relayerOwner = RelayerEscrow(payable(relayerEscrow)).owner();
        if (msg.sender != relayerEscrow && msg.sender != relayerOwner) revert NotRelayer();
    }

    function _onlyRelayerOrFactoryOwner() internal view {
        address relayerOwner = RelayerEscrow(payable(relayerEscrow)).owner();
        address factoryOwner = IOwnable(factory).owner();
        if (msg.sender != relayerEscrow && msg.sender != relayerOwner && msg.sender != factoryOwner) {
            revert NotAuthorized();
        }
    }

    function _onlyOracle() internal view {
        if (msg.sender != oracle) revert NotOracle();
    }

    function _onlyFactory() internal view {
        if (msg.sender != factory) revert NotFactory();
    }

    function initialize(InitParams calldata params) external {
        if (initialized) revert AlreadyInitialized();
        if (
            params.factory == address(0) || params.protocolPool == address(0) || params.relayerEscrow == address(0)
                || params.oracle == address(0) || params.verifier == address(0)
                || params.authorizationSigner == address(0) || params.ticketSize == 0 || params.commitDeadline == 0
                || params.collateralToken == address(0)
        ) revert InvalidInit();
        if (params.rakeBps > 10_000) revert InvalidInit();
        initialized = true;
        factory = params.factory;
        protocolPool = params.protocolPool;
        relayerEscrow = params.relayerEscrow;
        oracle = params.oracle;
        verifier = params.verifier;
        circuitHash = params.circuitHash;
        collateralToken = params.collateralToken;
        commitDeadline = params.commitDeadline;
        ticketSize = params.ticketSize;
        maxCommitments = params.maxCommitments;
        authorizationSigner = params.authorizationSigner;
        protocolLiabilityCap = params.protocolLiabilityCap;
        marketId = params.marketId;
        rakeBps = params.rakeBps;
        phase = Phase.Commit;
    }

    /// @notice Relayer-only commit entrypoint; verifies backend authorization and pushes the sealed commitment.
    function commitWithAuthorization(CommitAuth calldata auth, bytes calldata signature)
        external
        payable
        override
        onlyRelayer
        nonReentrant
    {
        if (phase != Phase.Commit) revert InvalidPhase();
        if (block.timestamp >= commitDeadline) revert CommitWindowClosed();
        if (commitsPaused) revert CommitsPaused();
        if (msg.value != 0) revert InvalidPayment();
        if (auth.ticketValue != ticketSize) revert InvalidPayment();
        if (auth.user == address(0)) revert InvalidAddress();
        if (IERC20(collateralToken).balanceOf(address(this)) < totalEscrow + ticketSize) revert InvalidPayment();
        if (maxCommitments != 0 && commitments.length >= maxCommitments) revert MaxCommitmentsReached();
        if (auth.expiry < block.timestamp) revert CommitExpired();
        if (usedCommitNonces[auth.user][auth.nonce]) revert CommitReplay();

        bytes memory commitData = abi.encodePacked(
            address(this),
            marketId,
            auth.commitment,
            auth.user,
            auth.nonce,
            auth.expiry,
            auth.ticketValue,
            block.chainid
        );
        bytes32 commitDigest;
        assembly {
            commitDigest := keccak256(add(commitData, 32), mload(commitData))
        }
        bytes32 digest = MessageHashUtils.toEthSignedMessageHash(commitDigest);
        if (digest.recover(signature) != authorizationSigner) revert InvalidSignature();

        usedCommitNonces[auth.user][auth.nonce] = true;
        commitments.push(auth.commitment);
        uint256 rake = (ticketSize * rakeBps) / 10_000;
        uint256 net = ticketSize - rake;
        totalEscrow += net;
        rakeCollected += rake;
        if (rake > 0) {
            IERC20(collateralToken).safeTransfer(protocolPool, rake);
        }
        emit Committed(commitments.length - 1, auth.commitment, totalEscrow);
    }

    /// @notice Locks the market and stores the Merkle root over commitments.
    function lock() external view onlyOracle {
        revert UseLockBatches();
    }

    /// @notice Locks the market with batch Merkle roots (depth-8 Poseidon tree per batch).
    function lockBatches(bytes32[] calldata roots, uint16[] calldata counts, bytes calldata relayerSig)
        external
        onlyOracle
    {
        if (phase != Phase.Commit) revert InvalidPhase();
        if (block.timestamp < commitDeadline) revert CommitWindowClosed();
        if (commitments.length == 0) revert NothingToLock();
        if (roots.length == 0 || roots.length != counts.length) revert BatchCountMismatch();
        if (relayerSig.length != 0) {
            bytes memory digestData = abi.encode(marketId, roots, counts, block.chainid);
            bytes32 digest;
            assembly {
                digest := keccak256(add(digestData, 32), mload(digestData))
            }
            bytes32 signed = MessageHashUtils.toEthSignedMessageHash(digest);
            address relayerOwner = RelayerEscrow(payable(relayerEscrow)).owner();
            if (signed.recover(relayerSig) != relayerOwner) revert InvalidRelayerSignature();
        }

        uint256 total = 0;
        for (uint256 i = 0; i < counts.length; ++i) {
            uint256 count = counts[i];
            if (count == 0) revert BatchCountMismatch();
            if (count > BATCH_SIZE) revert BatchSizeExceeded();
            total += count;
        }
        if (total != commitments.length) revert BatchCountMismatch();

        delete batchRoots;
        delete batchCounts;
        for (uint256 i = 0; i < roots.length; ++i) {
            batchRoots.push(roots[i]);
            batchCounts.push(counts[i]);
        }

        commitmentsRoot = roots.length == 1 ? roots[0] : bytes32(0);
        phase = Phase.Locked;
        emit Locked(commitmentsRoot, commitments.length);
    }

    /// @notice Oracle posts the winning outcome (0 or 1).
    function postResult(uint256 outcomeId) external onlyOracle {
        if (phase != Phase.Locked) revert InvalidPhase();
        if (resultPosted) revert ResultAlreadyPosted();
        if (outcomeId > 1) revert InvalidOutcome();
        winningOutcomeId = outcomeId;
        resultPosted = true;
        emit ResultPosted(outcomeId);
    }

    /// @notice Verifies Groth16 proof and moves market into the Settled phase.
    function verifyAndSettle(bytes calldata proof, uint256[10] calldata publicSignals)
        external
        onlyOracle
        nonReentrant
    {
        if (batchRoots.length != 1) revert InvalidBatchIndex();
        if (phase != Phase.Locked) revert InvalidPhase();
        if (!resultPosted) revert ResultMissing();

        if (
            publicSignals[0] != uint256(batchRoots[0]) || publicSignals[1] != marketId
                || publicSignals[2] != winningOutcomeId || publicSignals[3] != totalEscrow
        ) revert TotalsMismatch();
        if (publicSignals[5] != rakeBps) revert RakeMismatch();
        if (publicSignals[8] != uint256(circuitHash)) revert CircuitHashMismatch();
        if (publicSignals[9] != 0) revert PaddingMismatch();

        bool ok = IVerifier(verifier).verifyProof(proof, publicSignals);
        if (!ok) revert InvalidProof();

        _finalizeSettlement(publicSignals[3], publicSignals[4], publicSignals[6], publicSignals[7]);
    }

    /// @notice Verifies Groth16 proofs per batch and settles the market in one transaction.
    function verifyAndSettleBatched(
        bytes[] calldata proofs,
        uint256[10][] calldata publicSignals,
        uint16[] calldata batchIndexes
    ) external onlyOracle nonReentrant {
        if (phase != Phase.Locked) revert InvalidPhase();
        if (!resultPosted) revert ResultMissing();
        if (proofs.length != publicSignals.length || proofs.length != batchIndexes.length) {
            revert BatchProofLengthMismatch();
        }
        uint256 batchCount = batchRoots.length;
        if (batchCount == 0 || proofs.length != batchCount) revert BatchProofLengthMismatch();

        bool[] memory seen = new bool[](batchCount);
        uint256 totalEscrowSum = 0;
        uint256 totalLiabilitySum = 0;
        uint256 poolYesSum = 0;
        uint256 poolNoSum = 0;

        for (uint256 i = 0; i < proofs.length; ++i) {
            uint256 batchIndex = batchIndexes[i];
            if (batchIndex >= batchCount) revert InvalidBatchIndex();
            if (seen[batchIndex]) revert InvalidBatchIndex();
            seen[batchIndex] = true;

            uint256[10] calldata signals = publicSignals[i];
            if (
                signals[0] != uint256(batchRoots[batchIndex]) || signals[1] != marketId
                    || signals[2] != winningOutcomeId
            ) revert TotalsMismatch();
            if (signals[5] != rakeBps) revert RakeMismatch();
            if (signals[8] != uint256(circuitHash)) revert CircuitHashMismatch();
            if (signals[9] != 0) revert PaddingMismatch();

            bool ok = IVerifier(verifier).verifyProof(proofs[i], signals);
            if (!ok) revert InvalidProof();

            totalEscrowSum += signals[3];
            totalLiabilitySum += signals[4];
            poolYesSum += signals[6];
            poolNoSum += signals[7];
        }

        if (totalEscrowSum != totalEscrow) revert TotalsMismatch();

        _finalizeSettlement(totalEscrowSum, totalLiabilitySum, poolYesSum, poolNoSum);
    }

    /// @notice Winning tickets reveal and pay the user directly.
    function claim(
        address user,
        uint256 ticketId,
        uint256 outcomeId,
        uint256 amount,
        uint256 payout,
        bytes32 salt,
        bytes32[] calldata merkleProof
    ) external nonReentrant {
        if (phase != Phase.Settled) revert InvalidPhase();
        if (claimsPaused) revert ClaimsPaused();
        if (claimDeadline != 0 && block.timestamp > claimDeadline) revert ClaimWindowClosed();
        if (outcomeId != winningOutcomeId) revert WrongOutcome();
        if (claimedTickets[ticketId]) revert TicketAlreadyClaimed();
        bytes32 leaf = _computeLeaf(ticketId, outcomeId, amount, payout, salt, user);
        if (!_verifyLeaf(ticketId, leaf, merkleProof)) revert InvalidMerkleProof();

        claimedTickets[ticketId] = true;
        claimedLiability += payout;
        if (claimedLiability > totalLiability) revert OverClaimed();

        IERC20(collateralToken).safeTransfer(user, payout);
        emit Claimed(msg.sender, user, ticketId, payout);
    }

    /// @notice Enables refunds after the commit window closes; cancels further settlement/claims.
    function enableRefunds() external onlyRelayerOrFactoryOwner {
        if (phase == Phase.Settled) revert InvalidPhase();
        if (block.timestamp < commitDeadline && !commitsPaused) revert RefundsUnavailable();
        if (phase == Phase.Cancelled) return;
        commitsPaused = true;
        claimsPaused = true;
        phase = Phase.Cancelled;
        emit RefundsEnabled(msg.sender);
    }

    /// @notice Refunds a ticket when the market is cancelled (escape hatch when oracle stalls).
    function refund(
        address user,
        uint256 ticketId,
        uint256 outcomeId,
        uint256 amount,
        uint256 payout,
        bytes32 salt,
        bytes32[] calldata merkleProof
    ) external nonReentrant onlyRelayerOrFactoryOwner {
        if (phase != Phase.Cancelled) revert RefundsNotEnabled();
        if (user == address(0)) revert InvalidAddress();
        if (claimedTickets[ticketId]) revert TicketAlreadyClaimed();
        bytes32 leaf = _computeLeaf(ticketId, outcomeId, amount, payout, salt, user);
        if (!_verifyRefundLeaf(ticketId, leaf, merkleProof)) revert InvalidMerkleProof();

        claimedTickets[ticketId] = true;
        uint256 rake = (ticketSize * rakeBps) / 10_000;
        uint256 refundAmount = ticketSize - rake;
        IERC20(collateralToken).safeTransfer(user, refundAmount);
        emit Refunded(msg.sender, user, ticketId, refundAmount);
    }

    /// @notice Users may self-refund after refunds are enabled (caller must match the commitment leaf).
    function refundSelf(
        uint256 ticketId,
        uint256 outcomeId,
        uint256 amount,
        uint256 payout,
        bytes32 salt,
        bytes32[] calldata merkleProof
    ) external nonReentrant {
        if (phase != Phase.Cancelled) revert RefundsNotEnabled();
        if (claimedTickets[ticketId]) revert TicketAlreadyClaimed();
        bytes32 leaf = _computeLeaf(ticketId, outcomeId, amount, payout, salt, msg.sender);
        if (!_verifyRefundLeaf(ticketId, leaf, merkleProof)) revert InvalidMerkleProof();

        claimedTickets[ticketId] = true;
        uint256 rake = (ticketSize * rakeBps) / 10_000;
        uint256 refundAmount = ticketSize - rake;
        IERC20(collateralToken).safeTransfer(msg.sender, refundAmount);
        emit Refunded(msg.sender, msg.sender, ticketId, refundAmount);
    }

    /// @notice Returns the sealed commitment stored at an index (for off-chain auditing).
    function commitmentAt(uint256 index) external view returns (bytes32) {
        return commitments[index];
    }

    /// @notice Aggregated view for cheap off-chain polling of core state.
    function marketState()
        external
        view
        returns (
            bytes32 commitmentsRoot_,
            uint256 nextTicketId_,
            Phase phase_,
            uint256 commitDeadline_,
            uint256 winningOutcomeId_
        )
    {
        commitmentsRoot_ = commitmentsRoot;
        nextTicketId_ = commitments.length;
        phase_ = phase;
        commitDeadline_ = commitDeadline;
        winningOutcomeId_ = winningOutcomeId;
    }

    /// @notice Factory hook to update rake for existing markets (keeps all markets aligned to global rake).
    function setRakeBps(uint256 newRakeBps) external onlyFactory {
        if (phase != Phase.Commit) revert InvalidPhase();
        if (commitments.length != 0) revert RakeLocked();
        if (newRakeBps > 10_000) revert InvalidInit();
        rakeBps = newRakeBps;
    }

    /// @notice Rotate authorization signer (only during commit phase to keep auth coherent).
    function setAuthorizationSigner(address newSigner) external onlyFactory {
        if (newSigner == address(0)) revert InvalidAddress();
        if (phase != Phase.Commit) revert InvalidPhase();
        authorizationSigner = newSigner;
        emit AuthorizationSignerUpdated(newSigner);
    }

    /// @notice Rotate oracle; allowed until settlement to handle provider changes.
    function setOracle(address newOracle) external onlyFactory {
        if (newOracle == address(0)) revert InvalidAddress();
        if (phase == Phase.Settled) revert InvalidPhase();
        oracle = newOracle;
        emit OracleUpdated(newOracle);
    }

    /// @notice Rotate the relayer escrow (e.g., in response to relayer compromise).
    function setRelayerEscrow(address newRelayerEscrow) external onlyFactory {
        if (newRelayerEscrow == address(0)) revert InvalidAddress();
        relayerEscrow = newRelayerEscrow;
        emit RelayerEscrowUpdated(newRelayerEscrow);
    }

    /// @notice Adjust the per-market protocol liability cap before settlement.
    function setProtocolLiabilityCap(uint256 newCap) external onlyFactory {
        if (phase == Phase.Settled) revert InvalidPhase();
        protocolLiabilityCap = newCap;
        emit ProtocolLiabilityCapUpdated(newCap);
    }

    /// @notice Owner/factory controls to pause commits or claims in emergencies.
    function setCommitsPaused(bool paused) external onlyFactory {
        commitsPaused = paused;
        emit CommitsPausedSet(paused);
    }

    function setClaimsPaused(bool paused) external onlyFactory {
        claimsPaused = paused;
        emit ClaimsPausedSet(paused);
    }

    function _finalizeSettlement(
        uint256 totalEscrow_,
        uint256 totalLiability_,
        uint256 poolYes_,
        uint256 poolNo_
    ) internal {
        totalLiability = totalLiability_;
        poolTotalYes = poolYes_;
        poolTotalNo = poolNo_;

        rakeAmount = rakeCollected;
        uint256 required = totalLiability_;
        if (required > totalEscrow_ + protocolLiabilityCap) revert LiabilityExceedsCoverage();

        uint256 balance = IERC20(collateralToken).balanceOf(address(this));
        if (required > balance) {
            uint256 deficit = required - balance;
            protocolTopUp = deficit;
            IProtocolPool(protocolPool).draw(address(this), deficit);
        }

        if (required > IERC20(collateralToken).balanceOf(address(this))) revert InsufficientCoverage();

        // forward any surplus immediately; keep only what is needed for claims
        uint256 tokenBalance = IERC20(collateralToken).balanceOf(address(this));
        uint256 surplus = tokenBalance > totalLiability_ ? tokenBalance - totalLiability_ : 0;
        if (surplus > 0) {
            IERC20(collateralToken).safeTransfer(protocolPool, surplus);
        }

        if (claimDeadline == 0 || claimDeadline < block.timestamp) {
            claimDeadline = block.timestamp + CLAIM_WINDOW_SECONDS;
        }

        phase = Phase.Settled;
        emit Settled(totalLiability_, rakeAmount, protocolTopUp, poolTotalYes, poolTotalNo);
    }

    /// @notice Extend-only deadline updates. Cannot shorten.
    function extendCommitDeadline(uint256 newDeadline) external onlyFactory {
        if (newDeadline <= commitDeadline) revert DeadlineExtendOnly();
        if (phase != Phase.Commit) revert InvalidPhase();
        commitDeadline = newDeadline;
    }

    /// @notice Extend-only claim deadline updates. Cannot shorten.
    function extendClaimDeadline(uint256 newDeadline) external onlyFactory {
        if (newDeadline <= claimDeadline) revert DeadlineExtendOnly();
        claimDeadline = newDeadline;
        emit ClaimDeadlineExtended(newDeadline);
    }

    /// @notice Sweep unclaimed payouts after the claim deadline passes.
    function sweepUnclaimed(address recipient) external onlyFactory {
        if (phase != Phase.Settled) revert InvalidPhase();
        if (claimDeadline == 0 || block.timestamp <= claimDeadline) revert ClaimWindowOpen();
        if (claimsSwept) revert ClaimsAlreadySwept();
        if (recipient != protocolPool && recipient != relayerEscrow) revert InvalidAddress();

        claimsPaused = true;
        claimsSwept = true;
        uint256 remaining = IERC20(collateralToken).balanceOf(address(this));
        if (remaining > 0) {
            IERC20(collateralToken).safeTransfer(recipient, remaining);
        }
        emit ClaimsSwept(recipient, remaining);
    }

    function _computeLeaf(
        uint256 ticketId,
        uint256 outcomeId,
        uint256 amount,
        uint256 payout,
        bytes32 salt,
        address user
    )
        internal
        pure
        returns (bytes32 hash)
    {
        uint256 userSalt = PoseidonT3.poseidon([uint256(uint160(user)), uint256(salt)]);
        uint256 h1 = PoseidonT3.poseidon([ticketId, outcomeId]);
        uint256 h2 = PoseidonT3.poseidon([amount, payout]);
        uint256 h3 = PoseidonT3.poseidon([h2, userSalt]);
        uint256 leaf = PoseidonT3.poseidon([h1, h3]);
        hash = bytes32(leaf);
    }

    function _verifyLeaf(uint256 ticketId, bytes32 leaf, bytes32[] calldata proof) internal view returns (bool) {
        if (ticketId >= commitments.length) return false;
        if (commitments[ticketId] != leaf) return false;
        if (proof.length != MERKLE_DEPTH) return false;
        if (batchRoots.length == 0) return false;
        uint256 batchIndex = ticketId / BATCH_SIZE;
        if (batchIndex >= batchRoots.length) return false;
        uint256 indexInBatch = ticketId % BATCH_SIZE;
        if (indexInBatch >= batchCounts[batchIndex]) return false;

        uint256 computed = uint256(leaf);
        uint256 index = indexInBatch;
        for (uint256 i = 0; i < MERKLE_DEPTH; ++i) {
            uint256 sibling = uint256(proof[i]);
            if ((index & 1) == 1) {
                computed = PoseidonT3.poseidon([sibling, computed]);
            } else {
                computed = PoseidonT3.poseidon([computed, sibling]);
            }
            index >>= 1;
        }
        return computed == uint256(batchRoots[batchIndex]);
    }

    function _verifyRefundLeaf(uint256 ticketId, bytes32 leaf, bytes32[] calldata proof) internal view returns (bool) {
        if (batchRoots.length == 0) {
            if (ticketId >= commitments.length) return false;
            return commitments[ticketId] == leaf;
        }
        return _verifyLeaf(ticketId, leaf, proof);
    }

    /// @notice Returns the next ticket id (commitments length); useful for off-chain pre-checks.
    function nextTicketId() external view returns (uint256) {
        return commitments.length;
    }

    receive() external payable {
        revert("Native transfers disabled");
    }
}
