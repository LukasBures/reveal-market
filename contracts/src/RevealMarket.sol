// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol"; // Protects against reentrancy on state mutating flows.
import {SafeTransferLib} from "solmate/utils/SafeTransferLib.sol"; // Lightweight transfer helper for ETH and ERC20.
import {ERC20} from "solmate/tokens/ERC20.sol"; // Minimal ERC20 interface for collateral interactions.

import {IRakeManager} from "./interfaces/IRakeManager.sol"; // Interface for deducting rake and reading limits.
import {IVerifier} from "./interfaces/IVerifier.sol"; // Interface for verifying zero-knowledge proofs.
import {IMarketFactoryStatus} from "./interfaces/IMarketFactoryStatus.sol"; // Interface allowing markets to read global pauses.

/**
 * @dev Architectural overview
 *
 * RevealMarket is a stateful commit → reveal → settle engine with the following invariants:
 *   1. Users only reveal their bets after the oracle posts a result, preserving private order flow while the market is live.
 *   2. Settlement is provably correct through Groth16 public signals (winningPool, totalPool, outcome hash, version, nonce, market address).
 *   3. Guardians/factory maintain fine-grained controls (pauses, emergency settle, cancellation) for operational safety.
 *
 * Storage is intentionally verbose (track totalPool, winningPool, claimed stake, paidOut) to support both accounting and invariant tests.
 * All external functions either mutate state via guarded modifiers (phase/settlement locks) or run as pure view helpers for indexers.
 *
 * When integrating, remember the workflow:
 *   - `initialize` is called once by the factory clone.
 *   - During commit phase, `commit` accepts hashed tickets (hash(user, outcomeHash, salt)) for ERC20 or native collateral.
 *   - Anyone may call `lock` after the commit deadline, then the oracle posts the result via `postResult`.
 *   - Settlement requires submitting a Groth16 proof to `verifyProof`; on success we emit `ProofReceipt` + `MarketResolved`.
 *   - Winners call `claim` with their plaintext outcome+salt, and losers or cancelled markets rely on `refund`.
 *
 * Phases are encoded via the `Phase` enum so that invariant tooling can assert monotonic state transitions.
 */

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
    event ProofReceipt(bytes32 indexed nonce, address indexed verifier, bool success);
    event Settled(bytes32 indexed winningOutcomeHash);
    event MarketResolved(
        bytes32 indexed outcomeHash, uint256 winningStake, uint256 netPayoutPool, uint256 rakePaid, uint256 settledAt
    );
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
    error ProofVerificationFailed();
    error ProofOutcomeMismatch();
    error ProofTotalsMismatch();
    error ProofVersionMismatch();
    error InvalidProofNonce();
    error ProofNonceUsed();
    error InvalidMarketAddress();

    string public eventId; // External identifier for the market.
    Phase public phase; // Current lifecycle phase.

    uint256 public commitDeadline; // Timestamp after which commits close.
    uint256 public revealDeadline; // Timestamp after which refunds unlock if unsettled.

    address public oracle; // Oracle authorized to post results.
    address public verifier; // Verifier contract authorized for ZK proofs.
    address public rakeManager; // Rake manager contract for fee logic.
    address public treasury; // Treasury receiving rake transfers.
    address public factory; // Factory that deployed this market.
    address public collateral; // Collateral token (zero address indicates native).
    address public guardian; // Guardian empowered to pause/emergency settle.
    bool public commitsPaused; // Per-market commit pause flag.
    bool public claimsPaused; // Per-market claim pause flag.
    uint256 public cancellationTimestamp; // Timestamp of cancellation (if cancelled).

    string private _cancellationReason; // Human-readable reason supplied during cancellation.

    uint256 public totalPool; // Aggregate collateral currently held (post-rake when settled).
    uint256 public winningPool; // Total stake attributed to the winning side.
    bytes32 public winningOutcomeHash; // Hash of the winning outcome string.
    uint256 public settledAt; // Timestamp when settlement finalized.
    uint256 public rakePaid; // Amount of rake routed to treasury for this market.

    uint256 public claimedWinningStake; // Amount of winning stake that has already claimed.
    uint256 public paidOut; // Total collateral paid out to claimants.
    bytes32 public lastProofNonce; // Latest proof nonce accepted for settlement.

    bool private _initialized; // Tracks whether initialize has already run.
    bool private _settlementInProgress; // Prevents concurrent controller actions during settlement.
    uint256 public rakeBpsOverride; // Optional per-market rake override.
    mapping(bytes32 => bool) internal _consumedProofNonces; // Tracks used proof nonces to block replays.

    uint256 public constant CIRCUIT_VERSION = 1; // Hard-coded version gates proof circuits.

    mapping(address => Ticket[]) public userTickets; // Each participant’s list of tickets.

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
        if (_initialized) revert AlreadyInitialized(); // Guard against double initialization.
        if (oracle_ == address(0)) revert InvalidOracle(); // Require oracle address.
        if (verifier_ == address(0)) revert InvalidVerifier(); // Require verifier address.
        if (rakeManager_ == address(0)) revert InvalidRakeManager(); // Require rake manager address.
        if (treasury_ == address(0)) revert InvalidTreasury(); // Require treasury destination.
        if (guardian_ == address(0)) revert InvalidGuardian(); // Require guardian role to be set.
        if (commitDeadline_ <= block.timestamp) revert InvalidTimestamp(); // Commit window must be in future.
        if (revealDeadline_ <= commitDeadline_) revert InvalidTimestamp(); // Reveal deadline must follow commit deadline.
        uint256 maxRake = IRakeManager(rakeManager_).maxRakeBps(); // Fetch allowable cap from manager.
        if (rakeBpsOverride_ > maxRake) revert InvalidRakeBps(); // Enforce cap.

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

        phase = Phase.Commit; // Markets always start in the commit phase.
        _initialized = true; // Lock initialization path.

        emit Initialized(eventId_, oracle_, commitDeadline_, revealDeadline_, collateral_, guardian_);
        if (rakeBpsOverride_ > 0) {
            emit RakeConfigured(rakeBpsOverride_);
        }
    }

    /// @notice Allows users to commit a ticket hash with funds during the commit phase.
    function commit(bytes32 ticketHash, uint256 amount) external payable onlyPhase(Phase.Commit) {
        if (block.timestamp >= commitDeadline) revert InvalidTimestamp(); // Deadline guard.
        if (amount == 0) revert InvalidAmount(); // Require positive stake.
        if (_factoryCommitPaused()) revert CommitPaused(); // Respect factory pause knobs.
        if (commitsPaused) revert CommitPaused(); // Respect per-market pause knobs.

        if (collateral == address(0)) {
            if (msg.value != amount) revert InvalidPayment();
        } else {
            if (msg.value != 0) revert InvalidPayment();
            SafeTransferLib.safeTransferFrom(ERC20(collateral), msg.sender, address(this), amount);
        }

        userTickets[msg.sender].push(Ticket({commitHash: ticketHash, amount: amount, revealed: false, claimed: false})); // Store ticket.
        totalPool += amount; // Track funds entering the pool.

        emit Committed(msg.sender, ticketHash, amount);
    }

    /// @notice Locks the market once the commit deadline has elapsed.
    function lock() external onlyPhase(Phase.Commit) onlyAfter(commitDeadline) {
        phase = Phase.Locked; // Transition to locked state so commits halt.
        emit Locked();
    }

    /// @notice Oracle posts the resulting outcome hash after commits are locked.
    function postResult(bytes32 outcomeHash) external onlyOracle onlyPhase(Phase.Locked) {
        if (winningOutcomeHash != bytes32(0)) revert OutcomeAlreadySet(); // Prevent result overwrite.
        winningOutcomeHash = outcomeHash; // Store the oracle-supplied hash.
        emit ResultPosted(outcomeHash);
    }

    /// @notice Verifies a zero-knowledge proof and settles the market.
    function verifyProof(bytes calldata proof, uint256[6] calldata pubSignals) external onlyPhase(Phase.Locked) nonReentrant {
        if (phase == Phase.Cancelled) revert MarketAlreadyCancelled(); // Prevent settlement on cancelled market.
        if (winningOutcomeHash == bytes32(0)) revert WinningPoolNotSet(); // Oracle result must exist.

        uint256 declaredWinningPool = pubSignals[0];
        uint256 proofTotalPool = pubSignals[1];
        bytes32 proofOutcomeHash = bytes32(pubSignals[2]);
        uint256 proofVersion = pubSignals[3];
        bytes32 proofNonce = bytes32(pubSignals[4]);
        address proofMarket = _decodeMarketAddress(pubSignals[5]);

        if (proofOutcomeHash != winningOutcomeHash) revert ProofOutcomeMismatch(); // Proof outcome must match oracle result.
        if (proofTotalPool != totalPool) revert ProofTotalsMismatch(); // Guard against mismatched total pool.
        if (proofVersion != CIRCUIT_VERSION) revert ProofVersionMismatch(); // Ensure proof version compatibility.
        if (declaredWinningPool == 0 || declaredWinningPool > proofTotalPool) revert WinningPoolNotSet(); // Validate declared stakes.
        if (proofMarket != address(this)) revert InvalidMarketAddress(); // Prevent cross-market replays.
        if (proofNonce == bytes32(0)) revert InvalidProofNonce();
        if (_consumedProofNonces[proofNonce]) revert ProofNonceUsed();

        bool success = IVerifier(verifier).verifyProof(proof, pubSignals); // Delegate to verifier contract.
        emit ProofVerified(success); // Emit event regardless of result.
        emit ProofReceipt(proofNonce, verifier, success);
        if (!success) revert ProofVerificationFailed(); // Shield against false positives.

        _consumedProofNonces[proofNonce] = true;
        lastProofNonce = proofNonce;

        _finalizeSettlement(winningOutcomeHash, declaredWinningPool); // Apply settlement state transitions.
    }

    /// @notice Claims winnings by revealing the committed outcome.
    function claim(uint256 ticketId, string calldata outcome, bytes32 salt)
        external
        nonReentrant
        onlyPhase(Phase.Settled)
    {
        if (winningPool == 0) revert WinningPoolNotSet(); // Settlement must have set winning pool.
        if (_factoryClaimPaused()) revert ClaimPaused(); // Honor factory-level pause.
        if (claimsPaused) revert ClaimPaused(); // Honor per-market pause.
        if (phase == Phase.Cancelled) revert MarketAlreadyCancelled(); // Block claims after cancellation.

        Ticket storage ticket = _getTicket(msg.sender, ticketId); // Load referenced ticket.
        if (ticket.claimed) revert TicketAlreadyClaimed(); // Avoid double-claims.

        bytes32 outcomeHash = _hashOutcome(outcome); // Hash revealed outcome.
        if (outcomeHash != winningOutcomeHash) revert TicketLoses(); // Must match winning hash.

        bytes32 reconstructed = _hashCommit(msg.sender, outcomeHash, salt); // Recreate commit hash.
        if (reconstructed != ticket.commitHash) revert TicketLoses(); // Ensure reveal tied to commitment.

        ticket.claimed = true; // Mark as claimed before transferring.
        ticket.revealed = true; // Flag that this ticket has been revealed.

        uint256 newClaimedStake = claimedWinningStake + ticket.amount;
        uint256 payout;
        if (newClaimedStake >= winningPool) {
            payout = _collateralBalance(); // Final claimer sweeps remainder to avoid rounding dust.
        } else {
            payout = (ticket.amount * totalPool) / winningPool; // Otherwise pay proportionally.
        }
        claimedWinningStake = newClaimedStake; // Persist running total of claimed stake.
        paidOut += payout; // Track aggregate payouts for accounting.

        if (collateral == address(0)) {
            SafeTransferLib.safeTransferETH(msg.sender, payout);
        } else {
            SafeTransferLib.safeTransfer(ERC20(collateral), msg.sender, payout);
        }
        emit Claimed(msg.sender, payout);
    }

    /// @notice Refunds all tickets if the market was not settled before reveal deadline.
    function refund() external nonReentrant ifNotSettled {
        if (phase != Phase.Cancelled) {
            if (phase != Phase.Locked) revert InvalidPhase(Phase.Locked, phase); // Refunds only after commit window closed.
            if (block.timestamp <= revealDeadline) revert InvalidTimestamp(); // Require reveal deadline to have elapsed.
        }
        Ticket[] storage tickets = userTickets[msg.sender]; // Pull caller tickets into memory pointer.
        uint256 length = tickets.length; // Cache length for gas.
        uint256 refundAmount; // Accumulates total refund due.

        for (uint256 i = 0; i < length; ++i) {
            Ticket storage ticket = tickets[i]; // Inspect each ticket.
            if (!ticket.claimed && ticket.amount > 0) {
                refundAmount += ticket.amount; // Add refundable stake.
                ticket.claimed = true; // Prevent future refunds/claims.
                ticket.amount = 0; // Zero ticket balance to avoid reuse.
            }
        }

        if (refundAmount == 0) revert NothingToRefund(); // Bail out when nothing refundable.

        totalPool -= refundAmount; // Reduce pool to account for refunded stake.
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
            commitHash: ticket.commitHash, amount: ticket.amount, revealed: ticket.revealed, claimed: ticket.claimed
        });
    }

    /// @notice Computes the payout a ticket would receive if claimed with provided reveal data.
    function payoutPreview(address user, uint256 ticketId, string calldata outcome, bytes32 salt)
        external
        view
        returns (uint256 payout, bool claimable)
    {
        if (phase != Phase.Settled || winningPool == 0) return (0, false); // Only meaningful after settlement.

        Ticket storage ticket = _getTicket(user, ticketId); // Load ticket under inspection.
        if (ticket.claimed) return (0, false); // Already claimed → cannot claim again.

        bytes32 outcomeHash = _hashOutcome(outcome); // Hash proposed outcome.
        if (outcomeHash != winningOutcomeHash) return (0, false); // Must match winning hash.

        bytes32 reconstructed = _hashCommit(user, outcomeHash, salt); // Recreate commit.
        if (reconstructed != ticket.commitHash) return (0, false); // Must match stored commit hash.

        uint256 newClaimedStake = claimedWinningStake + ticket.amount;
        if (newClaimedStake >= winningPool) {
            payout = _collateralBalance();
        } else {
            payout = (ticket.amount * totalPool) / winningPool;
        }
        return (payout, true);
    }

    function remainingPayoutPool() external view returns (uint256) {
        return _collateralBalance(); // Mirror helper result (available collateral).
    }

    /// @notice Returns settlement metadata for indexers/dashboards.
    function resolutionSummary()
        external
        view
        returns (
            bytes32 outcomeHash,
            uint256 winningStake,
            uint256 netPool,
            uint256 rakeAmount,
            uint256 settledTimestamp
        )
    {
        return (winningOutcomeHash, winningPool, totalPool, rakePaid, settledAt);
    }

    function appliedRakeBps() public view returns (uint256) {
        uint256 overrideBps = rakeBpsOverride; // Cache override to avoid double reads.
        if (overrideBps == 0) {
            return IRakeManager(rakeManager).rakeBps(); // Fall back to shared manager value.
        }
        return overrideBps; // Otherwise surface the override.
    }

    function setGuardian(address newGuardian) external {
        _checkController(); // Restrict to factory or guardian.
        if (newGuardian == address(0)) revert InvalidGuardian(); // Disallow zero guardian.
        guardian = newGuardian; // Store replacement guardian.
        emit GuardianUpdated(newGuardian); // Emit change for indexers.
    }

    function setCommitPaused(bool paused) external {
        _checkController(); // Restrict to factory or guardian.
        commitsPaused = paused; // Flip commit pause flag.
        emit CommitPauseSet(paused, msg.sender); // Emit for transparency.
    }

    function setClaimPaused(bool paused) external {
        _checkController(); // Restrict to factory or guardian.
        claimsPaused = paused; // Flip claim pause flag.
        emit ClaimPauseSet(paused, msg.sender); // Emit for transparency.
    }

    function cancelMarket(string calldata reason) external {
        _checkController(); // Restrict to factory or guardian.
        if (phase == Phase.Settled) revert AlreadySettled(); // Cannot cancel post-settlement.
        if (phase == Phase.Cancelled) revert MarketAlreadyCancelled(); // Avoid double cancellation.
        phase = Phase.Cancelled; // Transition to cancelled state.
        cancellationTimestamp = block.timestamp; // Record timestamp for reference.
        _cancellationReason = reason; // Persist user-provided reason.
        winningOutcomeHash = bytes32(0); // Clear winner hash.
        winningPool = 0; // Clear winner pool.
        commitsPaused = true; // Freeze commits going forward.
        claimsPaused = true; // Freeze claims as well.
        emit MarketCancelled(msg.sender, reason); // Emit event.
    }

    function emergencySettle(bytes32 outcomeHash, uint256 declaredWinningPool) external nonReentrant {
        _checkController(); // Restrict to factory or guardian.
        if (phase != Phase.Locked) revert InvalidPhase(Phase.Locked, phase); // Only allowed before settlement completes.
        winningOutcomeHash = outcomeHash; // Override winner hash.
        _finalizeSettlement(outcomeHash, declaredWinningPool); // Finalize payouts.
        emit EmergencySettled(outcomeHash, declaredWinningPool, msg.sender); // Emit event for audit trail.
    }

    function updateOracle(address newOracle) external {
        _checkController(); // Restrict to factory or guardian.
        if (newOracle == address(0)) revert InvalidOracle(); // Require non-zero oracle.
        address previous = oracle; // Snapshot current oracle.
        oracle = newOracle; // Assign new oracle.
        emit OracleUpdated(previous, newOracle); // Emit change.
    }

    function cancellationReason() external view returns (string memory) {
        return _cancellationReason; // Provide reason to off-chain callers.
    }

    receive() external payable {
        revert InvalidPhase(Phase.Commit, phase); // Reject stray ETH transfers outside commit().
    }

    // ----------------------- internal utils -----------------------

    function _onlyPhase(Phase expected) internal view {
        if (phase != expected) revert InvalidPhase(expected, phase); // Enforce strict phase progression.
    }

    function _onlyOracle() internal view {
        if (msg.sender != oracle) revert InvalidOracle(); // Restrict call to oracle.
    }

    function _onlyAfter(uint256 timestamp) internal view {
        if (block.timestamp <= timestamp) revert InvalidTimestamp(); // Require timestamp to have elapsed.
    }

    function _ifNotSettled() internal view {
        if (phase == Phase.Settled) revert AlreadySettled(); // Disallow when already settled.
    }

    function _hashOutcome(string memory outcome) internal pure returns (bytes32 result) {
        bytes memory data = bytes(outcome); // Load string into bytes for hashing.
        assembly {
            result := keccak256(add(data, 0x20), mload(data))
        }
    }

    function _hashCommit(address user, bytes32 outcomeHash, bytes32 salt) internal pure returns (bytes32 result) {
        assembly {
            let ptr := mload(0x40) // Grab free memory pointer.
            mstore(ptr, shl(96, user)) // Store address left-aligned to 20 bytes.
            mstore(add(ptr, 0x14), outcomeHash) // Append outcome hash.
            mstore(add(ptr, 0x34), salt) // Append salt.
            result := keccak256(ptr, 0x54) // Hash the 84-byte payload.
            mstore(0x40, add(ptr, 0x60)) // Advance free memory pointer.
        }
    }

    function _decodeMarketAddress(uint256 raw) private pure returns (address) {
        if (raw >> 160 != 0) revert InvalidMarketAddress(); // Reject values that overflow address space.
        // casting to uint160 is safe because we've guaranteed the upper 96 bits are zero via the shift check above
        // forge-lint: disable-next-line(unsafe-typecast)
        return address(uint160(raw));
    }

    function _getTicket(address user, uint256 ticketId) private view returns (Ticket storage) {
        Ticket[] storage tickets = userTickets[user]; // Fetch user ticket list.
        if (ticketId >= tickets.length) revert TicketNotFound(); // Bounds check.
        return tickets[ticketId]; // Return pointer to requested ticket.
    }

    function _collateralBalance() internal view returns (uint256) {
        if (collateral == address(0)) {
            return address(this).balance; // When using native collateral, read ETH balance.
        }
        return ERC20(collateral).balanceOf(address(this)); // Otherwise read ERC20 balance.
    }

    function _finalizeSettlement(bytes32 outcomeHash, uint256 declaredWinningPool) internal {
        if (declaredWinningPool == 0 || declaredWinningPool > totalPool) revert WinningPoolNotSet(); // Ensure winning pool bounds.

        winningPool = declaredWinningPool; // Persist winning pool size.
        _settlementInProgress = true; // Block controller calls until done.
        uint256 netPool = IRakeManager(rakeManager).takeRake(collateral, totalPool, rakeBpsOverride); // Deduct rake.
        uint256 rakeAmount = totalPool - netPool; // Determine rake withheld.
        if (rakeAmount > 0) {
            if (collateral == address(0)) {
                SafeTransferLib.safeTransferETH(treasury, rakeAmount); // Send ETH rake.
            } else {
                SafeTransferLib.safeTransfer(ERC20(collateral), treasury, rakeAmount); // Send ERC20 rake.
            }
        }
        totalPool = netPool; // Update pool to net amount used for payouts.
        rakePaid = rakeAmount; // Track rake paid out for reporting.
        settledAt = block.timestamp; // Timestamp settlement completion.

        phase = Phase.Settled; // Record final phase.
        _settlementInProgress = false; // Re-open controller actions.
        emit Settled(outcomeHash); // Emit final settlement event.
        emit MarketResolved(outcomeHash, declaredWinningPool, netPool, rakeAmount, settledAt); // Rich metadata event.
    }

    function _factoryCommitPaused() internal view returns (bool) {
        if (factory.code.length == 0) return false; // If factory unset, treat as unpaused.
        try IMarketFactoryStatus(factory).globalCommitPaused() returns (bool paused) {
            return paused; // Read pause flag when interface call succeeds.
        } catch {
            return false; // Fail-open to avoid bricking markets if factory unavailable.
        }
    }

    function _factoryClaimPaused() internal view returns (bool) {
        if (factory.code.length == 0) return false; // If factory unset, treat as unpaused.
        try IMarketFactoryStatus(factory).globalClaimPaused() returns (bool paused) {
            return paused; // Read pause flag when interface call succeeds.
        } catch {
            return false; // Fail-open if factory call reverts.
        }
    }

    function _checkController() internal view {
        if (_settlementInProgress) revert SettlementInProgress(); // Block controller actions mid-settlement.
        if (msg.sender != factory && msg.sender != guardian) revert NotAuthorized(); // Require factory or guardian caller.
    }
}
