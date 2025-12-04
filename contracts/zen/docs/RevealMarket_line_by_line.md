# `RevealMarket.sol` line-by-line guide

> Note: Horizen Testnet’s native asset is ZEN. References to “ETH” in function names/comments reflect the naming conventions in Solmate helpers (`safeTransferETH`, etc.) but represent native ZEN flows.

Line 1 — `// SPDX-License-Identifier: MIT`
Declares the MIT license for SPDX-aware tooling.

Line 2 — `pragma solidity ^0.8.24;`
Targets Solidity 0.8.24-compatible compilers.

Line 3 — *(blank line)*
Separates the pragma/license block from imports.

Line 4 — `import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";`
Brings in reentrancy protection used on state-changing functions.

Line 5 — `import {SafeTransferLib} from "solmate/utils/SafeTransferLib.sol";`
Imports Solmate’s helper for safe ETH/ERC20 transfers.

Line 6 — `import {ERC20} from "solmate/tokens/ERC20.sol";`
Imports the minimal ERC20 interface used for collateral interactions.

Line 7 — *(blank line)*
Spacer before local project imports.

Line 8 — `import {IRakeManager} from "./interfaces/IRakeManager.sol";`
Loads the interface needed to interact with the rake manager.

Line 9 — `import {IVerifier} from "./interfaces/IVerifier.sol";`
Loads the interface for the zero-knowledge verifier dependency.

Line 10 — `import {IMarketFactoryStatus} from "./interfaces/IMarketFactoryStatus.sol";`
Imports the factory status interface used to read global pause flags.

Line 11 — *(blank line)*
Spacer before documentation header.

Line 12 — `/// @title RevealMarket`
NatSpec title naming the contract.

Line 13 — `/// @notice Commit-reveal prediction market supporting zero-knowledge settlement.`
NatSpec notice summarizing the contract’s purpose.

Line 14 — `contract RevealMarket is ReentrancyGuard {`
Declares the contract and shows it inherits the reentrancy guard utility.

Line 15 — `    enum Phase {`
Starts the `Phase` enum definition.

Line 16 — `        Commit,`
Enum value noted for the commit phase.

Line 17 — `        Locked,`
Enum value representing the period after commits close.

Line 18 — `        Settled,`
Enum value for the finalized/settled state.

Line 19 — `        Cancelled`
Enum value for cancelled markets.

Line 20 — `    }`
Ends the `Phase` enum definition.

Line 21 — *(blank line)*
Spacer between enum and struct.

Line 22 — `    struct Ticket {`
Begins the `Ticket` struct storing each user position.

Line 23 — `        bytes32 commitHash;`
Stores the commitment hash tied to the user’s reveal data.

Line 24 — `        uint256 amount;`
Stores how much collateral was staked with the ticket.

Line 25 — `        bool revealed;`
Tracks whether the ticket’s outcome has been revealed (unused but reserved).

Line 26 — `        bool claimed;`
Indicates whether the ticket was claimed/refunded already.

Line 27 — `    }`
Closes the `Ticket` struct.

Line 28 — *(blank line)*
Spacer before event declarations.

Line 29 — `    event Initialized(`
Starts the `Initialized` event signature.

Line 30 — `        string indexed eventId,`
First event parameter capturing the event identifier.

Line 31 — `        address indexed oracle,`
Second parameter logging the oracle address.

Line 32 — `        uint256 commitDeadline,`
Third parameter noting commit deadline timestamp.

Line 33 — `        uint256 revealDeadline,`
Fourth parameter noting reveal deadline timestamp.

Line 34 — `        address collateral,`
Fifth parameter logging the collateral token used.

Line 35 — `        address guardian`
Final parameter logging the guardian assigned to the market.

Line 36 — `    );`
Closes the `Initialized` event definition.

Line 37 — `    event Committed(address indexed user, bytes32 indexed ticketHash, uint256 amount);`
Event fired whenever a user submits a commitment with funds.

Line 38 — `    event Locked();`
Event emitted when the market transitions into the locked phase.

Line 39 — `    event ProofVerified(bool success);`
Event documenting verifier responses.

Line 40 — `    event Settled(bytes32 indexed winningOutcomeHash);`
Event emitted when settlement completes with the winning outcome hash.

Line 41 — `    event Claimed(address indexed user, uint256 payout);`
Event emitted when a participant successfully claims.

Line 42 — `    event Refunded(address indexed user, uint256 amount);`
Event signifying a refund payout.

Line 43 — `    event ResultPosted(bytes32 indexed outcomeHash);`
Event for oracle result announcements.

Line 44 — `    event GuardianUpdated(address indexed newGuardian);`
Event logged whenever the guardian changes.

Line 45 — `    event CommitPauseSet(bool paused, address indexed triggeredBy);`
Event emitted when commit activity is paused/unpaused.

Line 46 — `    event ClaimPauseSet(bool paused, address indexed triggeredBy);`
Event emitted when claim activity is paused/unpaused.

Line 47 — `    event MarketCancelled(address indexed triggeredBy, string reason);`
Event describing a cancellation along with the reason string.

Line 48 — `    event EmergencySettled(bytes32 outcomeHash, uint256 winningPool, address indexed triggeredBy);`
Event fired for emergency settlement actions.

Line 49 — `    event OracleUpdated(address indexed previousOracle, address indexed newOracle);`
Event recording oracle swaps.

Line 50 — `    event RakeConfigured(uint256 rakeBps);`
Event emitted when a per-market rake override is configured.

Line 51 — *(blank line)*
Spacer before error declarations.

Line 52 — `    error AlreadyInitialized();`
Error thrown when `initialize` is called twice.

Line 53 — `    error SettlementInProgress();`
Error used when an action is blocked during settlement.

Line 54 — `    error InvalidPhase(Phase expected, Phase current);`
Error for mismatched phase conditions.

Line 55 — `    error InvalidTimestamp();`
Generic timestamp validation failure error.

Line 56 — `    error InvalidOracle();`
Error thrown when an oracle address is missing or caller is not the oracle.

Line 57 — `    error InvalidVerifier();`
Error for missing/incorrect verifier address.

Line 58 — `    error InvalidRakeManager();`
Error for missing/incorrect rake manager address.

Line 59 — `    error InvalidTreasury();`
Error for missing/incorrect treasury address.

Line 60 — `    error InvalidAmount();`
Error used when an amount supplied is zero/invalid.

Line 61 — `    error TicketNotFound();`
Error thrown when referencing a nonexistent ticket ID.

Line 62 — `    error TicketAlreadyClaimed();`
Error thrown if the ticket has already been claimed/refunded.

Line 63 — `    error TicketLoses();`
Error raised when a claim proof does not match the winning outcome.

Line 64 — `    error WinningPoolNotSet();`
Error used when settlement data is missing or invalid.

Line 65 — `    error NothingToRefund();`
Error thrown if a refund call finds no refundable tickets.

Line 66 — `    error AlreadySettled();`
Error for operations disallowed once settled.

Line 67 — `    error OutcomeAlreadySet();`
Error when attempting to override a previously posted outcome.

Line 68 — `    error InvalidPayment();`
Error for mismatched ETH/ERC20 payment flows.

Line 69 — `    error InvalidGuardian();`
Error when a guardian address is zero or unauthorized.

Line 70 — `    error CommitPaused();`
Error triggered if commit activity is paused.

Line 71 — `    error ClaimPaused();`
Error triggered if claim activity is paused.

Line 72 — `    error NotAuthorized();`
Error for calls lacking guardian/factory authorization.

Line 73 — `    error MarketAlreadyCancelled();`
Error for redundant cancellation attempts.

Line 74 — `    error InvalidRakeBps();`
Error for rake overrides above allowed limits.

Line 75 — `    error ProofVerificationFailed();`
Error thrown if the verifier contract rejects the proof.

Line 76 — `    error ProofOutcomeMismatch();`
Error raised when the proof outcome hash does not match the recorded winner.

Line 77 — `    error ProofTotalsMismatch();`
Error raised when proof totals do not match on-chain totals.

Line 78 — `    error ProofVersionMismatch();`
Error when the proof circuit version differs from what the contract expects.

Line 79 — *(blank line)*
Spacer before state variables.

Line 80 — `    string public eventId;`
Stores the market identifier string.

Line 81 — `    Phase public phase;`
Tracks the current lifecycle phase.

Line 82 — *(blank line)*
Spacer before deadline storage.

Line 83 — `    uint256 public commitDeadline;`
Timestamp after which new commits are invalid.

Line 84 — `    uint256 public revealDeadline;`
Timestamp after which refunds become available if unsettled.

Line 85 — *(blank line)*
Spacer before address storage.

Line 86 — `    address public oracle;`
Current oracle’s address.

Line 87 — `    address public verifier;`
Trusted verifier contract address.

Line 88 — `    address public rakeManager;`
Rake manager contract address.

Line 89 — `    address public treasury;`
Treasury address receiving rake.

Line 90 — `    address public factory;`
Factory address that deployed and controls this market.

Line 91 — `    address public collateral;`
Collateral token used (zero address indicates native ETH).

Line 92 — `    address public guardian;`
Guardian with emergency controls.

Line 93 — `    bool public commitsPaused;`
Flag toggling per-market commit activity.

Line 94 — `    bool public claimsPaused;`
Flag toggling per-market claim activity.

Line 95 — `    uint256 public cancellationTimestamp;`
Timestamp when the market was cancelled (if ever).

Line 96 — *(blank line)*
Spacer before private cancellation reason storage.

Line 97 — `    string private _cancellationReason;`
Stores the cancellation reason string for later retrieval.

Line 98 — *(blank line)*
Spacer before pool accounting.

Line 99 — `    uint256 public totalPool;`
Total collateral collected (minus withdrawals after settlement).

Line 100 — `    uint256 public winningPool;`
Amount of totalPool that belonged to the winning side.

Line 101 — `    bytes32 public winningOutcomeHash;`
Hash representing the winning outcome.

Line 102 — *(blank line)*
Spacer before payout tracking.

Line 103 — `    uint256 public claimedWinningStake;`
Tracks how much winning stake has already been claimed.

Line 104 — `    uint256 public paidOut;`
Tracks total collateral paid out to claimants.

Line 105 — *(blank line)*
Spacer before internal flags.

Line 106 — `    bool private _initialized;`
Prevents re-initialization of the clone.

Line 107 — `    bool private _settlementInProgress;`
Flag guarding against overlapping settlement mutations.

Line 108 — `    uint256 public rakeBpsOverride;`
Optional market-specific rake override in basis points.

Line 109 — *(blank line)*
Spacer before constant declarations.

Line 110 — `    uint256 public constant CIRCUIT_VERSION = 1;`
Indicates the circuit version the verifier proof must reference.

Line 111 — *(blank line)*
Spacer before mapping.

Line 112 — `    mapping(address => Ticket[]) public userTickets;`
Maintains a list of tickets per user address.

Line 113 — *(blank line)*
Spacer before modifiers.

Line 114 — `    modifier onlyPhase(Phase expected) {`
Starts modifier enforcing a required phase.

Line 115 — `        _onlyPhase(expected);`
Calls the internal helper performing the check.

Line 116 — `        _;`
Continues execution if the phase is correct.

Line 117 — `    }`
Ends the `onlyPhase` modifier.

Line 118 — *(blank line)*
Spacer between modifiers.

Line 119 — `    modifier onlyOracle() {`
Starts modifier restricting access to the oracle.

Line 120 — `        _onlyOracle();`
Invokes helper verifying `msg.sender` is the oracle.

Line 121 — `        _;`
Allows continued execution if authorized.

Line 122 — `    }`
Ends the `onlyOracle` modifier.

Line 123 — *(blank line)*
Spacer.

Line 124 — `    modifier onlyAfter(uint256 timestamp) {`
Starts modifier ensuring a timestamp has passed.

Line 125 — `        _onlyAfter(timestamp);`
Calls helper that reverts until the timestamp is in the past.

Line 126 — `        _;`
Continues execution after the check.

Line 127 — `    }`
Ends the `onlyAfter` modifier.

Line 128 — *(blank line)*
Spacer.

Line 129 — `    modifier ifNotSettled() {`
Begins modifier blocking actions once settled.

Line 130 — `        _ifNotSettled();`
Invokes helper ensuring the phase is not Settled.

Line 131 — `        _;`
Continues execution when allowed.

Line 132 — `    }`
Ends `ifNotSettled`.

Line 133 — *(blank line)*
Spacer before initializer documentation.

Line 134 — `    /// @notice Initializes the market clone.`
NatSpec summary for `initialize`.

Line 135 — `    /// @param eventId_ Market identifier.`
Describes the `eventId_` parameter.

Line 136 — `    /// @param commitDeadline_ Timestamp after which commits close.`
Explains the commit deadline argument.

Line 137 — `    /// @param revealDeadline_ Timestamp after which refunds unlock if unsettled.`
Explains the reveal deadline argument.

Line 138 — `    /// @param oracle_ Oracle authorized to post results.`
Documents the oracle parameter.

Line 139 — `    /// @param verifier_ Zero-knowledge verifier contract.`
Documents the verifier parameter.

Line 140 — `    /// @param rakeManager_ Rake manager contract.`
Documents the rake manager parameter.

Line 141 — `    /// @param treasury_ Treasury that receives rake.`
Documents the treasury parameter.

Line 142 — `    /// @param collateral_ Collateral token used for staking (address(0) for native ETH).`
Explains the collateral argument semantics.

Line 143 — `    /// @param guardian_ Guardian able to pause/emergency-control the market.`
Describes the guardian argument.

Line 144 — `    function initialize(`
Begins the initializer function definition.

Line 145 — `        string calldata eventId_,`
First parameter of the initializer.

Line 146 — `        uint256 commitDeadline_,`
Second parameter describing the commit deadline.

Line 147 — `        uint256 revealDeadline_,`
Third parameter describing the reveal deadline.

Line 148 — `        address oracle_,`
Fourth parameter for the oracle address.

Line 149 — `        address verifier_,`
Fifth parameter for the verifier address.

Line 150 — `        address rakeManager_,`
Sixth parameter for the rake manager address.

Line 151 — `        address treasury_,`
Seventh parameter for the treasury address.

Line 152 — `        address collateral_,`
Eighth parameter for the collateral token.

Line 153 — `        address guardian_,`
Ninth parameter for the guardian address.

Line 154 — `        uint256 rakeBpsOverride_`
Tenth parameter for the optional rake override.

Line 155 — `    ) external {`
Closes the signature and marks it externally callable.

Line 156 — `        if (_initialized) revert AlreadyInitialized();`
Blocks re-initialization of clones.

Line 157 — `        if (oracle_ == address(0)) revert InvalidOracle();`
Requires a valid oracle address.

Line 158 — `        if (verifier_ == address(0)) revert InvalidVerifier();`
Requires a valid verifier address.

Line 159 — `        if (rakeManager_ == address(0)) revert InvalidRakeManager();`
Requires a valid rake manager.

Line 160 — `        if (treasury_ == address(0)) revert InvalidTreasury();`
Requires a valid treasury address.

Line 161 — `        if (guardian_ == address(0)) revert InvalidGuardian();`
Requires a valid guardian.

Line 162 — `        if (commitDeadline_ <= block.timestamp) revert InvalidTimestamp();`
Ensures the commit deadline is in the future.

Line 163 — `        if (revealDeadline_ <= commitDeadline_) revert InvalidTimestamp();`
Ensures the reveal deadline follows the commit deadline.

Line 164 — `        uint256 maxRake = IRakeManager(rakeManager_).maxRakeBps();`
Fetches the maximum allowed rake from the manager.

Line 165 — `        if (rakeBpsOverride_ > maxRake) revert InvalidRakeBps();`
Prevents overriding above the allowed maximum.

Line 166 — *(blank line)*
Spacer between validation and assignments.

Line 167 — `        eventId = eventId_;`
Stores the event identifier.

Line 168 — `        commitDeadline = commitDeadline_;`
Stores the commit deadline.

Line 169 — `        revealDeadline = revealDeadline_;`
Stores the reveal deadline.

Line 170 — `        oracle = oracle_;`
Stores the oracle address.

Line 171 — `        verifier = verifier_;`
Stores the verifier address.

Line 172 — `        rakeManager = rakeManager_;`
Stores the rake manager address.

Line 173 — `        treasury = treasury_;`
Stores the treasury address.

Line 174 — `        factory = msg.sender;`
Records the factory (caller) that initialized the market.

Line 175 — `        collateral = collateral_;`
Stores the collateral token choice.

Line 176 — `        guardian = guardian_;`
Stores the guardian address.

Line 177 — `        rakeBpsOverride = rakeBpsOverride_;`
Stores the override setting.

Line 178 — *(blank line)*
Spacer before phase initialization.

Line 179 — `        phase = Phase.Commit;`
Sets the starting phase.

Line 180 — `        _initialized = true;`
Marks the clone as initialized.

Line 181 — *(blank line)*
Spacer before events.

Line 182 — `        emit Initialized(eventId_, oracle_, commitDeadline_, revealDeadline_, collateral_, guardian_);`
Emits the initialization event with core settings.

Line 183 — `        if (rakeBpsOverride_ > 0) {`
Conditionally emit a rake override event if applicable.

Line 184 — `            emit RakeConfigured(rakeBpsOverride_);`
Emits the per-market rake configuration event.

Line 185 — `        }`
Ends the conditional block.

Line 186 — `    }`
Closes `initialize`.

Line 187 — *(blank line)*
Spacer before commit function.

Line 188 — `    /// @notice Allows users to commit a ticket hash with funds during the commit phase.`
NatSpec summary of the commit function.

Line 189 — `    function commit(bytes32 ticketHash, uint256 amount) external payable onlyPhase(Phase.Commit) {`
Function signature requiring commit phase and allowing ETH payment.

Line 190 — `        if (block.timestamp >= commitDeadline) revert InvalidTimestamp();`
Ensures commits happen before the deadline.

Line 191 — `        if (amount == 0) revert InvalidAmount();`
Requires non-zero stake.

Line 192 — `        if (_factoryCommitPaused()) revert CommitPaused();`
Checks factory-level commit pause flag.

Line 193 — `        if (commitsPaused) revert CommitPaused();`
Checks per-market commit pause flag.

Line 194 — *(blank line)*
Spacer before payment handling.

Line 195 — `        if (collateral == address(0)) {`
Branch for native ETH collateral.

Line 196 — `            if (msg.value != amount) revert InvalidPayment();`
Requires sent ETH to equal the declared amount.

Line 197 — `        } else {`
Branch for ERC20 collateral.

Line 198 — `            if (msg.value != 0) revert InvalidPayment();`
Disallows sending ETH when ERC20 is expected.

Line 199 — `            SafeTransferLib.safeTransferFrom(ERC20(collateral), msg.sender, address(this), amount);`
Transfers the ERC20 collateral from the user into the market.

Line 200 — `        }`
Ends payment handling branch.

Line 201 — *(blank line)*
Spacer between payment logic and ticket storage.

Line 202 — `        userTickets[msg.sender].push(Ticket({commitHash: ticketHash, amount: amount, revealed: false, claimed: false}));`
Appends a new ticket entry for the caller.

Line 203 — `        totalPool += amount;`
Increases the pool size by the committed amount.

Line 204 — *(blank line)*
Spacer before event emission.

Line 205 — `        emit Committed(msg.sender, ticketHash, amount);`
Logs the commitment for off-chain consumers.

Line 206 — `    }`
Ends the `commit` function.

Line 207 — *(blank line)*
Spacer before lock function.

Line 208 — `    /// @notice Locks the market once the commit deadline has elapsed.`
NatSpec summary of the `lock` function.

Line 209 — `    function lock() external onlyPhase(Phase.Commit) onlyAfter(commitDeadline) {`
Function requiring commit phase and that the deadline has passed.

Line 210 — `        phase = Phase.Locked;`
Transitions the market to the locked phase.

Line 211 — `        emit Locked();`
Emits the `Locked` event.

Line 212 — `    }`
Ends `lock`.

Line 213 — *(blank line)*
Spacer before result posting.

Line 214 — `    /// @notice Oracle posts the resulting outcome hash after commits are locked.`
NatSpec for `postResult`.

Line 215 — `    function postResult(bytes32 outcomeHash) external onlyOracle onlyPhase(Phase.Locked) {`
Function signature requiring oracle access during locked phase.

Line 216 — `        if (winningOutcomeHash != bytes32(0)) revert OutcomeAlreadySet();`
Prevents overwriting an existing result.

Line 217 — `        winningOutcomeHash = outcomeHash;`
Stores the winning outcome hash.

Line 218 — `        emit ResultPosted(outcomeHash);`
Emits the result event.

Line 219 — `    }`
Ends `postResult`.

Line 220 — *(blank line)*
Spacer before proof verification.

Line 221 — `    /// @notice Verifies a zero-knowledge proof and settles the market.`
NatSpec summary of `verifyProof`.

Line 222 — `    function verifyProof(bytes calldata proof, uint256[4] calldata pubSignals) external onlyPhase(Phase.Locked) nonReentrant {`
Function verifying proofs during the locked phase with reentrancy protection.

Line 223 — `        if (phase == Phase.Cancelled) revert MarketAlreadyCancelled();`
Blocks proof verification if the market was cancelled.

Line 224 — `        if (winningOutcomeHash == bytes32(0)) revert WinningPoolNotSet();`
Requires a posted outcome before verifying.

Line 225 — *(blank line)*
Spacer before parsing signals.

Line 226 — `        uint256 declaredWinningPool = pubSignals[0];`
Reads the declared winning pool from the proof signals.

Line 227 — `        uint256 proofTotalPool = pubSignals[1];`
Reads the proof’s total-pool value.

Line 228 — `        bytes32 proofOutcomeHash = bytes32(pubSignals[2]);`
Reads the proof’s outcome hash.

Line 229 — `        uint256 proofVersion = pubSignals[3];`
Reads the proof’s circuit version.

Line 230 — *(blank line)*
Spacer before validations.

Line 231 — `        if (proofOutcomeHash != winningOutcomeHash) revert ProofOutcomeMismatch();`
Ensures the proof references the same outcome recorded earlier.

Line 232 — `        if (proofTotalPool != totalPool) revert ProofTotalsMismatch();`
Ensures the proof matches on-chain pool totals.

Line 233 — `        if (proofVersion != CIRCUIT_VERSION) revert ProofVersionMismatch();`
Ensures the proof uses the expected circuit version.

Line 234 — `        if (declaredWinningPool == 0 || declaredWinningPool > proofTotalPool) revert WinningPoolNotSet();`
Validates the declared winning pool is within range.

Line 235 — *(blank line)*
Spacer before external verifier call.

Line 236 — `        bool success = IVerifier(verifier).verifyProof(proof, pubSignals);`
Invokes the external verifier and records whether it succeeded.

Line 237 — `        emit ProofVerified(success);`
Emits an event with the verifier’s response.

Line 238 — `        if (!success) revert ProofVerificationFailed();`
Reverts if the verifier rejected the proof.

Line 239 — *(blank line)*
Spacer before settlement finalization.

Line 240 — `        _finalizeSettlement(winningOutcomeHash, declaredWinningPool);`
Executes the internal settlement routine with the proof data.

Line 241 — `    }`
Ends `verifyProof`.

Line 242 — *(blank line)*
Spacer before claim function.

Line 243 — `    /// @notice Claims winnings by revealing the committed outcome.`
NatSpec for the `claim` function.

Line 244 — `    function claim(uint256 ticketId, string calldata outcome, bytes32 salt) external nonReentrant onlyPhase(Phase.Settled) {`
Function signature requiring the settled phase and guarding reentrancy.

Line 245 — `        if (winningPool == 0) revert WinningPoolNotSet();`
Ensures settlement recorded a winning pool.

Line 246 — `        if (_factoryClaimPaused()) revert ClaimPaused();`
Checks factory-level claim pause flag.

Line 247 — `        if (claimsPaused) revert ClaimPaused();`
Checks per-market claim pause flag.

Line 248 — `        if (phase == Phase.Cancelled) revert MarketAlreadyCancelled();`
Blocks claims when the market was cancelled.

Line 249 — *(blank line)*
Spacer before ticket retrieval.

Line 250 — `        Ticket storage ticket = _getTicket(msg.sender, ticketId);`
Fetches the referenced ticket for the caller.

Line 251 — `        if (ticket.claimed) revert TicketAlreadyClaimed();`
Prevents double-claiming.

Line 252 — *(blank line)*
Spacer before reveal verification.

Line 253 — `        bytes32 outcomeHash = _hashOutcome(outcome);`
Computes the hash of the provided outcome string.

Line 254 — `        if (outcomeHash != winningOutcomeHash) revert TicketLoses();`
Ensures the reveal matches the winning outcome.

Line 255 — *(blank line)*
Spacer before recomputing the commit hash.

Line 256 — `        bytes32 reconstructed = _hashCommit(msg.sender, outcomeHash, salt);`
Rebuilds the original commit hash using caller/outcome/salt.

Line 257 — `        if (reconstructed != ticket.commitHash) revert TicketLoses();`
Ensures the reveal matches the original commitment.

Line 258 — *(blank line)*
Spacer before state updates.

Line 259 — `        ticket.claimed = true;`
Marks the ticket as claimed.

Line 260 — `        ticket.revealed = true;`
Marks the ticket as revealed.

Line 261 — *(blank line)*
Spacer before payout calculation.

Line 262 — `        uint256 newClaimedStake = claimedWinningStake + ticket.amount;`
Calculates the new total claimed stake if this claim succeeds.

Line 263 — `        uint256 payout;`
Declares a payout accumulator variable.

Line 264 — `        if (newClaimedStake >= winningPool) {`
Checks if this claim exhausts the winning pool (handles rounding).

Line 265 — `            payout = _collateralBalance();`
If so, send whatever balance remains to the claimant.

Line 266 — `        } else {`
Branch for the normal proportional payout.

Line 267 — `            payout = (ticket.amount * totalPool) / winningPool;`
Computes payout proportional to the user’s stake.

Line 268 — `        }`
Ends payout branch.

Line 269 — `        claimedWinningStake = newClaimedStake;`
Persists the updated claimed stake measure.

Line 270 — `        paidOut += payout;`
Accumulates total collateral paid out.

Line 271 — *(blank line)*
Spacer before payments.

Line 272 — `        if (collateral == address(0)) {`
Branch for native ETH payouts.

Line 273 — `            SafeTransferLib.safeTransferETH(msg.sender, payout);`
Sends ETH to the claimant.

Line 274 — `        } else {`
Branch for ERC20 payouts.

Line 275 — `            SafeTransferLib.safeTransfer(ERC20(collateral), msg.sender, payout);`
Transfers ERC20 collateral to the claimant.

Line 276 — `        }`
Ends payout transfer branch.

Line 277 — `        emit Claimed(msg.sender, payout);`
Emits the claim event.

Line 278 — `    }`
Ends `claim`.

Line 279 — *(blank line)*
Spacer before refund function.

Line 280 — `    /// @notice Refunds all tickets if the market was not settled before reveal deadline.`
NatSpec summary for `refund`.

Line 281 — `    function refund() external nonReentrant ifNotSettled {`
Function signature requiring the market not be settled and guarding reentrancy.

Line 282 — `        Ticket[] storage tickets = userTickets[msg.sender];`
Loads all tickets owned by the caller.

Line 283 — `        uint256 length = tickets.length;`
Caches the ticket count for loop efficiency.

Line 284 — `        uint256 refundAmount;`
Accumulator for the total refund owed.

Line 285 — *(blank line)*
Spacer before loop.

Line 286 — `        for (uint256 i = 0; i < length; ++i) {`
Begins loop across the caller’s tickets.

Line 287 — `            Ticket storage ticket = tickets[i];`
Loads each ticket reference.

Line 288 — `            if (!ticket.claimed && ticket.amount > 0) {`
Only refund tickets that still hold funds and haven’t been claimed.

Line 289 — `                refundAmount += ticket.amount;`
Add the stake to the refund accumulator.

Line 290 — `                ticket.claimed = true;`
Mark the ticket as claimed to prevent double refunds.

Line 291 — `                ticket.amount = 0;`
Zero out the refunded amount.

Line 292 — `            }`
Ends conditional.

Line 293 — `        }`
Closes the loop.

Line 294 — *(blank line)*
Spacer before validations.

Line 295 — `        if (refundAmount == 0) revert NothingToRefund();`
Reverts if no refundable value was found.

Line 296 — `        if (phase != Phase.Cancelled && block.timestamp <= revealDeadline) revert InvalidTimestamp();`
Requires either cancellation or the reveal deadline having passed.

Line 297 — *(blank line)*
Spacer before transfers.

Line 298 — `        totalPool -= refundAmount;`
Reduces the pool to reflect refunded funds.

Line 299 — `        if (collateral == address(0)) {`
Branch for ETH refunds.

Line 300 — `            SafeTransferLib.safeTransferETH(msg.sender, refundAmount);`
Transfers ETH back to the user.

Line 301 — `        } else {`
Branch for ERC20 refunds.

Line 302 — `            SafeTransferLib.safeTransfer(ERC20(collateral), msg.sender, refundAmount);`
Transfers ERC20 tokens back to the user.

Line 303 — `        }`
Ends refund branch.

Line 304 — `        emit Refunded(msg.sender, refundAmount);`
Emits the refund event.

Line 305 — `    }`
Ends `refund`.

Line 306 — *(blank line)*
Spacer before read-only helpers.

Line 307 — `    /// @notice Returns the number of tickets a user holds.`
NatSpec description for `ticketCount`.

Line 308 — `    function ticketCount(address user) external view returns (uint256) {`
Function returning a user’s ticket count.

Line 309 — `        return userTickets[user].length;`
Reads and returns the length of the ticket array.

Line 310 — `    }`
Ends `ticketCount`.

Line 311 — *(blank line)*
Spacer.

Line 312 — `    /// @notice Returns the details of a specific ticket.`
NatSpec summary for `ticketInfo`.

Line 313 — `    function ticketInfo(address user, uint256 ticketId) external view returns (Ticket memory) {`
Function returning a copy of a ticket.

Line 314 — `        Ticket storage ticket = _getTicket(user, ticketId);`
Retrieves the ticket storage reference via helper.

Line 315 — `        return Ticket({`
Begins a struct literal for returning.

Line 316 — `            commitHash: ticket.commitHash,`
Copies the commit hash.

Line 317 — `            amount: ticket.amount,`
Copies the staked amount.

Line 318 — `            revealed: ticket.revealed,`
Copies the reveal flag.

Line 319 — `            claimed: ticket.claimed`
Copies the claimed flag.

Line 320 — `        });`
Closes the struct literal and return statement.

Line 321 — `    }`
Ends `ticketInfo`.

Line 322 — *(blank line)*
Spacer before payout preview.

Line 323 — `    /// @notice Computes the payout a ticket would receive if claimed with provided reveal data.`
NatSpec summary for `payoutPreview`.

Line 324 — `    function payoutPreview(`
Begins the multi-line signature.

Line 325 — `        address user,`
First argument: ticket owner.

Line 326 — `        uint256 ticketId,`
Second argument: ticket index.

Line 327 — `        string calldata outcome,`
Third argument: outcome string to test.

Line 328 — `        bytes32 salt`
Fourth argument: salt to pair with the outcome.

Line 329 — `    ) external view returns (uint256 payout, bool claimable) {`
Completes the signature and states it returns payout/claimability.

Line 330 — `        if (phase != Phase.Settled || winningPool == 0) return (0, false);`
Early exits if settlement isn’t complete.

Line 331 — *(blank line)*
Spacer before ticket lookup.

Line 332 — `        Ticket storage ticket = _getTicket(user, ticketId);`
Loads the ticket being inspected.

Line 333 — `        if (ticket.claimed) return (0, false);`
Rejects already claimed tickets.

Line 334 — *(blank line)*
Spacer before outcome hash.

Line 335 — `        bytes32 outcomeHash = _hashOutcome(outcome);`
Recomputes the candidate outcome hash.

Line 336 — `        if (outcomeHash != winningOutcomeHash) return (0, false);`
Requires the candidate to match the winning outcome.

Line 337 — *(blank line)*
Spacer before commit reconstruction.

Line 338 — `        bytes32 reconstructed = _hashCommit(user, outcomeHash, salt);`
Rebuilds the original commit hash.

Line 339 — `        if (reconstructed != ticket.commitHash) return (0, false);`
Ensures the reveal data matches this ticket.

Line 340 — *(blank line)*
Spacer before payout calculation.

Line 341 — `        uint256 newClaimedStake = claimedWinningStake + ticket.amount;`
Predicts how much winning stake would be claimed.

Line 342 — `        if (newClaimedStake >= winningPool) {`
Checks if this hypothetical claim would exhaust the pool.

Line 343 — `            payout = _collateralBalance();`
Would pay out the remainder of the contract balance in that case.

Line 344 — `        } else {`
Otherwise compute proportionally.

Line 345 — `            payout = (ticket.amount * totalPool) / winningPool;`
Calculates the proportional payout.

Line 346 — `        }`
Ends the conditional.

Line 347 — `        return (payout, true);`
Returns the previewed payout and claimable flag.

Line 348 — `    }`
Ends `payoutPreview`.

Line 349 — *(blank line)*
Spacer before other views.

Line 350 — `    function remainingPayoutPool() external view returns (uint256) {`
View helper reporting the remaining collateral balance.

Line 351 — `        return _collateralBalance();`
Returns the helper’s result.

Line 352 — `    }`
Ends `remainingPayoutPool`.

Line 353 — *(blank line)*
Spacer.

Line 354 — `    function appliedRakeBps() public view returns (uint256) {`
View helper showing the effective rake rate.

Line 355 — `        uint256 overrideBps = rakeBpsOverride;`
Caches the override value.

Line 356 — `        if (overrideBps == 0) {`
If no override is set...

Line 357 — `            return IRakeManager(rakeManager).rakeBps();`
...return the shared rake manager value.

Line 358 — `        }`
Closes conditional branch.

Line 359 — `        return overrideBps;`
Otherwise return the override.

Line 360 — `    }`
Ends `appliedRakeBps`.

Line 361 — *(blank line)*
Spacer before controller setters.

Line 362 — `    function setGuardian(address newGuardian) external {`
Starts the guardian setter callable by controllers.

Line 363 — `        _checkController();`
Ensures only the factory or guardian can call this.

Line 364 — `        if (newGuardian == address(0)) revert InvalidGuardian();`
Prevents clearing the guardian.

Line 365 — `        guardian = newGuardian;`
Stores the new guardian.

Line 366 — `        emit GuardianUpdated(newGuardian);`
Emits the guardian update event.

Line 367 — `    }`
Ends `setGuardian`.

Line 368 — *(blank line)*
Spacer.

Line 369 — `    function setCommitPaused(bool paused) external {`
Starts function toggling commit pause state.

Line 370 — `        _checkController();`
Requires controller authorization.

Line 371 — `        commitsPaused = paused;`
Updates the flag.

Line 372 — `        emit CommitPauseSet(paused, msg.sender);`
Emits the pause event.

Line 373 — `    }`
Ends `setCommitPaused`.

Line 374 — *(blank line)*
Spacer.

Line 375 — `    function setClaimPaused(bool paused) external {`
Starts function toggling claim pause state.

Line 376 — `        _checkController();`
Requires controller authorization.

Line 377 — `        claimsPaused = paused;`
Updates the flag.

Line 378 — `        emit ClaimPauseSet(paused, msg.sender);`
Emits the pause event.

Line 379 — `    }`
Ends `setClaimPaused`.

Line 380 — *(blank line)*
Spacer before cancellation.

Line 381 — `    function cancelMarket(string calldata reason) external {`
Starts the cancellation function requiring controllers.

Line 382 — `        _checkController();`
Ensures only factory/guardian can cancel.

Line 383 — `        if (phase == Phase.Settled) revert AlreadySettled();`
Prevents cancelling after settlement.

Line 384 — `        if (phase == Phase.Cancelled) revert MarketAlreadyCancelled();`
Prevents cancelling twice.

Line 385 — `        phase = Phase.Cancelled;`
Sets the phase to cancelled.

Line 386 — `        cancellationTimestamp = block.timestamp;`
Records when cancellation occurred.

Line 387 — `        _cancellationReason = reason;`
Saves the supplied reason string.

Line 388 — `        winningOutcomeHash = bytes32(0);`
Clears the winning outcome.

Line 389 — `        winningPool = 0;`
Clears the winning pool amount.

Line 390 — `        commitsPaused = true;`
Pauses commits as part of cancellation.

Line 391 — `        claimsPaused = true;`
Pauses claims as well.

Line 392 — `        emit MarketCancelled(msg.sender, reason);`
Emits the cancellation event.

Line 393 — `    }`
Ends `cancelMarket`.

Line 394 — *(blank line)*
Spacer before emergency settle.

Line 395 — `    function emergencySettle(bytes32 outcomeHash, uint256 declaredWinningPool) external nonReentrant {`
Starts function allowing controllers to force settlement.

Line 396 — `        _checkController();`
Requires controller authorization.

Line 397 — `        if (phase != Phase.Locked) revert InvalidPhase(Phase.Locked, phase);`
Only allowed from the locked phase.

Line 398 — `        winningOutcomeHash = outcomeHash;`
Overrides the winning outcome hash with supplied value.

Line 399 — `        _finalizeSettlement(outcomeHash, declaredWinningPool);`
Runs settlement with the provided winning pool.

Line 400 — `        emit EmergencySettled(outcomeHash, declaredWinningPool, msg.sender);`
Emits the emergency settlement event.

Line 401 — `    }`
Ends `emergencySettle`.

Line 402 — *(blank line)*
Spacer before oracle update.

Line 403 — `    function updateOracle(address newOracle) external {`
Starts the oracle update helper.

Line 404 — `        _checkController();`
Requires controller authorization.

Line 405 — `        if (newOracle == address(0)) revert InvalidOracle();`
Ensures a valid oracle address is supplied.

Line 406 — `        address previous = oracle;`
Stores the old oracle for event emission.

Line 407 — `        oracle = newOracle;`
Updates storage with the new oracle.

Line 408 — `        emit OracleUpdated(previous, newOracle);`
Emits the oracle update event.

Line 409 — `    }`
Ends `updateOracle`.

Line 410 — *(blank line)*
Spacer.

Line 411 — `    function cancellationReason() external view returns (string memory) {`
View function returning the stored cancellation reason.

Line 412 — `        return _cancellationReason;`
Returns the private string.

Line 413 — `    }`
Ends `cancellationReason`.

Line 414 — *(blank line)*
Spacer before receive hook.

Line 415 — `    receive() external payable {`
Defines the receive function for stray ETH transfers.

Line 416 — `        revert InvalidPhase(Phase.Commit, phase);`
Rejects direct ETH transfers unless they flow through commit.

Line 417 — `    }`
Ends the receive hook.

Line 418 — *(blank line)*
Spacer before internal utilities banner.

Line 419 — `    // ----------------------- internal utils -----------------------`
Comment separating internal helper section.

Line 420 — *(blank line)*
Spacer.

Line 421 — `    function _onlyPhase(Phase expected) internal view {`
Helper verifying that `phase` equals `expected`.

Line 422 — `        if (phase != expected) revert InvalidPhase(expected, phase);`
Performs the actual phase comparison and revert.

Line 423 — `    }`
Ends `_onlyPhase`.

Line 424 — *(blank line)*
Spacer.

Line 425 — `    function _onlyOracle() internal view {`
Helper verifying `msg.sender` is the oracle.

Line 426 — `        if (msg.sender != oracle) revert InvalidOracle();`
Performs the caller check.

Line 427 — `    }`
Ends `_onlyOracle`.

Line 428 — *(blank line)*
Spacer.

Line 429 — `    function _onlyAfter(uint256 timestamp) internal view {`
Helper ensuring the current time exceeds `timestamp`.

Line 430 — `        if (block.timestamp <= timestamp) revert InvalidTimestamp();`
Performs the timestamp comparison and revert.

Line 431 — `    }`
Ends `_onlyAfter`.

Line 432 — *(blank line)*
Spacer.

Line 433 — `    function _ifNotSettled() internal view {`
Helper that blocks execution if the market is settled.

Line 434 — `        if (phase == Phase.Settled) revert AlreadySettled();`
Checks the phase and reverts if necessary.

Line 435 — `    }`
Ends `_ifNotSettled`.

Line 436 — *(blank line)*
Spacer.

Line 437 — `    function _hashOutcome(string memory outcome) internal pure returns (bytes32 result) {`
Helper hashing an outcome string.

Line 438 — `        bytes memory data = bytes(outcome);`
Loads the string’s byte representation.

Line 439 — `        assembly {`
Begins an inline assembly block for efficiency.

Line 440 — `            result := keccak256(add(data, 0x20), mload(data))`
Computes the keccak256 hash over the string contents.

Line 441 — `        }`
Ends the assembly block.

Line 442 — `    }`
Ends `_hashOutcome`.

Line 443 — *(blank line)*
Spacer.

Line 444 — `    function _hashCommit(address user, bytes32 outcomeHash, bytes32 salt) internal pure returns (bytes32 result) {`
Helper rebuilding the commit hash from inputs.

Line 445 — `        assembly {`
Starts inline assembly for efficient hashing.

Line 446 — `            let ptr := mload(0x40)`
Loads free memory pointer.

Line 447 — `            mstore(ptr, shl(96, user))`
Stores the user address left-padded to 20 bytes.

Line 448 — `            mstore(add(ptr, 0x14), outcomeHash)`
Stores the outcome hash immediately after the address.

Line 449 — `            mstore(add(ptr, 0x34), salt)`
Stores the salt after the outcome hash.

Line 450 — `            result := keccak256(ptr, 0x54)`
Hashes the 84-byte region to produce the commit hash.

Line 451 — `            mstore(0x40, add(ptr, 0x60))`
Updates the free memory pointer.

Line 452 — `        }`
Ends the assembly block.

Line 453 — `    }`
Ends `_hashCommit`.

Line 454 — *(blank line)*
Spacer.

Line 455 — `    function _getTicket(address user, uint256 ticketId) private view returns (Ticket storage) {`
Private helper fetching a ticket reference.

Line 456 — `        Ticket[] storage tickets = userTickets[user];`
Loads the user’s ticket array.

Line 457 — `        if (ticketId >= tickets.length) revert TicketNotFound();`
Validates that the index exists.

Line 458 — `        return tickets[ticketId];`
Returns the storage pointer.

Line 459 — `    }`
Ends `_getTicket`.

Line 460 — *(blank line)*
Spacer before balance helper.

Line 461 — `    function _collateralBalance() internal view returns (uint256) {`
Helper returning the contract’s collateral balance.

Line 462 — `        if (collateral == address(0)) {`
Branch for ETH balances.

Line 463 — `            return address(this).balance;`
Returns ETH balance when using native collateral.

Line 464 — `        }`
Else branch fallback.

Line 465 — `        return ERC20(collateral).balanceOf(address(this));`
Returns ERC20 balance when using token collateral.

Line 466 — `    }`
Ends `_collateralBalance`.

Line 467 — *(blank line)*
Spacer before settlement helper.

Line 468 — `    function _finalizeSettlement(bytes32 outcomeHash, uint256 declaredWinningPool) internal {`
Core helper that finalizes settlement mechanics.

Line 469 — `        if (declaredWinningPool == 0 || declaredWinningPool > totalPool) revert WinningPoolNotSet();`
Validates the declared winning pool.

Line 470 — *(blank line)*
Spacer before state updates.

Line 471 — `        winningPool = declaredWinningPool;`
Stores the winning pool size.

Line 472 — `        _settlementInProgress = true;`
Signals that settlement-side effects are underway.

Line 473 — `        uint256 netPool = IRakeManager(rakeManager).takeRake(collateral, totalPool, rakeBpsOverride);`
Asks the rake manager to deduct rake and return the net pool.

Line 474 — `        uint256 rakeAmount = totalPool - netPool;`
Derives how much rake was removed.

Line 475 — `        if (rakeAmount > 0) {`
Only transfer rake if non-zero.

Line 476 — `            if (collateral == address(0)) {`
Branch for ETH rake transfers.

Line 477 — `                SafeTransferLib.safeTransferETH(treasury, rakeAmount);`
Sends ETH rake to the treasury.

Line 478 — `            } else {`
Branch for ERC20 rake transfers.

Line 479 — `                SafeTransferLib.safeTransfer(ERC20(collateral), treasury, rakeAmount);`
Transfers ERC20 rake to the treasury.

Line 480 — `            }`
Ends rake transfer branch.

Line 481 — `        }`
Ends conditional.

Line 482 — `        totalPool = netPool;`
Updates `totalPool` to the post-rake value.

Line 483 — *(blank line)*
Spacer before final state changes.

Line 484 — `        phase = Phase.Settled;`
Sets the market to the settled phase.

Line 485 — `        _settlementInProgress = false;`
Clears the in-progress flag.

Line 486 — `        emit Settled(outcomeHash);`
Emits the settlement event.

Line 487 — `    }`
Ends `_finalizeSettlement`.

Line 488 — *(blank line)*
Spacer before factory pause helpers.

Line 489 — `    function _factoryCommitPaused() internal view returns (bool) {`
Helper querying the factory’s global commit pause flag.

Line 490 — `        if (factory.code.length == 0) return false;`
If the factory is not a contract (e.g., set to zero), assume no pause.

Line 491 — `        try IMarketFactoryStatus(factory).globalCommitPaused() returns (bool paused) {`
Performs a try/catch call into the factory interface.

Line 492 — `            return paused;`
Returns the value when the call succeeds.

Line 493 — `        } catch {`
Fallback path if the call reverts.

Line 494 — `            return false;`
Default to `false` when the factory call fails.

Line 495 — `        }`
Ends try/catch block.

Line 496 — `    }`
Ends `_factoryCommitPaused`.

Line 497 — *(blank line)*
Spacer.

Line 498 — `    function _factoryClaimPaused() internal view returns (bool) {`
Helper querying the factory’s global claim pause flag.

Line 499 — `        if (factory.code.length == 0) return false;`
Assumes unpaused if factory is not a contract.

Line 500 — `        try IMarketFactoryStatus(factory).globalClaimPaused() returns (bool paused) {`
Calls the factory interface to read the flag.

Line 501 — `            return paused;`
Returns the factory’s response.

Line 502 — `        } catch {`
Fallback if the call fails.

Line 503 — `            return false;`
Defaults to unpaused when the call reverts.

Line 504 — `        }`
Ends try/catch.

Line 505 — `    }`
Ends `_factoryClaimPaused`.

Line 506 — *(blank line)*
Spacer.

Line 507 — `    function _checkController() internal view {`
Helper ensuring the caller is allowed to perform guardian/factory-only actions.

Line 508 — `        if (_settlementInProgress) revert SettlementInProgress();`
Blocks controller actions during settlement to prevent inconsistencies.

Line 509 — `        if (msg.sender != factory && msg.sender != guardian) revert NotAuthorized();`
Requires the caller to be the factory or guardian.

Line 510 — `    }`
Ends `_checkController`.

Line 511 — `}`
Ends the contract.
