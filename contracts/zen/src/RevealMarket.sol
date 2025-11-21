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

    struct SettlementSignals {
        uint256 winningStake;
        uint256 totalLiability;
        uint256 grossPool;
        uint256 rakeAmount;
        uint256 payoutMultiplier;
        bytes32 outcomeHash;
        uint256 version;
        bytes32 nonce;
        address market;
        uint256 floatUsed;
        bytes32 commitmentsRoot;
        bytes32 winningCommitmentsRoot;
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
    event ResultPosted(bytes32 indexed outcomeHash);
    event ProofVerified(bool success);
    event ProofReceipt(bytes32 indexed nonce, address indexed verifier, bool success);
    event MarketSettled(bytes32 indexed winningOutcome);
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
    error CommitPaused();
    error ClaimPaused();
    error NotAuthorized();
    error MarketAlreadyCancelled();
    error InvalidRakeBps();
    error ProofVerificationFailed();
    error ProofOutcomeMismatch();
    error ProofTotalsMismatch();
    error ProofVersionMismatch();
    error InvalidProofNonce();
    error ProofNonceUsed();
    error InvalidMarketAddress();
    error InvalidPayoutMultiplier();
    error LiabilityExceedsCoverage(uint256 required, uint256 available);
    error ExceedsMarketSize();
    error OutstandingClaims();
    error InvalidProofLayout();
    error InvalidMerkleProof();
    error CommitmentNotFound();

    uint256 public constant WAD = 1e18;
    uint256 public constant CIRCUIT_VERSION = 2;
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

    string private _cancellationReason;

    uint256 public userEscrow;
    uint256 public houseFloat;
    uint256 public totalLiability;
    uint256 public maxLiability;
    uint256 public winningPool;
    bytes32 public winningOutcomeHash;
    uint256 public settledAt;
    uint256 public rakePaid;
    uint256 public paidOut;
    uint256 public claimedWinningStake;
    bytes32 public lastProofNonce;
    bytes32 public commitmentsRoot;
    bytes32 public winningCommitmentsRoot;
    uint256 public commitmentsCount;
    uint256 public rakeBpsOverride;
    uint256 public floatReservedAtSettlement;

    PayoutCurve public payoutCurve;
    uint256 public payoutMultiplier;

    bool private _initialized;
    bool private _settlementInProgress;
    mapping(bytes32 => bool) internal _consumedProofNonces;
    mapping(bytes32 => bool) public commitmentExists;
    mapping(address => Ticket[]) public userTickets;

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
    function initialize(
        string calldata eventId_,
        uint256 commitDeadline_,
        uint256 revealDeadline_,
        address oracle_,
        address verifier_,
        address rakeManager_,
        address treasury_,
        address guardian_,
        uint256 rakeBpsOverride_,
        uint256 payoutMultiplier_,
        PayoutCurve payoutCurve_,
        uint256 maxMarketSize_
    ) external {
        if (_initialized) revert AlreadyInitialized();
        if (oracle_ == address(0)) revert InvalidOracle();
        if (verifier_ == address(0)) revert InvalidVerifier();
        if (rakeManager_ == address(0)) revert InvalidRakeManager();
        if (treasury_ == address(0)) revert InvalidTreasury();
        if (guardian_ == address(0)) revert InvalidGuardian();
        if (payoutMultiplier_ == 0 || payoutMultiplier_ > MAX_PAYOUT_MULTIPLIER) revert InvalidPayoutMultiplier();
        if (commitDeadline_ <= block.timestamp) revert InvalidTimestamp();
        if (revealDeadline_ <= commitDeadline_) revert InvalidTimestamp();
        uint256 maxRake = IRakeManager(rakeManager_).maxRakeBps();
        if (rakeBpsOverride_ > maxRake) revert InvalidRakeBps();

        eventId = eventId_;
        commitDeadline = commitDeadline_;
        revealDeadline = revealDeadline_;
        oracle = oracle_;
        verifier = verifier_;
        rakeManager = rakeManager_;
        treasury = treasury_;
        factory = msg.sender;
        guardian = guardian_;
        rakeBpsOverride = rakeBpsOverride_;
        payoutMultiplier = payoutMultiplier_;
        payoutCurve = payoutCurve_;
        maxMarketSize = maxMarketSize_;

        phase = Phase.Commit;
        _initialized = true;

        emit Initialized(
            eventId_, oracle_, commitDeadline_, revealDeadline_, guardian_, payoutMultiplier_, payoutCurve_, maxMarketSize_
        );
        if (rakeBpsOverride_ > 0) {
            emit RakeConfigured(rakeBpsOverride_);
        }
    }

    /// @notice Allows users to commit a ticket hash with ZEN during the commit phase.
    function commit(bytes32 ticketHash, uint256 amount) external payable nonReentrant onlyPhase(Phase.Commit) {
        if (block.timestamp >= commitDeadline) revert InvalidTimestamp();
        if (amount == 0) revert InvalidAmount();
        if (_factoryCommitPaused()) revert CommitPaused();
        if (commitsPaused) revert CommitPaused();
        if (msg.value != amount) revert InvalidPayment();

        uint256 potentialPayout = _estimatePayout(amount);
        (uint256 newLiability, uint256 newEscrow, uint256 coverage) =
            _estimateMaxPayoutAfterCommit(amount, potentialPayout);
        if (newLiability > coverage) revert LiabilityExceedsCoverage(newLiability, coverage);
        _enforceMarketSize(newEscrow, houseFloat);
        _syncFactoryAccounting(newEscrow, houseFloat, newLiability);

        userEscrow = newEscrow;
        maxLiability = newLiability;
        commitmentsRoot = keccak256(abi.encodePacked(commitmentsRoot, ticketHash));
        commitmentsCount += 1;
        emit MaxLiabilityUpdated(newLiability);

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

    /// @notice Locks the market once the commit deadline has elapsed.
    function lock() external onlyPhase(Phase.Commit) onlyAfter(commitDeadline) {
        phase = Phase.Locked;
        emit Locked();
    }

    /// @notice Oracle posts the resulting outcome hash after commits are locked.
    function postResult(bytes32 outcomeHash) external onlyOracle onlyPhase(Phase.Locked) {
        if (winningOutcomeHash != bytes32(0)) revert OutcomeAlreadySet();
        winningOutcomeHash = outcomeHash;
        emit ResultPosted(outcomeHash);
    }

    /// @notice Verifies a zero-knowledge proof and settles the market atomically.
    function verifyAndSettle(bytes calldata proof, uint256[12] calldata pubSignals)
        external
        onlyPhase(Phase.Locked)
        nonReentrant
    {
        if (phase == Phase.Cancelled) revert MarketAlreadyCancelled();
        if (winningOutcomeHash == bytes32(0)) revert WinningPoolNotSet();

        SettlementSignals memory signals = _decodeSignals(pubSignals);
        if (signals.outcomeHash != winningOutcomeHash) revert ProofOutcomeMismatch();
        if (signals.version != CIRCUIT_VERSION) revert ProofVersionMismatch();
        if (signals.market != address(this)) revert InvalidMarketAddress();
        if (signals.nonce == bytes32(0)) revert InvalidProofNonce();
        if (_consumedProofNonces[signals.nonce]) revert ProofNonceUsed();
        if (signals.payoutMultiplier != payoutMultiplier) revert InvalidPayoutMultiplier();
        if (signals.payoutMultiplier == 0 || signals.payoutMultiplier > MAX_PAYOUT_MULTIPLIER) {
            revert InvalidPayoutMultiplier();
        }
        if (signals.commitmentsRoot != commitmentsRoot) revert InvalidProofLayout();
        if (signals.winningCommitmentsRoot == bytes32(0)) revert InvalidProofLayout();

        uint256 grossPool = userEscrow + houseFloat;
        if (signals.grossPool != grossPool) revert ProofTotalsMismatch();

        uint256 netEscrow = IRakeManager(rakeManager).takeRake(ZEN, userEscrow, rakeBpsOverride);
        uint256 expectedRake = userEscrow - netEscrow;
        if (signals.rakeAmount != expectedRake) revert ProofTotalsMismatch();

        uint256 liabilityExpected = _estimatePayout(signals.winningStake);
        if (signals.totalLiability != liabilityExpected) revert ProofTotalsMismatch();

        if (signals.floatUsed > houseFloat) revert LiabilityExceedsCoverage(signals.floatUsed, houseFloat);

        uint256 netPool = netEscrow + houseFloat;
        if (signals.floatUsed > netPool) revert LiabilityExceedsCoverage(signals.floatUsed, netPool);
        if (signals.totalLiability > netPool) revert LiabilityExceedsCoverage(signals.totalLiability, netPool);

        bool success = IVerifier(verifier).verifyProof(proof, pubSignals);
        emit ProofVerified(success);
        emit ProofReceipt(signals.nonce, verifier, success);
        if (!success) revert ProofVerificationFailed();

        _consumedProofNonces[signals.nonce] = true;
        lastProofNonce = signals.nonce;
        _settlementInProgress = true;

        winningPool = signals.winningStake;
        totalLiability = signals.totalLiability;
        maxLiability = signals.totalLiability;
        rakePaid = signals.rakeAmount;
        floatReservedAtSettlement = signals.floatUsed;
        if (rakePaid > userEscrow) revert ProofTotalsMismatch();
        if (rakePaid > 0) {
            SafeTransferLib.safeTransferETH(treasury, rakePaid);
        }
        userEscrow = netEscrow;
        winningCommitmentsRoot = signals.winningCommitmentsRoot;
        settledAt = block.timestamp;
        phase = Phase.Settled;

        uint256 newNetPool = userEscrow + houseFloat;
        if (newNetPool != netPool) revert ProofTotalsMismatch();
        _settlementInProgress = false;
        _syncFactoryAccounting(userEscrow, houseFloat, maxLiability);

        emit MaxLiabilityUpdated(signals.totalLiability);
        emit MarketSettled(winningOutcomeHash);
        emit MarketResolved(winningOutcomeHash, winningPool, totalLiability, newNetPool, rakePaid, settledAt);
    }

    /// @notice Claims winnings by revealing the committed outcome.
    function claim(uint256 ticketId, string calldata outcome, bytes32 salt, bytes32[] calldata merkleProof)
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

        bytes32 outcomeHash = _hashOutcome(outcome);
        if (outcomeHash != winningOutcomeHash) revert TicketLoses();

        bytes32 reconstructed = _hashCommit(msg.sender, outcomeHash, salt);
        if (reconstructed != ticket.commitHash) revert TicketLoses();
        if (!commitmentExists[reconstructed]) revert CommitmentNotFound();
        if (winningCommitmentsRoot == bytes32(0)) revert InvalidProofLayout();
        if (merkleProof.length == 0) {
            if (reconstructed != winningCommitmentsRoot) revert InvalidMerkleProof();
        } else if (!_verifyMerkle(reconstructed, winningCommitmentsRoot, merkleProof)) {
            revert InvalidMerkleProof();
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
    function payoutPreview(address user, uint256 ticketId, string calldata outcome, bytes32 salt)
        external
        view
        returns (uint256 payout, bool claimable)
    {
        if (phase != Phase.Settled || totalLiability == 0) return (0, false);

        Ticket storage ticket = _getTicket(user, ticketId);
        if (ticket.claimed) return (0, false);

        bytes32 outcomeHash = _hashOutcome(outcome);
        if (outcomeHash != winningOutcomeHash) return (0, false);

        bytes32 reconstructed = _hashCommit(user, outcomeHash, salt);
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
        return (winningOutcomeHash, winningPool, totalLiability, _collateralBalance(), rakePaid, settledAt);
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
        winningOutcomeHash = bytes32(0);
        winningPool = 0;
        commitsPaused = true;
        claimsPaused = true;
        emit MarketCancelled(msg.sender, reason);
    }

    function emergencySettle(bytes32 outcomeHash, uint256 declaredWinningPool) external nonReentrant {
        _checkController();
        if (phase != Phase.Locked) revert InvalidPhase(Phase.Locked, phase);
        winningOutcomeHash = outcomeHash;
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
        emit EmergencySettled(outcomeHash, declaredWinningPool, msg.sender);
        emit MarketSettled(outcomeHash);
        emit MarketResolved(outcomeHash, declaredWinningPool, totalLiability, _collateralBalance(), rakePaid, settledAt);
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

    function _hashOutcome(string memory outcome) internal pure returns (bytes32 result) {
        bytes memory data = bytes(outcome);
        assembly {
            result := keccak256(add(data, 0x20), mload(data))
        }
    }

    function _hashCommit(address user, bytes32 outcomeHash, bytes32 salt) internal pure returns (bytes32 result) {
        assembly {
            let ptr := mload(0x40)
            mstore(ptr, shl(96, user))
            mstore(add(ptr, 0x14), outcomeHash)
            mstore(add(ptr, 0x34), salt)
            result := keccak256(ptr, 0x54)
            mstore(0x40, add(ptr, 0x60))
        }
    }

    function _decodeSignals(uint256[12] calldata pubSignals) internal pure returns (SettlementSignals memory signals) {
        signals.winningStake = pubSignals[0];
        signals.totalLiability = pubSignals[1];
        signals.grossPool = pubSignals[2];
        signals.rakeAmount = pubSignals[3];
        signals.payoutMultiplier = pubSignals[4];
        signals.outcomeHash = bytes32(pubSignals[5]);
        signals.version = pubSignals[6];
        signals.nonce = bytes32(pubSignals[7]);
        signals.market = _decodeMarketAddress(pubSignals[8]);
        signals.floatUsed = pubSignals[9];
        signals.commitmentsRoot = bytes32(pubSignals[10]);
        signals.winningCommitmentsRoot = bytes32(pubSignals[11]);
    }

    function _decodeMarketAddress(uint256 raw) private pure returns (address) {
        if (raw >> 160 != 0) revert InvalidMarketAddress();
        unchecked {
            // casting to uint160 is safe because upper 96 bits are enforced to be zero above
            // forge-lint: disable-next-line(unsafe-typecast)
            return address(uint160(raw));
        }
    }

    function _getTicket(address user, uint256 ticketId) private view returns (Ticket storage) {
        Ticket[] storage tickets = userTickets[user];
        if (ticketId >= tickets.length) revert TicketNotFound();
        return tickets[ticketId];
    }

    function _collateralBalance() internal view returns (uint256) {
        return address(this).balance;
    }

    function _verifyMerkle(bytes32 leaf, bytes32 root, bytes32[] calldata proof) internal pure returns (bool) {
        bytes32 computed = leaf;
        for (uint256 i = 0; i < proof.length; ++i) {
            computed = keccak256(abi.encodePacked(computed, proof[i]));
        }
        return computed == root;
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
