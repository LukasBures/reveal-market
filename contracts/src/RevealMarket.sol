// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {SafeTransferLib} from "solmate/utils/SafeTransferLib.sol";
import {ERC20} from "solmate/tokens/ERC20.sol";

import {IRakeManager} from "./interfaces/IRakeManager.sol";
import {IVerifier} from "./interfaces/IVerifier.sol";
import {IMarketFactoryStatus} from "./interfaces/IMarketFactoryStatus.sol";

/// @title RevealMarket
/// @notice Commit-reveal prediction market supporting zero-knowledge settlement.
contract RevealMarket is ReentrancyGuard {
    enum Phase {
        Commit,
        Locked,
        Settled,
        Cancelled
    }

    struct Ticket {
        bytes32 commitHash;
        uint256 amount;
        bool revealed;
        bool claimed;
    }

    event Initialized(
        string indexed eventId,
        address indexed oracle,
        uint256 commitDeadline,
        uint256 revealDeadline,
        address collateral,
        address guardian
    );
    event Committed(address indexed user, bytes32 indexed ticketHash, uint256 amount);
    event Locked();
    event ProofVerified(bool success);
    event Settled(bytes32 indexed winningOutcomeHash);
    event Claimed(address indexed user, uint256 payout);
    event Refunded(address indexed user, uint256 amount);
    event ResultPosted(bytes32 indexed outcomeHash);
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

    string public eventId;
    Phase public phase;

    uint256 public commitDeadline;
    uint256 public revealDeadline;

    address public oracle;
    address public verifier;
    address public rakeManager;
    address public treasury;
    address public factory;
    address public collateral;
    address public guardian;
    bool public commitsPaused;
    bool public claimsPaused;
    uint256 public cancellationTimestamp;

    string private _cancellationReason;

    uint256 public totalPool;
    uint256 public winningPool;
    bytes32 public winningOutcomeHash;

    uint256 public claimedWinningStake;
    uint256 public paidOut;

    bool private _initialized;
    bool private _settlementInProgress;
    uint256 public rakeBpsOverride;

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

    /// @notice Initializes the market clone.
    /// @param eventId_ Market identifier.
    /// @param commitDeadline_ Timestamp after which commits close.
    /// @param revealDeadline_ Timestamp after which refunds unlock if unsettled.
    /// @param oracle_ Oracle authorized to post results.
    /// @param verifier_ Zero-knowledge verifier contract.
    /// @param rakeManager_ Rake manager contract.
    /// @param treasury_ Treasury that receives rake.
    /// @param collateral_ Collateral token used for staking (address(0) for native ETH).
    /// @param guardian_ Guardian able to pause/emergency-control the market.
    function initialize(
        string calldata eventId_,
        uint256 commitDeadline_,
        uint256 revealDeadline_,
        address oracle_,
        address verifier_,
        address rakeManager_,
        address treasury_,
        address collateral_,
        address guardian_,
        uint256 rakeBpsOverride_
    ) external {
        if (_initialized) revert AlreadyInitialized();
        if (oracle_ == address(0)) revert InvalidOracle();
        if (verifier_ == address(0)) revert InvalidVerifier();
        if (rakeManager_ == address(0)) revert InvalidRakeManager();
        if (treasury_ == address(0)) revert InvalidTreasury();
        if (guardian_ == address(0)) revert InvalidGuardian();
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
        collateral = collateral_;
        guardian = guardian_;
        rakeBpsOverride = rakeBpsOverride_;

        phase = Phase.Commit;
        _initialized = true;

        emit Initialized(eventId_, oracle_, commitDeadline_, revealDeadline_, collateral_, guardian_);
        if (rakeBpsOverride_ > 0) {
            emit RakeConfigured(rakeBpsOverride_);
        }
    }

    /// @notice Allows users to commit a ticket hash with funds during the commit phase.
    function commit(bytes32 ticketHash, uint256 amount) external payable onlyPhase(Phase.Commit) {
        if (block.timestamp >= commitDeadline) revert InvalidTimestamp();
        if (amount == 0) revert InvalidAmount();
        if (_factoryCommitPaused()) revert CommitPaused();
        if (commitsPaused) revert CommitPaused();

        if (collateral == address(0)) {
            if (msg.value != amount) revert InvalidPayment();
        } else {
            if (msg.value != 0) revert InvalidPayment();
            SafeTransferLib.safeTransferFrom(ERC20(collateral), msg.sender, address(this), amount);
        }

        userTickets[msg.sender].push(Ticket({commitHash: ticketHash, amount: amount, revealed: false, claimed: false}));
        totalPool += amount;

        emit Committed(msg.sender, ticketHash, amount);
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

    /// @notice Verifies a zero-knowledge proof and settles the market.
    function verifyProof(bytes calldata proof, uint256[4] calldata pubSignals) external onlyPhase(Phase.Locked) nonReentrant {
        if (phase == Phase.Cancelled) revert MarketAlreadyCancelled();
        if (winningOutcomeHash == bytes32(0)) revert WinningPoolNotSet();

        bool success = IVerifier(verifier).verifyProof(proof, pubSignals);
        emit ProofVerified(success);
        if (!success) revert WinningPoolNotSet();

        uint256 declaredWinningPool = pubSignals[0];
        _finalizeSettlement(winningOutcomeHash, declaredWinningPool);
    }

    /// @notice Claims winnings by revealing the committed outcome.
    function claim(uint256 ticketId, string calldata outcome, bytes32 salt) external nonReentrant onlyPhase(Phase.Settled) {
        if (winningPool == 0) revert WinningPoolNotSet();
        if (_factoryClaimPaused()) revert ClaimPaused();
        if (claimsPaused) revert ClaimPaused();
        if (phase == Phase.Cancelled) revert MarketAlreadyCancelled();

        Ticket storage ticket = _getTicket(msg.sender, ticketId);
        if (ticket.claimed) revert TicketAlreadyClaimed();

        bytes32 outcomeHash = _hashOutcome(outcome);
        if (outcomeHash != winningOutcomeHash) revert TicketLoses();

        bytes32 reconstructed = _hashCommit(msg.sender, outcomeHash, salt);
        if (reconstructed != ticket.commitHash) revert TicketLoses();

        ticket.claimed = true;
        ticket.revealed = true;

        uint256 newClaimedStake = claimedWinningStake + ticket.amount;
        uint256 payout;
        if (newClaimedStake >= winningPool) {
            payout = _collateralBalance();
        } else {
            payout = (ticket.amount * totalPool) / winningPool;
        }
        claimedWinningStake = newClaimedStake;
        paidOut += payout;

        if (collateral == address(0)) {
            SafeTransferLib.safeTransferETH(msg.sender, payout);
        } else {
            SafeTransferLib.safeTransfer(ERC20(collateral), msg.sender, payout);
        }
        emit Claimed(msg.sender, payout);
    }

    /// @notice Refunds all tickets if the market was not settled before reveal deadline.
    function refund() external nonReentrant ifNotSettled {
        Ticket[] storage tickets = userTickets[msg.sender];
        uint256 length = tickets.length;
        uint256 refundAmount;

        for (uint256 i = 0; i < length; ++i) {
            Ticket storage ticket = tickets[i];
            if (!ticket.claimed && ticket.amount > 0) {
                refundAmount += ticket.amount;
                ticket.claimed = true;
                ticket.amount = 0;
            }
        }

        if (refundAmount == 0) revert NothingToRefund();
        if (phase != Phase.Cancelled && block.timestamp <= revealDeadline) revert InvalidTimestamp();

        totalPool -= refundAmount;
        if (collateral == address(0)) {
            SafeTransferLib.safeTransferETH(msg.sender, refundAmount);
        } else {
            SafeTransferLib.safeTransfer(ERC20(collateral), msg.sender, refundAmount);
        }
        emit Refunded(msg.sender, refundAmount);
    }

    /// @notice Returns the number of tickets a user holds.
    function ticketCount(address user) external view returns (uint256) {
        return userTickets[user].length;
    }

    /// @notice Returns the details of a specific ticket.
    function ticketInfo(address user, uint256 ticketId) external view returns (Ticket memory) {
        Ticket storage ticket = _getTicket(user, ticketId);
        return Ticket({
            commitHash: ticket.commitHash,
            amount: ticket.amount,
            revealed: ticket.revealed,
            claimed: ticket.claimed
        });
    }

    /// @notice Computes the payout a ticket would receive if claimed with provided reveal data.
    function payoutPreview(
        address user,
        uint256 ticketId,
        string calldata outcome,
        bytes32 salt
    ) external view returns (uint256 payout, bool claimable) {
        if (phase != Phase.Settled || winningPool == 0) return (0, false);

        Ticket storage ticket = _getTicket(user, ticketId);
        if (ticket.claimed) return (0, false);

        bytes32 outcomeHash = _hashOutcome(outcome);
        if (outcomeHash != winningOutcomeHash) return (0, false);

        bytes32 reconstructed = _hashCommit(user, outcomeHash, salt);
        if (reconstructed != ticket.commitHash) return (0, false);

        uint256 newClaimedStake = claimedWinningStake + ticket.amount;
        if (newClaimedStake >= winningPool) {
            payout = _collateralBalance();
        } else {
            payout = (ticket.amount * totalPool) / winningPool;
        }
        return (payout, true);
    }

    function remainingPayoutPool() external view returns (uint256) {
        return _collateralBalance();
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
        _finalizeSettlement(outcomeHash, declaredWinningPool);
        emit EmergencySettled(outcomeHash, declaredWinningPool, msg.sender);
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

    function _getTicket(address user, uint256 ticketId) private view returns (Ticket storage) {
        Ticket[] storage tickets = userTickets[user];
        if (ticketId >= tickets.length) revert TicketNotFound();
        return tickets[ticketId];
    }

    function _collateralBalance() internal view returns (uint256) {
        if (collateral == address(0)) {
            return address(this).balance;
        }
        return ERC20(collateral).balanceOf(address(this));
    }

    function _finalizeSettlement(bytes32 outcomeHash, uint256 declaredWinningPool) internal {
        if (declaredWinningPool == 0 || declaredWinningPool > totalPool) revert WinningPoolNotSet();

        winningPool = declaredWinningPool;
        _settlementInProgress = true;
        uint256 netPool = IRakeManager(rakeManager).takeRake(collateral, totalPool, rakeBpsOverride);
        uint256 rakeAmount = totalPool - netPool;
        if (rakeAmount > 0) {
            if (collateral == address(0)) {
                SafeTransferLib.safeTransferETH(treasury, rakeAmount);
            } else {
                SafeTransferLib.safeTransfer(ERC20(collateral), treasury, rakeAmount);
            }
        }
        totalPool = netPool;

        phase = Phase.Settled;
        _settlementInProgress = false;
        emit Settled(outcomeHash);
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
}
