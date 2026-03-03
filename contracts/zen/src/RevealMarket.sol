// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

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

interface IFactoryVerifierPolicy {
    function isVerifierCurrentlyApproved(address verifier, bytes32 expectedCircuitHash) external view returns (bool);
}

/// @notice Minimal commit/reveal market using fixed-size tickets and ZK-verified settlement.
contract RevealMarket is IRevealMarket, ReentrancyGuard {
    using SafeERC20 for IERC20;
    using ECDSA for bytes32;

    uint256 public constant BATCH_SIZE = 256;
    uint8 public constant MERKLE_DEPTH = 8;
    uint256 public constant MAX_LOCK_BATCH_COUNT = 64;
    uint256 public constant MAX_COMMITMENTS_LIMIT = MAX_LOCK_BATCH_COUNT * BATCH_SIZE;
    uint256 private constant SNARK_SCALAR_FIELD =
        21888242871839275222246405745257275088548364400416034343698204186575808495617;
    uint256 public constant MAX_COMMIT_DEADLINE_EXTENSION = 30 days;
    uint256 public constant CLAIM_WINDOW_SECONDS = 180 days;
    uint256 public constant MAX_CLAIM_DEADLINE_EXTENSION = 365 days;
    uint256 public constant SETTLEMENT_TIMEOUT_SECONDS = 14 days;

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
    bool public commitDeadlineExtended;
    uint256 public claimDeadline;
    bool public claimDeadlineExtended;
    bool public claimsSwept;
    uint256 public claimPauseTotalDuration;
    uint256 public claimPauseStartedAt;
    uint256 public refundDeadline;
    bool public refundDeadlineExtended;
    bool public refundsSwept;
    uint256 public protocolTopUp;
    uint256 public winningOutcomeId;
    bytes32 public lockedVerifierKeyHash;
    uint256 public settledBatchCount;
    uint256 public settledEscrowSum;
    uint256 public settledLiabilitySum;
    uint256 public settledPoolYesSum;
    uint256 public settledPoolNoSum;
    uint256 public lockedAt;
    bool public resultPosted;
    bool private initialized;

    bytes32[] private commitments;
    address[] private commitmentUsers;
    mapping(address => mapping(uint256 => bool)) public usedCommitNonces;
    mapping(uint256 => bool) public claimedTickets;
    mapping(uint16 => uint256) private batchProofEpoch;
    uint256 private currentBatchProofEpoch;

    event Committed(uint256 indexed ticketId, bytes32 commitment, uint256 totalEscrow);
    event Locked(bytes32 indexed commitmentsRoot, uint256 ticketCount);
    event ResultPosted(uint256 indexed winningOutcomeId);
    event Settled(
        uint256 indexed totalLiability, uint256 rakeAmount, uint256 protocolTopUp, uint256 poolYes, uint256 poolNo
    );
    event Claimed(address indexed relayer, address indexed user, uint256 indexed ticketId, uint256 amount);
    event ClaimDeadlineExtended(uint256 newDeadline);
    event ClaimsSwept(address indexed recipient, uint256 amount);
    event RefundDeadlineExtended(uint256 newDeadline);
    event CommitsPausedSet(bool paused);
    event ClaimsPausedSet(bool paused);
    event RefundsEnabled(address indexed caller);
    event Refunded(address indexed caller, address indexed user, uint256 indexed ticketId, uint256 amount);
    event AuthorizationSignerUpdated(address indexed signer);
    event OracleUpdated(address indexed oracle);
    event RelayerEscrowUpdated(address indexed relayer);
    event ProtocolPoolUpdated(address indexed protocolPool);
    event ProtocolLiabilityCapUpdated(uint256 newCap);
    event VerifierUpdated(address indexed verifier, bytes32 indexed circuitHash);
    event LockedVerifierKeyRefreshed(bytes32 indexed keyHash);
    event SettlementProgressReset(uint256 previousSettledBatches);
    event BatchProofAccepted(uint16 indexed batchIndex, uint256 settledBatches);
    event RefundsSwept(address indexed recipient, uint256 amount);

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
    error DeadlineTooFar();
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

    error VerifierInputCountMismatch();
    error VerifierKeyMismatch();
    error BatchAlreadyVerified();
    error RefundWindowClosed();
    error FeeOnTransferNotSupported();
    error MaxCommitmentsUnsupported();
    error ClaimDeadlineAlreadyExtended();
    error RefundDeadlineAlreadyExtended();
    error CommitmentUserMismatch();
    error TicketIndexMismatch();
    error CommitDeadlineAlreadyExtended();
    error VerifierNotApproved();
    error FieldElementOutOfRange();
    error OracleAuthorizationExpired();
    error NativeTransfersDisabled();

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
        if (msg.sender != relayerEscrow) revert NotRelayer();
    }

    function _onlyRelayerOrFactoryOwner() internal view {
        if (msg.sender == relayerEscrow) return;
        address relayerOwner = RelayerEscrow(payable(relayerEscrow)).owner();
        if (msg.sender == relayerOwner) return;
        address factoryOwner = IOwnable(factory).owner();
        if (msg.sender == factoryOwner) return;
        revert NotAuthorized();
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
        if (IVerifier(params.verifier).expectedInputs() != 10) revert VerifierInputCountMismatch();
        if (IVerifier(params.verifier).circuitHash() != params.circuitHash) revert CircuitHashMismatch();
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
        if (params.maxCommitments > MAX_COMMITMENTS_LIMIT) revert MaxCommitmentsUnsupported();
        maxCommitments = params.maxCommitments == 0 ? MAX_COMMITMENTS_LIMIT : params.maxCommitments;
        authorizationSigner = params.authorizationSigner;
        protocolLiabilityCap = params.protocolLiabilityCap;
        marketId = params.marketId;
        rakeBps = params.rakeBps;
        phase = Phase.Commit;
    }

    /// @notice Relayer-only commit entrypoint; verifies backend authorization and pushes the sealed commitment.
    /// @dev Trust assumption: the relayer controls commit ordering and may front-run or reorder tickets within
    ///      a block. ticketId is bound to the sequential commitments.length at execution time; the backend
    ///      authorization signature covers the ticketId to prevent replay across slots.
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
        address cachedRelayerEscrow = relayerEscrow;
        if (RelayerEscrow(payable(cachedRelayerEscrow)).commitsPaused()) revert CommitsPaused();
        if (msg.value != 0) revert InvalidPayment();
        uint256 cachedTicketSize = ticketSize;
        if (auth.ticketValue != cachedTicketSize) revert InvalidPayment();
        if (auth.user == address(0)) revert InvalidAddress();
        address cachedCollateralToken = collateralToken;
        if (IERC20(cachedCollateralToken).balanceOf(address(this)) < totalEscrow + cachedTicketSize) {
            revert InvalidPayment();
        }
        if (commitments.length >= maxCommitments) revert MaxCommitmentsReached();
        if (uint256(auth.commitment) >= SNARK_SCALAR_FIELD) revert FieldElementOutOfRange();
        uint256 expectedTicketId = commitments.length;
        if (auth.ticketId != expectedTicketId) revert TicketIndexMismatch();
        if (auth.expiry < block.timestamp) revert CommitExpired();
        if (usedCommitNonces[auth.user][auth.nonce]) revert CommitReplay();

        bytes memory commitData = abi.encodePacked(
            address(this),
            marketId,
            auth.ticketId,
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
        commitmentUsers.push(auth.user);
        uint256 cachedRakeBps = rakeBps;
        uint256 rake = (cachedTicketSize * cachedRakeBps) / 10_000;
        uint256 net = cachedTicketSize - rake;
        totalEscrow += net;
        rakeCollected += rake;
        emit Committed(expectedTicketId, auth.commitment, totalEscrow);
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
        if (IVerifier(verifier).circuitHash() != circuitHash) revert CircuitHashMismatch();
        if (!_isVerifierApprovedForSettlement()) revert VerifierNotApproved();
        if (relayerSig.length == 0) revert InvalidRelayerSignature();
        bytes memory digestData = abi.encode(address(this), factory, marketId, roots, counts, block.chainid);
        bytes32 digest;
        assembly {
            digest := keccak256(add(digestData, 32), mload(digestData))
        }
        bytes32 signed = MessageHashUtils.toEthSignedMessageHash(digest);
        address relayerOwner = RelayerEscrow(payable(relayerEscrow)).owner();
        if (signed.recover(relayerSig) != relayerOwner) revert InvalidRelayerSignature();

        uint256 expectedBatches = (commitments.length + BATCH_SIZE - 1) / BATCH_SIZE;
        if (roots.length != expectedBatches) revert BatchCountMismatch();
        uint256 total = 0;
        for (uint256 i = 0; i < counts.length;) {
            uint256 count = counts[i];
            if (count > BATCH_SIZE) revert BatchSizeExceeded();
            uint256 remaining = commitments.length - total;
            uint256 expectedCount = remaining > BATCH_SIZE ? BATCH_SIZE : remaining;
            if (count != expectedCount) revert BatchCountMismatch();
            total += count;
            unchecked {
                ++i;
            }
        }
        if (total != commitments.length) revert BatchCountMismatch();

        delete batchRoots;
        delete batchCounts;
        for (uint256 i = 0; i < roots.length;) {
            batchRoots.push(roots[i]);
            batchCounts.push(counts[i]);
            unchecked {
                ++i;
            }
        }

        lockedVerifierKeyHash = IVerifier(verifier).verifyingKeyHash();
        currentBatchProofEpoch += 1;
        settledBatchCount = 0;
        settledEscrowSum = 0;
        settledLiabilitySum = 0;
        settledPoolYesSum = 0;
        settledPoolNoSum = 0;
        lockedAt = block.timestamp;
        IProtocolPool(protocolPool).reserveLiability(address(this), protocolLiabilityCap);

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
        address cachedVerifier = verifier;
        if (IVerifier(cachedVerifier).circuitHash() != circuitHash) revert CircuitHashMismatch();
        if (!_isVerifierApprovedForSettlement()) revert VerifierNotApproved();
        if (IVerifier(cachedVerifier).verifyingKeyHash() != lockedVerifierKeyHash) revert VerifierKeyMismatch();

        if (
            publicSignals[0] != uint256(batchRoots[0]) || publicSignals[1] != marketId
                || publicSignals[2] != winningOutcomeId || publicSignals[3] != totalEscrow
        ) revert TotalsMismatch();
        if (publicSignals[5] != rakeBps) revert RakeMismatch();
        if (publicSignals[8] != uint256(circuitHash)) revert CircuitHashMismatch();
        if (publicSignals[9] != 0) revert PaddingMismatch();

        bool ok = IVerifier(cachedVerifier).verifyProof(proof, publicSignals);
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
        address cachedVerifier = verifier;
        if (IVerifier(cachedVerifier).circuitHash() != circuitHash) revert CircuitHashMismatch();
        if (!_isVerifierApprovedForSettlement()) revert VerifierNotApproved();
        if (IVerifier(cachedVerifier).verifyingKeyHash() != lockedVerifierKeyHash) revert VerifierKeyMismatch();
        if (proofs.length != publicSignals.length || proofs.length != batchIndexes.length) {
            revert BatchProofLengthMismatch();
        }
        uint256 batchCount = batchRoots.length;
        if (batchCount == 0 || proofs.length == 0) revert BatchProofLengthMismatch();

        uint256 memBatchCount = settledBatchCount;
        uint256 memEscrowSum = settledEscrowSum;
        uint256 memLiabilitySum = settledLiabilitySum;
        uint256 memPoolYesSum = settledPoolYesSum;
        uint256 memPoolNoSum = settledPoolNoSum;

        for (uint256 i = 0; i < proofs.length;) {
            _verifyBatchProof(proofs[i], publicSignals[i], batchIndexes[i], batchCount, cachedVerifier);
            memBatchCount += 1;
            memEscrowSum += publicSignals[i][3];
            memLiabilitySum += publicSignals[i][4];
            memPoolYesSum += publicSignals[i][6];
            memPoolNoSum += publicSignals[i][7];
            emit BatchProofAccepted(batchIndexes[i], memBatchCount);
            unchecked {
                ++i;
            }
        }

        settledBatchCount = memBatchCount;
        settledEscrowSum = memEscrowSum;
        settledLiabilitySum = memLiabilitySum;
        settledPoolYesSum = memPoolYesSum;
        settledPoolNoSum = memPoolNoSum;

        if (memBatchCount == batchCount) {
            if (memEscrowSum != totalEscrow) revert TotalsMismatch();
            _finalizeSettlement(memEscrowSum, memLiabilitySum, memPoolYesSum, memPoolNoSum);
        }
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
        if (claimsSwept) revert ClaimsAlreadySwept();
        if (claimDeadline != 0 && block.timestamp > _effectiveClaimDeadline()) revert ClaimWindowClosed();
        if (outcomeId != winningOutcomeId) revert WrongOutcome();
        if (claimedTickets[ticketId]) revert TicketAlreadyClaimed();
        if (_ticketOwner(ticketId) != user) revert CommitmentUserMismatch();
        bytes32 leaf = _computeLeaf(ticketId, outcomeId, amount, payout, salt, user);
        if (!_verifyLeaf(ticketId, leaf, merkleProof)) revert InvalidMerkleProof();

        claimedTickets[ticketId] = true;
        claimedLiability += payout;
        if (claimedLiability > totalLiability) revert OverClaimed();

        _safeTransferExact(user, payout);
        emit Claimed(msg.sender, user, ticketId, payout);
    }

    /// @notice Enables refunds after the commit window closes; cancels further settlement/claims.
    function enableRefunds() external {
        if (msg.sender != factory) revert NotFactory();
        if (phase == Phase.Settled) revert InvalidPhase();
        if (phase == Phase.Cancelled) return;
        if (phase == Phase.Commit) {
            if (block.timestamp < commitDeadline) revert RefundsUnavailable();
        } else if (phase == Phase.Locked) {
            if (block.timestamp < lockedAt + SETTLEMENT_TIMEOUT_SECONDS) revert RefundsUnavailable();
        } else {
            revert InvalidPhase();
        }
        commitsPaused = true;
        claimsPaused = true;
        phase = Phase.Cancelled;
        uint256 minRefundDeadline = block.timestamp + CLAIM_WINDOW_SECONDS;
        if (refundDeadline < minRefundDeadline) {
            refundDeadline = minRefundDeadline;
        }
        refundDeadlineExtended = false;
        _releaseLiabilityReservation();
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
        if (refundDeadline != 0 && block.timestamp > refundDeadline) revert RefundWindowClosed();
        if (refundsSwept) revert ClaimsAlreadySwept();
        if (user == address(0)) revert InvalidAddress();
        if (claimedTickets[ticketId]) revert TicketAlreadyClaimed();
        if (_ticketOwner(ticketId) != user) revert CommitmentUserMismatch();
        bytes32 leaf = _computeLeaf(ticketId, outcomeId, amount, payout, salt, user);
        if (!_verifyRefundLeaf(ticketId, leaf, merkleProof)) revert InvalidMerkleProof();

        claimedTickets[ticketId] = true;
        uint256 refundAmount = ticketSize;
        _safeTransferExact(user, refundAmount);
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
        if (refundDeadline != 0 && block.timestamp > refundDeadline) revert RefundWindowClosed();
        if (refundsSwept) revert ClaimsAlreadySwept();
        if (claimedTickets[ticketId]) revert TicketAlreadyClaimed();
        if (_ticketOwner(ticketId) != msg.sender) revert CommitmentUserMismatch();
        bytes32 leaf = _computeLeaf(ticketId, outcomeId, amount, payout, salt, msg.sender);
        if (!_verifyRefundLeaf(ticketId, leaf, merkleProof)) revert InvalidMerkleProof();

        claimedTickets[ticketId] = true;
        uint256 refundAmount = ticketSize;
        _safeTransferExact(msg.sender, refundAmount);
        emit Refunded(msg.sender, msg.sender, ticketId, refundAmount);
    }

    /// @notice Permissionless refund path that only needs the sealed ticket id in cancelled markets.
    function refundTicket(uint256 ticketId) external nonReentrant {
        if (phase != Phase.Cancelled) revert RefundsNotEnabled();
        if (refundDeadline != 0 && block.timestamp > refundDeadline) revert RefundWindowClosed();
        if (refundsSwept) revert ClaimsAlreadySwept();
        if (claimedTickets[ticketId]) revert TicketAlreadyClaimed();
        address user = _ticketOwner(ticketId);
        if (user == address(0)) revert CommitmentUserMismatch();

        claimedTickets[ticketId] = true;
        uint256 refundAmount = ticketSize;
        _safeTransferExact(user, refundAmount);
        emit Refunded(msg.sender, user, ticketId, refundAmount);
    }

    /// @notice Fallback claim path when users cannot reconstruct commitment preimages.
    /// Oracle signs ticket-level payouts off-chain and anyone can execute delivery to the recorded ticket owner.
    /// @dev Trust assumption: the oracle is trusted to produce correct payout amounts. The on-chain guard caps
    ///      cumulative claimed liability at totalLiability and per-ticket payouts at totalLiability to bound damage
    ///      from a compromised oracle key.
    function claimWithOracleAuthorization(
        uint256 ticketId,
        uint256 payout,
        uint256 expiry,
        bytes calldata oracleSignature
    ) external nonReentrant {
        if (phase != Phase.Settled) revert InvalidPhase();
        if (claimsPaused) revert ClaimsPaused();
        if (claimsSwept) revert ClaimsAlreadySwept();
        if (claimDeadline != 0 && block.timestamp > _effectiveClaimDeadline()) revert ClaimWindowClosed();
        if (block.timestamp > expiry) revert OracleAuthorizationExpired();
        if (payout > totalLiability) revert OverClaimed();
        if (claimedTickets[ticketId]) revert TicketAlreadyClaimed();

        address user = _ticketOwner(ticketId);
        if (user == address(0)) revert CommitmentUserMismatch();
        bytes32 digest = MessageHashUtils.toEthSignedMessageHash(
            keccak256(
                abi.encode(
                    address(this),
                    marketId,
                    ticketId,
                    user,
                    winningOutcomeId,
                    payout,
                    expiry,
                    block.chainid,
                    "CLAIM_ORACLE_V1"
                )
            )
        );
        if (digest.recover(oracleSignature) != oracle) revert InvalidSignature();

        claimedTickets[ticketId] = true;
        claimedLiability += payout;
        if (claimedLiability > totalLiability) revert OverClaimed();

        _safeTransferExact(user, payout);
        emit Claimed(msg.sender, user, ticketId, payout);
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

    /// @notice Rotate oracle; only allowed during the Commit phase.
    function setOracle(address newOracle) external onlyFactory {
        if (newOracle == address(0)) revert InvalidAddress();
        if (phase != Phase.Commit) revert InvalidPhase();
        oracle = newOracle;
        emit OracleUpdated(newOracle);
    }

    /// @notice Rotate the relayer escrow (e.g., in response to relayer compromise).
    function setRelayerEscrow(address newRelayerEscrow) external onlyFactory {
        if (newRelayerEscrow == address(0)) revert InvalidAddress();
        relayerEscrow = newRelayerEscrow;
        emit RelayerEscrowUpdated(newRelayerEscrow);
    }

    /// @notice Rotate protocol pool routing during commit phase before lock reservations are taken.
    function setProtocolPool(address newProtocolPool) external onlyFactory {
        if (newProtocolPool == address(0)) revert InvalidAddress();
        if (phase != Phase.Commit) revert InvalidPhase();
        if (commitments.length != 0) revert InvalidPhase();
        protocolPool = newProtocolPool;
        emit ProtocolPoolUpdated(newProtocolPool);
    }

    /// @notice Rotate verifier metadata before terminal phases.
    function setVerifier(address newVerifier, bytes32 newCircuitHash) external onlyFactory {
        if (newVerifier == address(0)) revert InvalidAddress();
        if (phase != Phase.Commit) revert InvalidPhase();
        if (IVerifier(newVerifier).expectedInputs() != 10) revert VerifierInputCountMismatch();
        if (IVerifier(newVerifier).circuitHash() != newCircuitHash) revert CircuitHashMismatch();
        if (commitments.length != 0 && newCircuitHash != circuitHash) revert CircuitHashMismatch();
        verifier = newVerifier;
        circuitHash = newCircuitHash;
        emit VerifierUpdated(newVerifier, newCircuitHash);
    }

    /// @notice Refreshes the locked verifier key hash after a verifier key rotation.
    ///         Resets settlement progress if any batch proofs were already accepted under the old key.
    function refreshLockedVerifierKeyHash() external onlyFactory {
        if (phase != Phase.Locked) revert InvalidPhase();
        if (IVerifier(verifier).circuitHash() != circuitHash) revert CircuitHashMismatch();
        if (!_isVerifierApprovedForSettlement()) revert VerifierNotApproved();
        bytes32 newKeyHash = IVerifier(verifier).verifyingKeyHash();
        lockedVerifierKeyHash = newKeyHash;
        if (settledBatchCount > 0) {
            uint256 prev = settledBatchCount;
            currentBatchProofEpoch += 1;
            settledBatchCount = 0;
            settledEscrowSum = 0;
            settledLiabilitySum = 0;
            settledPoolYesSum = 0;
            settledPoolNoSum = 0;
            emit SettlementProgressReset(prev);
        }
        emit LockedVerifierKeyRefreshed(newKeyHash);
    }

    /// @notice Adjust the per-market protocol liability cap before settlement.
    function setProtocolLiabilityCap(uint256 newCap) external onlyFactory {
        if (phase != Phase.Commit) revert InvalidPhase();
        protocolLiabilityCap = newCap;
        emit ProtocolLiabilityCapUpdated(newCap);
    }

    /// @notice Owner/factory controls to pause commits or claims in emergencies.
    function setCommitsPaused(bool paused) external onlyFactory {
        commitsPaused = paused;
        emit CommitsPausedSet(paused);
    }

    function setClaimsPaused(bool paused) external onlyFactory {
        if (claimsSwept) revert ClaimsAlreadySwept();
        if (phase == Phase.Settled) {
            if (paused && !claimsPaused) {
                claimPauseStartedAt = block.timestamp;
            } else if (!paused && claimsPaused) {
                uint256 elapsed = block.timestamp - claimPauseStartedAt;
                uint256 newTotal = claimPauseTotalDuration + elapsed;
                if (newTotal > MAX_CLAIM_DEADLINE_EXTENSION) {
                    newTotal = MAX_CLAIM_DEADLINE_EXTENSION;
                }
                claimPauseTotalDuration = newTotal;
                claimPauseStartedAt = 0;
            }
        }
        claimsPaused = paused;
        emit ClaimsPausedSet(paused);
    }

    function _finalizeSettlement(uint256 totalEscrow_, uint256 totalLiability_, uint256 poolYes_, uint256 poolNo_)
        internal
    {
        totalLiability = totalLiability_;
        poolTotalYes = poolYes_;
        poolTotalNo = poolNo_;

        rakeAmount = rakeCollected;
        uint256 required = totalLiability_;
        if (required > totalEscrow_ + protocolLiabilityCap) revert LiabilityExceedsCoverage();

        address cachedCollateralToken = collateralToken;
        uint256 balance = IERC20(cachedCollateralToken).balanceOf(address(this));
        if (required > balance) {
            uint256 deficit = required - balance;
            protocolTopUp = deficit;
            IProtocolPool(protocolPool).draw(address(this), deficit);
            balance = IERC20(cachedCollateralToken).balanceOf(address(this));
        }

        if (required > balance) revert InsufficientCoverage();

        // forward any surplus immediately; keep only what is needed for claims
        uint256 surplus = balance > totalLiability_ ? balance - totalLiability_ : 0;
        if (surplus > 0) {
            _safeTransferExact(protocolPool, surplus);
        }

        uint256 minClaimDeadline = block.timestamp + CLAIM_WINDOW_SECONDS;
        if (claimDeadline < minClaimDeadline) {
            claimDeadline = minClaimDeadline;
        }
        claimDeadlineExtended = false;
        claimPauseTotalDuration = 0;
        claimPauseStartedAt = claimsPaused ? block.timestamp : 0;

        _releaseLiabilityReservation();
        phase = Phase.Settled;
        emit Settled(totalLiability_, rakeAmount, protocolTopUp, poolTotalYes, poolTotalNo);
    }

    /// @notice Extend-only deadline updates. Cannot shorten. Must be called before the window closes.
    function extendCommitDeadline(uint256 newDeadline) external onlyFactory {
        if (newDeadline <= commitDeadline) revert DeadlineExtendOnly();
        if (phase != Phase.Commit) revert InvalidPhase();
        if (block.timestamp >= commitDeadline) revert CommitWindowClosed();
        if (commitDeadlineExtended) revert CommitDeadlineAlreadyExtended();
        if (newDeadline > commitDeadline + MAX_COMMIT_DEADLINE_EXTENSION) revert DeadlineTooFar();
        commitDeadline = newDeadline;
        commitDeadlineExtended = true;
    }

    /// @notice Extend-only claim deadline updates. Cannot shorten.
    function extendClaimDeadline(uint256 newDeadline) external onlyFactory {
        if (phase != Phase.Settled) revert InvalidPhase();
        if (claimsSwept) revert ClaimsAlreadySwept();
        if (claimDeadlineExtended) revert ClaimDeadlineAlreadyExtended();
        if (claimDeadline == 0 || block.timestamp > _effectiveClaimDeadline()) revert ClaimWindowClosed();
        if (newDeadline <= claimDeadline) revert DeadlineExtendOnly();
        if (newDeadline > claimDeadline + MAX_CLAIM_DEADLINE_EXTENSION) revert DeadlineTooFar();
        claimDeadline = newDeadline;
        claimDeadlineExtended = true;
        emit ClaimDeadlineExtended(newDeadline);
    }

    /// @notice Extend-only refund deadline updates. Can be used once for cancelled markets.
    function extendRefundDeadline(uint256 newDeadline) external onlyFactory {
        if (phase != Phase.Cancelled) revert InvalidPhase();
        if (refundsSwept) revert ClaimsAlreadySwept();
        if (refundDeadlineExtended) revert RefundDeadlineAlreadyExtended();
        if (refundDeadline == 0 || block.timestamp > refundDeadline) revert RefundWindowClosed();
        if (newDeadline <= refundDeadline) revert DeadlineExtendOnly();
        if (newDeadline > refundDeadline + MAX_CLAIM_DEADLINE_EXTENSION) revert DeadlineTooFar();
        refundDeadline = newDeadline;
        refundDeadlineExtended = true;
        emit RefundDeadlineExtended(newDeadline);
    }

    /// @notice Sweep unclaimed payouts after the claim deadline passes.
    function sweepUnclaimed(address recipient) external onlyFactory {
        if (phase != Phase.Settled) revert InvalidPhase();
        if (claimDeadline == 0 || block.timestamp <= _effectiveClaimDeadline()) revert ClaimWindowOpen();
        if (claimsSwept) revert ClaimsAlreadySwept();
        if (recipient != protocolPool) revert InvalidAddress();

        claimsPaused = true;
        claimsSwept = true;
        uint256 remaining = IERC20(collateralToken).balanceOf(address(this));
        if (remaining > 0) {
            _safeTransferExact(recipient, remaining);
        }
        emit ClaimsSwept(recipient, remaining);
    }

    /// @notice Sweep unrefunded collateral after cancellation refund window closes.
    function sweepCancelledRefunds(address recipient) external onlyFactory {
        if (phase != Phase.Cancelled) revert InvalidPhase();
        if (refundDeadline == 0 || block.timestamp <= refundDeadline) revert ClaimWindowOpen();
        if (refundsSwept) revert ClaimsAlreadySwept();
        if (recipient != protocolPool) revert InvalidAddress();

        refundsSwept = true;
        uint256 remaining = IERC20(collateralToken).balanceOf(address(this));
        if (remaining > 0) {
            _safeTransferExact(recipient, remaining);
        }
        emit RefundsSwept(recipient, remaining);
    }

    function _verifyBatchProof(
        bytes calldata proof,
        uint256[10] calldata signals,
        uint16 batchIndex,
        uint256 batchCount,
        address cachedVerifier
    ) internal {
        if (batchIndex >= batchCount) revert InvalidBatchIndex();
        uint256 epoch = currentBatchProofEpoch;
        if (batchProofEpoch[batchIndex] == epoch) revert BatchAlreadyVerified();
        uint256 cachedMarketId = marketId;
        if (signals[0] != uint256(batchRoots[batchIndex]) || signals[1] != cachedMarketId || signals[2] != winningOutcomeId) {
            revert TotalsMismatch();
        }
        if (signals[5] != rakeBps) revert RakeMismatch();
        if (signals[8] != uint256(circuitHash)) revert CircuitHashMismatch();
        if (signals[9] != 0) revert PaddingMismatch();

        bool ok = IVerifier(cachedVerifier).verifyProof(proof, signals);
        if (!ok) revert InvalidProof();

        batchProofEpoch[batchIndex] = epoch;
    }

    function _releaseLiabilityReservation() internal {
        IProtocolPool(protocolPool).releaseLiabilityReservation(address(this));
    }

    function _computeLeaf(
        uint256 ticketId,
        uint256 outcomeId,
        uint256 amount,
        uint256 payout,
        bytes32 salt,
        address user
    ) internal pure returns (bytes32 hash) {
        if (
            ticketId >= SNARK_SCALAR_FIELD || outcomeId >= SNARK_SCALAR_FIELD || amount >= SNARK_SCALAR_FIELD
                || payout >= SNARK_SCALAR_FIELD || uint256(salt) >= SNARK_SCALAR_FIELD
        ) {
            revert FieldElementOutOfRange();
        }
        uint256 leaf = PoseidonT3.computeLeaf(ticketId, outcomeId, amount, payout, uint256(uint160(user)), uint256(salt));
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

        bytes32[8] memory siblings;
        for (uint256 i = 0; i < 8;) {
            siblings[i] = proof[i];
            unchecked {
                ++i;
            }
        }
        uint256 computed = PoseidonT3.verifyMerkle(uint256(leaf), indexInBatch, siblings);
        return computed == uint256(batchRoots[batchIndex]);
    }

    function _verifyRefundLeaf(uint256 ticketId, bytes32 leaf, bytes32[] calldata proof) internal view returns (bool) {
        proof;
        if (ticketId >= commitments.length) return false;
        return commitments[ticketId] == leaf;
    }

    function _effectiveClaimDeadline() internal view returns (uint256) {
        uint256 effective = claimDeadline + claimPauseTotalDuration;
        if (claimsPaused && claimPauseStartedAt != 0) {
            effective += block.timestamp - claimPauseStartedAt;
        }
        return effective;
    }

    function _ticketOwner(uint256 ticketId) internal view returns (address) {
        if (ticketId >= commitmentUsers.length) return address(0);
        return commitmentUsers[ticketId];
    }

    function _isVerifierApprovedForSettlement() internal view returns (bool) {
        try IFactoryVerifierPolicy(factory).isVerifierCurrentlyApproved(verifier, circuitHash) returns (bool approved) {
            return approved;
        } catch {
            return false;
        }
    }

    /// @dev Strict accounting transfer that reverts on fee-on-transfer or deflationary tokens.
    ///      Intentionally over-checks both sender debit and recipient credit to ensure exact delivery.
    ///      This is safe because the collateral token is a known, trusted ERC20 set at initialization;
    ///      the strict checks serve as a defense-in-depth invariant rather than a runtime expectation.
    function _safeTransferExact(address recipient, uint256 amount) internal {
        IERC20 token = IERC20(collateralToken);
        uint256 senderBalanceBefore = token.balanceOf(address(this));
        uint256 recipientBalanceBefore = token.balanceOf(recipient);
        token.safeTransfer(recipient, amount);
        uint256 senderBalanceAfter = token.balanceOf(address(this));
        if (senderBalanceAfter > senderBalanceBefore) revert FeeOnTransferNotSupported();
        uint256 senderDebited = senderBalanceBefore - senderBalanceAfter;
        if (senderDebited != amount) revert FeeOnTransferNotSupported();
        uint256 recipientBalanceAfter = token.balanceOf(recipient);
        if (recipientBalanceAfter < recipientBalanceBefore) revert FeeOnTransferNotSupported();
        uint256 recipientReceived = recipientBalanceAfter - recipientBalanceBefore;
        if (recipientReceived < amount) revert FeeOnTransferNotSupported();
    }

    /// @notice Returns true if a batch proof has been accepted in the current settlement epoch.
    function batchProofVerified(uint16 batchIndex) external view returns (bool) {
        return batchProofEpoch[batchIndex] == currentBatchProofEpoch;
    }

    /// @notice Returns the next ticket id (commitments length); useful for off-chain pre-checks.
    function nextTicketId() external view returns (uint256) {
        return commitments.length;
    }

    receive() external payable {
        revert NativeTransfersDisabled();
    }
}
