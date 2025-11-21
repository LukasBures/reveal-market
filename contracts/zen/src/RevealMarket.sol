// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {SafeTransferLib} from "solmate/utils/SafeTransferLib.sol";

import {IMarketFactoryRisk} from "./interfaces/IMarketFactoryRisk.sol";
import {IMarketFactoryStatus} from "./interfaces/IMarketFactoryStatus.sol";
import {IRakeManager} from "./interfaces/IRakeManager.sol";
import {IVerifier} from "./interfaces/IVerifier.sol";

/// @title RevealMarket
/// @notice ZEN-denominated commit/reveal market with liability-aware accounting and float support.
contract RevealMarket is ReentrancyGuard {
    enum Phase {
        Commit,
        Locked,
        Settled,
        Cancelled
    }

    enum PayoutCurve {
        FixedOdds,
        ConstantMultiplier
    }

    struct Ticket {
        bytes32 commitHash;
        uint256 amount;
        bool revealed;
        bool claimed;
    }

    struct InitConfig {
        string eventId;
        uint256 commitDeadline;
        uint256 revealDeadline;
        address oracle;
        address verifier;
        address rakeManager;
        address treasury;
        address guardian;
        uint256 rakeBpsOverride;
        uint256 payoutMultiplier;
        PayoutCurve payoutCurve;
        uint256 maxMarketSize;
    }

    struct SettlementSignals {
        bytes32 commitmentsRoot;
        uint256 marketId;
        uint256 winningOutcomeId;
        uint256 totalEscrow;
        uint256 totalLiability;
        uint256 rakeBps;
        uint256 poolTotalYes;
        uint256 poolTotalNo;
        uint256 commitmentsCount;
        bytes32 circuitHash;
    }

    event Initialized(
        string indexed eventId,
        address indexed oracle,
        uint256 commitDeadline,
        uint256 revealDeadline,
        address guardian,
        uint256 payoutMultiplier,
        PayoutCurve curve,
        uint256 maxMarketSize
    );
    event Commit(address indexed user, bytes32 indexed positionHash, uint256 stake, uint256 timestamp);
    event Committed(address indexed user, bytes32 indexed ticketHash, uint256 amount);
    event Locked();
    event ResultPosted(uint256 indexed outcomeId);
    event ProofVerified(bool success);
    event ProofReceipt(bytes32 indexed nonce, address indexed verifier, bool success);
    event MarketSettled(uint256 indexed winningOutcome);
    event MarketResolved(
        bytes32 indexed outcomeHash,
        uint256 winningStake,
        uint256 totalLiability,
        uint256 netPool,
        uint256 rakePaid,
        uint256 settledAt
    );
    event Claimed(address indexed user, uint256 payout);
    event Refunded(address indexed user, uint256 amount);
    event MaxLiabilityUpdated(uint256 value);
    event FloatAdded(uint256 amount);
    event FloatUsed(uint256 amount);
    event FloatWithdrawn(address indexed to, uint256 amount);
    event GuardianUpdated(address indexed newGuardian);
    event CommitPauseSet(bool paused, address indexed triggeredBy);
    event ClaimPauseSet(bool paused, address indexed triggeredBy);
    event MarketCancelled(address indexed triggeredBy, string reason);
    event EmergencySettled(bytes32 outcomeHash, uint256 winningPool, address indexed triggeredBy);
    event OracleUpdated(address indexed previousOracle, address indexed newOracle);
    event RakeConfigured(uint256 rakeBps);

    error AlreadyInitialized();
    error SettlementInProgress();
    error InvalidPhase(Phase expected, Phase current);
    error InvalidTimestamp();
    error InvalidOracle();
    error InvalidVerifier();
    error InvalidRakeManager();
    error InvalidTreasury();
    error InvalidAmount();
    error TicketNotFound();
    error TicketAlreadyClaimed();
    error TicketLoses();
    error WinningPoolNotSet();
    error NothingToRefund();
    error AlreadySettled();
    error OutcomeAlreadySet();
    error InvalidPayment();
    error InvalidGuardian();
    error InvalidOutcome();
    error CommitPaused();
    error ClaimPaused();
    error NotAuthorized();
    error MarketAlreadyCancelled();
    error InvalidRakeBps();
    error ProofVerificationFailed();
    error ProofOutcomeMismatch();
    error ProofTotalsMismatch();
    error CircuitHashMismatch();
    error InvalidMarketAddress();
    error InvalidPayoutMultiplier();
    error LiabilityExceedsCoverage(uint256 required, uint256 available);
    error ExceedsMarketSize();
    error OutstandingClaims();
    error InvalidProofLayout();
    error InvalidMerkleProof();
    error CommitmentNotFound();

    uint256 public constant WAD = 1e18;
    uint256 public constant MAX_PAYOUT_MULTIPLIER = 5e18; // 5x cap for odds to avoid extreme exposure.
    address public constant ZEN = address(0);

    string public eventId;
    Phase public phase;

    uint256 public commitDeadline;
    uint256 public revealDeadline;

    address public oracle;
    address public verifier;
    address public rakeManager;
    address public treasury;
    address public factory;
    address public guardian;
    bool public commitsPaused;
    bool public claimsPaused;
    uint256 public cancellationTimestamp;
    uint256 public maxMarketSize;
    bytes32 public circuitHash;
    uint256 public marketId;

    string private _cancellationReason;

    uint256 public userEscrow;
    uint256 public houseFloat;
    uint256 public totalLiability;
    uint256 public maxLiability;
    uint256 public winningPool;
    uint256 public winningOutcomeId;
    bool public outcomeSet;
    uint256 public settledAt;
    uint256 public rakePaid;
    uint256 public paidOut;
    uint256 public claimedWinningStake;
    bytes32 public commitmentsRoot;
    bytes32 public winningCommitmentsRoot;
    uint256 public commitmentsCount;
    uint256 public rakeBpsOverride;
    uint256 public floatReservedAtSettlement;

    PayoutCurve public payoutCurve;
    uint256 public payoutMultiplier;

    bool private _initialized;
    bool private _settlementInProgress;
    mapping(bytes32 => bool) public commitmentExists;
    mapping(address => Ticket[]) public userTickets;
    bytes32[] private _commitments;

    modifier onlyPhase(Phase expected) {
        _onlyPhase(expected);
        _;
    }

    modifier onlyOracle() {
        _onlyOracle();
        _;
    }

    modifier onlyAfter(uint256 timestamp) {
        _onlyAfter(timestamp);
        _;
    }

    modifier ifNotSettled() {
        _ifNotSettled();
        _;
    }

    /// @notice Initializes the market clone (ZEN-only collateral).
    function initialize(InitConfig calldata cfg) external {
        if (_initialized) revert AlreadyInitialized();
        if (cfg.oracle == address(0)) revert InvalidOracle();
        if (cfg.verifier == address(0)) revert InvalidVerifier();
        if (cfg.rakeManager == address(0)) revert InvalidRakeManager();
        if (cfg.treasury == address(0)) revert InvalidTreasury();
        if (cfg.guardian == address(0)) revert InvalidGuardian();
        if (cfg.payoutMultiplier == 0 || cfg.payoutMultiplier > MAX_PAYOUT_MULTIPLIER) revert InvalidPayoutMultiplier();
        if (cfg.commitDeadline <= block.timestamp) revert InvalidTimestamp();
        if (cfg.revealDeadline <= cfg.commitDeadline) revert InvalidTimestamp();
        if (cfg.rakeBpsOverride > IRakeManager(cfg.rakeManager).maxRakeBps()) revert InvalidRakeBps();

        eventId = cfg.eventId;
        commitDeadline = cfg.commitDeadline;
        revealDeadline = cfg.revealDeadline;
        oracle = cfg.oracle;
        verifier = cfg.verifier;
        rakeManager = cfg.rakeManager;
        treasury = cfg.treasury;
        factory = msg.sender;
        guardian = cfg.guardian;
        rakeBpsOverride = cfg.rakeBpsOverride;
        payoutMultiplier = cfg.payoutMultiplier;
        payoutCurve = cfg.payoutCurve;
        maxMarketSize = cfg.maxMarketSize;
        circuitHash = IVerifier(cfg.verifier).circuitHash();
        marketId = uint256(uint160(address(this)));

        phase = Phase.Commit;
        _initialized = true;

        emit Initialized(
            eventId, oracle, commitDeadline, revealDeadline, guardian, payoutMultiplier, payoutCurve, maxMarketSize
        );
        if (cfg.rakeBpsOverride > 0) {
            emit RakeConfigured(cfg.rakeBpsOverride);
        }
    }

    /// @notice Allows users to commit a ticket hash with ZEN during the commit phase.
    function commit(uint256 outcomeId, uint256 amount, bytes32 salt) external payable nonReentrant onlyPhase(Phase.Commit) {
        if (block.timestamp >= commitDeadline) revert InvalidTimestamp();
        if (amount == 0) revert InvalidAmount();
        if (_factoryCommitPaused()) revert CommitPaused();
        if (commitsPaused) revert CommitPaused();
        if (msg.value != amount) revert InvalidPayment();
        if (outcomeId > 1) revert InvalidOutcome();

        uint256 potentialPayout = _estimatePayout(amount);
        (uint256 newLiability, uint256 newEscrow, uint256 coverage) =
            _estimateMaxPayoutAfterCommit(amount, potentialPayout);
        if (newLiability > coverage) revert LiabilityExceedsCoverage(newLiability, coverage);
        _enforceMarketSize(newEscrow, houseFloat);
        _syncFactoryAccounting(newEscrow, houseFloat, newLiability);

        userEscrow = newEscrow;
        maxLiability = newLiability;
        commitmentsCount += 1;
        emit MaxLiabilityUpdated(newLiability);

        bytes32 ticketHash = _hashCommit(msg.sender, outcomeId, amount, salt);
        bytes32 leaf = keccak256(abi.encodePacked(ticketHash));
        _commitments.push(leaf);
        userTickets[msg.sender].push(Ticket({commitHash: ticketHash, amount: amount, revealed: false, claimed: false}));
        commitmentExists[ticketHash] = true;

        emit Commit(msg.sender, ticketHash, amount, block.timestamp);
        emit Committed(msg.sender, ticketHash, amount);
    }

    /// @notice Adds house float liquidity for enhanced payouts.
    function fundMarket(uint256 amount) external payable nonReentrant {
        if (msg.sender != treasury && msg.sender != factory && msg.sender != guardian) revert NotAuthorized();
        if (amount == 0 || msg.value != amount) revert InvalidPayment();
        uint256 newFloat = houseFloat + amount;
        _enforceMarketSize(userEscrow, newFloat);
        houseFloat = newFloat;
        emit FloatAdded(amount);
        _syncFactoryAccounting(userEscrow, houseFloat, maxLiability);
    }

    /// @notice Locks the market once the commit deadline has elapsed and stores the canonical commitments root.
    function lock() external onlyPhase(Phase.Commit) onlyAfter(commitDeadline) {
        if (msg.sender != oracle && msg.sender != guardian && msg.sender != factory) revert NotAuthorized();
        if (commitmentsCount == 0) revert InvalidProofLayout();
        commitmentsRoot = _computeMerkleRoot(_commitments);
        winningCommitmentsRoot = commitmentsRoot;
        phase = Phase.Locked;
        emit Locked();
    }

    /// @notice Oracle posts the resulting outcome hash after commits are locked.
    function postResult(uint256 outcomeId) external onlyOracle onlyPhase(Phase.Locked) {
        if (outcomeSet) revert OutcomeAlreadySet();
        winningOutcomeId = outcomeId;
        outcomeSet = true;
        emit ResultPosted(outcomeId);
    }

    /// @notice Verifies a zero-knowledge proof and settles the market atomically.
    function verifyAndSettle(bytes calldata proof, uint256[10] calldata pubSignals)
        external
        onlyPhase(Phase.Locked)
        nonReentrant
    {
        if (phase == Phase.Cancelled) revert MarketAlreadyCancelled();
        if (!outcomeSet) revert WinningPoolNotSet();
        if (commitmentsRoot == bytes32(0) || commitmentsCount == 0) revert InvalidProofLayout();

        SettlementSignals memory signals = _decodeSignals(pubSignals);
        if (signals.commitmentsRoot != commitmentsRoot) revert InvalidProofLayout();
        if (signals.commitmentsCount != commitmentsCount) revert InvalidProofLayout();
        if (signals.marketId != marketId) revert InvalidMarketAddress();
        if (signals.circuitHash != circuitHash) revert CircuitHashMismatch();

        if (signals.winningOutcomeId != winningOutcomeId) revert ProofOutcomeMismatch();

        uint256 expectedPool = signals.poolTotalYes + signals.poolTotalNo;
        if (expectedPool != signals.totalEscrow) revert ProofTotalsMismatch();
        if (signals.totalEscrow != userEscrow) revert ProofTotalsMismatch();
        uint256 appliedRake = appliedRakeBps();
        if (signals.rakeBps != appliedRake) revert InvalidRakeBps();

        uint256 expectedRakeAmount = (signals.totalEscrow * signals.rakeBps) / 10_000;
        uint256 netEscrow = signals.totalEscrow - expectedRakeAmount;
        uint256 netPool = netEscrow + houseFloat;
        if (signals.totalLiability > netPool) revert LiabilityExceedsCoverage(signals.totalLiability, netPool);

        bool success = IVerifier(verifier).verifyProof(proof, pubSignals);
        emit ProofVerified(success);
        emit ProofReceipt(signals.commitmentsRoot, verifier, success);
        if (!success) revert ProofVerificationFailed();

        _settlementInProgress = true;

        rakePaid = expectedRakeAmount;
        if (rakePaid > userEscrow) revert ProofTotalsMismatch();
        if (rakePaid > 0) {
            SafeTransferLib.safeTransferETH(treasury, rakePaid);
        }

        userEscrow = netEscrow;
        winningCommitmentsRoot = commitmentsRoot;
        winningPool = signals.winningOutcomeId == 0 ? signals.poolTotalYes : signals.poolTotalNo;
        totalLiability = signals.totalLiability;
        maxLiability = signals.totalLiability;
        floatReservedAtSettlement = 0;
        settledAt = block.timestamp;
        phase = Phase.Settled;

        uint256 newNetPool = userEscrow + houseFloat;
        if (newNetPool != netPool) revert ProofTotalsMismatch();
        _settlementInProgress = false;
        _syncFactoryAccounting(userEscrow, houseFloat, maxLiability);

        emit MaxLiabilityUpdated(signals.totalLiability);
        emit MarketSettled(winningOutcomeId);
        emit MarketResolved(bytes32(winningOutcomeId), winningPool, totalLiability, newNetPool, rakePaid, settledAt);
    }

    /// @notice Claims winnings by revealing the committed outcome.
    function claim(
        uint256 ticketId,
        uint256 outcomeId,
        bytes32 salt,
        uint256 leafIndex,
        bytes32[] calldata merkleProof
    )
        external
        nonReentrant
        onlyPhase(Phase.Settled)
    {
        if (totalLiability == 0) revert WinningPoolNotSet();
        if (_factoryClaimPaused()) revert ClaimPaused();
        if (claimsPaused) revert ClaimPaused();
        if (phase == Phase.Cancelled) revert MarketAlreadyCancelled();

        Ticket storage ticket = _getTicket(msg.sender, ticketId);
        if (ticket.claimed) revert TicketAlreadyClaimed();

        if (!outcomeSet || outcomeId != winningOutcomeId) revert TicketLoses();

        bytes32 reconstructed = _hashCommit(msg.sender, outcomeId, ticket.amount, salt);
        if (reconstructed != ticket.commitHash) revert TicketLoses();
        if (!commitmentExists[reconstructed]) revert CommitmentNotFound();
        if (winningCommitmentsRoot == bytes32(0)) revert InvalidProofLayout();
        bytes32 leaf = keccak256(abi.encodePacked(reconstructed));
        if (commitmentsCount == 1) {
            if (merkleProof.length != 0 || leaf != winningCommitmentsRoot) revert InvalidMerkleProof();
        } else {
            if (merkleProof.length == 0) revert InvalidMerkleProof();
            if (leafIndex >= commitmentsCount) revert InvalidMerkleProof();
            if (!_verifyMerkle(leaf, winningCommitmentsRoot, merkleProof, leafIndex)) {
                revert InvalidMerkleProof();
            }
        }

        ticket.claimed = true;
        ticket.revealed = true;

        uint256 payout = _estimatePayout(ticket.amount);
        uint256 newPaidOut = paidOut + payout;
        if (newPaidOut > totalLiability) revert LiabilityExceedsCoverage(newPaidOut, totalLiability);
        if (payout > _collateralBalance()) revert LiabilityExceedsCoverage(payout, _collateralBalance());

        paidOut = newPaidOut;
        claimedWinningStake += ticket.amount;
        _applyPayoutAccounting(payout);
        maxLiability = totalLiability - paidOut;
        emit MaxLiabilityUpdated(maxLiability);
        _syncFactoryAccounting(userEscrow, houseFloat, maxLiability);

        SafeTransferLib.safeTransferETH(msg.sender, payout);
        emit Claimed(msg.sender, payout);
    }

    /// @notice Refunds all tickets if the market was not settled before reveal deadline or got cancelled.
    function refund() external nonReentrant ifNotSettled {
        if (phase != Phase.Cancelled) {
            if (phase != Phase.Locked) revert InvalidPhase(Phase.Locked, phase);
            if (block.timestamp <= revealDeadline) revert InvalidTimestamp();
        }
        Ticket[] storage tickets = userTickets[msg.sender];
        uint256 length = tickets.length;
        uint256 refundAmount;

        for (uint256 i = 0; i < length; ++i) {
            Ticket storage ticket = tickets[i];
            if (!ticket.claimed && ticket.amount > 0) {
                uint256 ticketPayout = _estimatePayout(ticket.amount);
                refundAmount += ticket.amount;
                ticket.claimed = true;
                ticket.amount = 0;
                if (ticketPayout <= maxLiability) {
                    maxLiability -= ticketPayout;
                } else {
                    maxLiability = 0;
                }
            }
        }

        if (refundAmount == 0) revert NothingToRefund();

        userEscrow -= refundAmount;
        SafeTransferLib.safeTransferETH(msg.sender, refundAmount);
        emit Refunded(msg.sender, refundAmount);
        _syncFactoryAccounting(userEscrow, houseFloat, maxLiability);
    }

    /// @notice Withdraws leftover float after all claims are satisfied.
    function withdrawFloat(address recipient, uint256 amount) external nonReentrant {
        if (msg.sender != treasury && msg.sender != factory && msg.sender != guardian) revert NotAuthorized();
        if (phase != Phase.Settled) revert InvalidPhase(Phase.Settled, phase);
        if (paidOut < totalLiability) revert OutstandingClaims();
        if (amount == 0 || amount > houseFloat) revert InvalidAmount();
        if (amount > _collateralBalance()) revert LiabilityExceedsCoverage(amount, _collateralBalance());

        houseFloat -= amount;
        SafeTransferLib.safeTransferETH(recipient, amount);
        emit FloatWithdrawn(recipient, amount);
        _syncFactoryAccounting(userEscrow, houseFloat, maxLiability);
    }

    /// @notice Returns the number of tickets a user holds.
    function ticketCount(address user) external view returns (uint256) {
        return userTickets[user].length;
    }

    /// @notice Returns the details of a specific ticket.
    function ticketInfo(address user, uint256 ticketId) external view returns (Ticket memory) {
        Ticket storage ticket = _getTicket(user, ticketId);
        return Ticket({
            commitHash: ticket.commitHash, amount: ticket.amount, revealed: ticket.revealed, claimed: ticket.claimed
        });
    }

    /// @notice Computes the payout a ticket would receive if claimed with provided reveal data.
    function payoutPreview(address user, uint256 ticketId, uint256 outcomeId, bytes32 salt)
        external
        view
        returns (uint256 payout, bool claimable)
    {
        if (phase != Phase.Settled || totalLiability == 0) return (0, false);

        Ticket storage ticket = _getTicket(user, ticketId);
        if (ticket.claimed) return (0, false);

        if (!outcomeSet || outcomeId != winningOutcomeId) return (0, false);

        bytes32 reconstructed = _hashCommit(user, outcomeId, ticket.amount, salt);
        if (reconstructed != ticket.commitHash) return (0, false);

        payout = _estimatePayout(ticket.amount);
        if (payout + paidOut > totalLiability) return (0, false);
        if (payout > _collateralBalance()) return (0, false);
        return (payout, true);
    }

    function remainingPayoutPool() external view returns (uint256) {
        return _collateralBalance();
    }

    /// @notice Returns settlement metadata for indexers/dashboards.
    function resolutionSummary()
        external
        view
        returns (
            bytes32 outcomeHash,
            uint256 winningStake,
            uint256 liability,
            uint256 netPool,
            uint256 rakeAmount,
            uint256 settledTimestamp
        )
    {
        return (bytes32(winningOutcomeId), winningPool, totalLiability, _collateralBalance(), rakePaid, settledAt);
    }

    function appliedRakeBps() public view returns (uint256) {
        uint256 overrideBps = rakeBpsOverride;
        if (overrideBps == 0) {
            return IRakeManager(rakeManager).rakeBps();
        }
        return overrideBps;
    }

    function setGuardian(address newGuardian) external {
        _checkController();
        if (newGuardian == address(0)) revert InvalidGuardian();
        guardian = newGuardian;
        emit GuardianUpdated(newGuardian);
    }

    function setCommitPaused(bool paused) external {
        _checkController();
        commitsPaused = paused;
        emit CommitPauseSet(paused, msg.sender);
    }

    function setClaimPaused(bool paused) external {
        _checkController();
        claimsPaused = paused;
        emit ClaimPauseSet(paused, msg.sender);
    }

    function cancelMarket(string calldata reason) external {
        _checkController();
        if (phase == Phase.Settled) revert AlreadySettled();
        if (phase == Phase.Cancelled) revert MarketAlreadyCancelled();
        phase = Phase.Cancelled;
        cancellationTimestamp = block.timestamp;
        _cancellationReason = reason;
        winningOutcomeId = 0;
        outcomeSet = false;
        winningPool = 0;
        commitsPaused = true;
        claimsPaused = true;
        emit MarketCancelled(msg.sender, reason);
    }

    function emergencySettle(uint256 outcomeId, uint256 declaredWinningPool) external nonReentrant {
        _checkController();
        if (phase != Phase.Locked) revert InvalidPhase(Phase.Locked, phase);
        winningOutcomeId = outcomeId;
        outcomeSet = true;
        uint256 requiredLiability = _estimatePayout(declaredWinningPool);
        uint256 netEscrow = IRakeManager(rakeManager).takeRake(ZEN, userEscrow, rakeBpsOverride);
        rakePaid = userEscrow - netEscrow;
        uint256 coverage = netEscrow + houseFloat;
        if (requiredLiability > coverage) revert LiabilityExceedsCoverage(requiredLiability, coverage);
        if (rakePaid > 0) {
            SafeTransferLib.safeTransferETH(treasury, rakePaid);
        }
        userEscrow = netEscrow;
        totalLiability = requiredLiability;
        maxLiability = requiredLiability;
        winningPool = declaredWinningPool;
        settledAt = block.timestamp;
        phase = Phase.Settled;
        _syncFactoryAccounting(userEscrow, houseFloat, maxLiability);
        emit MaxLiabilityUpdated(maxLiability);
        emit EmergencySettled(bytes32(outcomeId), declaredWinningPool, msg.sender);
        emit MarketSettled(outcomeId);
        emit MarketResolved(bytes32(outcomeId), declaredWinningPool, totalLiability, _collateralBalance(), rakePaid, settledAt);
    }

    function updateOracle(address newOracle) external {
        _checkController();
        if (newOracle == address(0)) revert InvalidOracle();
        address previous = oracle;
        oracle = newOracle;
        emit OracleUpdated(previous, newOracle);
    }

    function cancellationReason() external view returns (string memory) {
        return _cancellationReason;
    }

    /// @notice Estimate future liability for a new commit (for dashboards/testing).
    function previewMaxLiability(uint256 amount) public view returns (uint256) {
        uint256 potentialPayout = _estimatePayout(amount);
        (uint256 newLiability,,) = _estimateMaxPayoutAfterCommit(amount, potentialPayout);
        return newLiability;
    }

    receive() external payable {
        revert InvalidPhase(Phase.Commit, phase);
    }

    // ----------------------- internal utils -----------------------

    function _onlyPhase(Phase expected) internal view {
        if (phase != expected) revert InvalidPhase(expected, phase);
    }

    function _onlyOracle() internal view {
        if (msg.sender != oracle) revert InvalidOracle();
    }

    function _onlyAfter(uint256 timestamp) internal view {
        if (block.timestamp <= timestamp) revert InvalidTimestamp();
    }

    function _ifNotSettled() internal view {
        if (phase == Phase.Settled) revert AlreadySettled();
    }

    function _hashCommit(address user, uint256 outcomeId, uint256 amount, bytes32 salt)
        internal
        view
        returns (bytes32 result)
    {
        result = keccak256(abi.encodePacked(address(this), user, outcomeId, amount, salt));
    }

    function _decodeSignals(uint256[10] calldata pubSignals) internal pure returns (SettlementSignals memory signals) {
        signals.commitmentsRoot = bytes32(pubSignals[0]);
        signals.marketId = pubSignals[1];
        signals.winningOutcomeId = pubSignals[2];
        signals.totalEscrow = pubSignals[3];
        signals.totalLiability = pubSignals[4];
        signals.rakeBps = pubSignals[5];
        signals.poolTotalYes = pubSignals[6];
        signals.poolTotalNo = pubSignals[7];
        signals.commitmentsCount = pubSignals[8];
        signals.circuitHash = bytes32(pubSignals[9]);
    }

    function _getTicket(address user, uint256 ticketId) private view returns (Ticket storage) {
        Ticket[] storage tickets = userTickets[user];
        if (ticketId >= tickets.length) revert TicketNotFound();
        return tickets[ticketId];
    }

    function _collateralBalance() internal view returns (uint256) {
        return address(this).balance;
    }

    function _verifyMerkle(bytes32 leaf, bytes32 root, bytes32[] calldata proof, uint256 index)
        internal
        pure
        returns (bool)
    {
        bytes32 computed = leaf;
        for (uint256 i = 0; i < proof.length; ++i) {
            bytes32 sibling = proof[i];
            if ((index & 1) == 1) {
                computed = keccak256(abi.encodePacked(sibling, computed));
            } else {
                computed = keccak256(abi.encodePacked(computed, sibling));
            }
            index >>= 1;
        }
        return computed == root;
    }

    function _computeMerkleRoot(bytes32[] memory leaves) internal pure returns (bytes32) {
        uint256 n = leaves.length;
        if (n == 0) return bytes32(0);
        while (n > 1) {
            uint256 nextN = (n + 1) >> 1;
            for (uint256 i = 0; i < nextN; ++i) {
                uint256 idx = i << 1;
                bytes32 left = leaves[idx];
                bytes32 right = idx + 1 < n ? leaves[idx + 1] : left;
                leaves[i] = keccak256(abi.encodePacked(left, right));
            }
            n = nextN;
        }
        return leaves[0];
    }

    function _estimatePayout(uint256 stake) internal view returns (uint256) {
        return (stake * payoutMultiplier) / WAD;
    }

    function _estimateMaxPayoutAfterCommit(uint256 amount, uint256 potentialPayout)
        internal
        view
        returns (uint256 newLiability, uint256 newEscrow, uint256 coverage)
    {
        newLiability = maxLiability + potentialPayout;
        newEscrow = userEscrow + amount;
        coverage = _netCoverage(newEscrow, houseFloat);
    }

    function _rakeFor(uint256 amount) internal view returns (uint256) {
        return (amount * appliedRakeBps()) / 10_000;
    }

    function _netCoverage(uint256 escrow, uint256 floatBalance) internal view returns (uint256) {
        uint256 rakeShare = _rakeFor(escrow);
        return escrow - rakeShare + floatBalance;
    }

    function _applyPayoutAccounting(uint256 payout) internal {
        uint256 poolBefore = _collateralBalance();
        if (payout > poolBefore) revert LiabilityExceedsCoverage(payout, poolBefore);
        if (poolBefore == 0) revert LiabilityExceedsCoverage(payout, 0);

        uint256 floatPortion = (houseFloat * payout) / poolBefore;
        if (floatPortion > houseFloat) {
            floatPortion = houseFloat;
        }
        if (floatPortion > 0) {
            houseFloat -= floatPortion;
            emit FloatUsed(floatPortion);
        }
        userEscrow = userEscrow - (payout - floatPortion);
    }

    function _factoryCommitPaused() internal view returns (bool) {
        if (factory.code.length == 0) return false;
        try IMarketFactoryStatus(factory).globalCommitPaused() returns (bool paused) {
            return paused;
        } catch {
            return false;
        }
    }

    function _factoryClaimPaused() internal view returns (bool) {
        if (factory.code.length == 0) return false;
        try IMarketFactoryStatus(factory).globalClaimPaused() returns (bool paused) {
            return paused;
        } catch {
            return false;
        }
    }

    function _checkController() internal view {
        if (_settlementInProgress) revert SettlementInProgress();
        if (msg.sender != factory && msg.sender != guardian) revert NotAuthorized();
    }

    function _enforceMarketSize(uint256 escrowBalance, uint256 floatBalance) internal view {
        uint256 cap = maxMarketSize;
        if (cap == 0) return;
        if (escrowBalance + floatBalance > cap) revert ExceedsMarketSize();
    }

    function _syncFactoryAccounting(uint256 escrowBalance, uint256 floatBalance, uint256 liability) internal {
        if (factory.code.length == 0) return;
        IMarketFactoryRisk(factory).syncAccounting(address(this), escrowBalance, floatBalance, liability);
    }
}
