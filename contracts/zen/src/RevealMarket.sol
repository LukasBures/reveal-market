// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {MessageHashUtils} from "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

import {IProtocolPool} from "./interfaces/IProtocolPool.sol";
import {IRelayerEscrow} from "./interfaces/IRelayerEscrow.sol";
import {IRevealMarket} from "./interfaces/IRevealMarket.sol";
import {IVerifier} from "./interfaces/IVerifier.sol";
import {RelayerEscrow} from "./RelayerEscrow.sol";

/// @notice Minimal commit/reveal market using fixed-size tickets and ZK-verified settlement.
contract RevealMarket is IRevealMarket, ReentrancyGuard {
    using SafeERC20 for IERC20;
    using ECDSA for bytes32;

    struct InitParams {
        address factory;
        address protocolPool;
        address relayerEscrow;
        address oracle;
        address verifier;
        bytes32 circuitHash;
        address collateralToken;
        uint256 commitDeadline;
        uint256 revealDeadline;
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
    uint256 public revealDeadline;
    uint256 public ticketSize;
    uint256 public maxCommitments;
    address public override authorizationSigner;
    uint256 public protocolLiabilityCap;
    uint256 public override marketId;
    uint256 public rakeBps;

    Phase public override phase;
    bytes32 public commitmentsRoot;
    uint256 public totalEscrow;
    uint256 public totalLiability;
    uint256 public rakeAmount;
    uint256 public rakeCollected;
    bool public commitsPaused;
    bool public claimsPaused;
    uint256 public poolTotalYes;
    uint256 public poolTotalNo;
    uint256 public claimedLiability;
    uint256 public protocolTopUp;
    uint256 public winningOutcomeId;
    bool public resultPosted;
    bool private initialized;

    bytes32[] private commitments;
    mapping(uint256 => bool) public usedCommitNonces;
    mapping(uint256 => bool) public claimedTickets;

    event Committed(uint256 indexed ticketId, bytes32 commitment, uint256 totalEscrow);
    event Locked(bytes32 commitmentsRoot, uint256 ticketCount);
    event ResultPosted(uint256 indexed winningOutcomeId);
    event Settled(uint256 totalLiability, uint256 rakeAmount, uint256 protocolTopUp, uint256 poolYes, uint256 poolNo);
    event Claimed(address indexed relayer, address indexed user, uint256 indexed ticketId, uint256 amount);
    event Finished(uint256 leftoverToProtocol);
    event AuthorizationSignerUpdated(address indexed signer);
    event OracleUpdated(address indexed oracle);
    event RelayerEscrowUpdated(address indexed relayer);
    event ProtocolLiabilityCapUpdated(uint256 newCap);

    error AlreadyInitialized();
    error NotRelayer();
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
    error ClaimWindowClosed();
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
    error InvalidAddress();

    modifier onlyRelayer() {
        _onlyRelayer();
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
                || params.revealDeadline <= params.commitDeadline || params.collateralToken == address(0)
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
        revealDeadline = params.revealDeadline;
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
        uint256 requiredBalance = totalEscrow + rakeCollected + ticketSize;
        if (IERC20(collateralToken).balanceOf(address(this)) < requiredBalance) revert InvalidPayment();
        if (maxCommitments != 0 && commitments.length >= maxCommitments) revert MaxCommitmentsReached();
        if (auth.expiry < block.timestamp) revert CommitExpired();
        if (usedCommitNonces[auth.nonce]) revert CommitReplay();

        bytes32 digest = MessageHashUtils.toEthSignedMessageHash(
            keccak256(abi.encode(address(this), marketId, auth.commitment, auth.nonce, auth.expiry))
        );
        if (digest.recover(signature) != authorizationSigner) revert InvalidSignature();

        usedCommitNonces[auth.nonce] = true;
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
    function lock() external onlyOracle {
        if (phase != Phase.Commit) revert InvalidPhase();
        if (block.timestamp < commitDeadline) revert CommitWindowClosed();
        if (commitments.length == 0) revert NothingToLock();

        commitmentsRoot = _computeCommitmentsRoot();
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
        if (phase != Phase.Locked) revert InvalidPhase();
        if (!resultPosted) revert ResultMissing();

        if (
            publicSignals[0] != uint256(commitmentsRoot) || publicSignals[1] != marketId
                || publicSignals[2] != winningOutcomeId || publicSignals[3] != totalEscrow
        ) revert TotalsMismatch();
        if (publicSignals[5] != rakeBps) revert RakeMismatch();
        if (publicSignals[8] != uint256(circuitHash)) revert CircuitHashMismatch();
        if (publicSignals[9] != 0) revert PaddingMismatch();

        bool ok = IVerifier(verifier).verifyProof(proof, publicSignals);
        if (!ok) revert InvalidProof();

        totalLiability = publicSignals[4];
        poolTotalYes = publicSignals[6];
        poolTotalNo = publicSignals[7];

        rakeAmount = rakeCollected;
        uint256 required = totalLiability;
        if (required > totalEscrow + protocolLiabilityCap) revert LiabilityExceedsCoverage();

        uint256 balance = IERC20(collateralToken).balanceOf(address(this));
        if (required > balance) {
            uint256 deficit = required - balance;
            protocolTopUp = deficit;
            IProtocolPool(protocolPool).draw(address(this), deficit);
        }

        if (required > IERC20(collateralToken).balanceOf(address(this))) revert InsufficientCoverage();

        // forward any surplus immediately; keep only what is needed for claims
        uint256 tokenBalance = IERC20(collateralToken).balanceOf(address(this));
        uint256 surplus = tokenBalance > totalLiability ? tokenBalance - totalLiability : 0;
        if (surplus > 0) {
            IERC20(collateralToken).safeTransfer(protocolPool, surplus);
        }

        phase = Phase.Settled;
        emit Settled(totalLiability, rakeAmount, protocolTopUp, poolTotalYes, poolTotalNo);
    }

    /// @notice Winning tickets reveal and route payouts back to the relayer escrow.
    function claim(
        address user,
        uint256 ticketId,
        uint256 outcomeId,
        uint256 amount,
        bytes32 salt,
        bytes32[] calldata merkleProof
    ) external onlyRelayer nonReentrant {
        if (phase != Phase.Settled) revert InvalidPhase();
        if (block.timestamp > revealDeadline) revert ClaimWindowClosed();
        if (claimsPaused) revert ClaimsPaused();
        if (outcomeId != winningOutcomeId) revert WrongOutcome();
        if (claimedTickets[ticketId]) revert TicketAlreadyClaimed();
        bytes32 leaf = _computeLeaf(ticketId, outcomeId, amount, salt);
        if (!_verifyLeaf(ticketId, leaf, merkleProof)) revert InvalidMerkleProof();

        claimedTickets[ticketId] = true;
        claimedLiability += amount;
        if (claimedLiability > totalLiability) revert OverClaimed();

        IERC20(collateralToken).safeTransfer(relayerEscrow, amount);
        IRelayerEscrow(relayerEscrow).creditFromMarket(user, amount);
        emit Claimed(msg.sender, user, ticketId, amount);

        if (claimedLiability == totalLiability) {
            _finish();
        }
    }

    /// @notice Returns the sealed commitment stored at an index (for off-chain auditing).
    function commitmentAt(uint256 index) external view returns (bytes32) {
        return commitments[index];
    }

    function _finish() internal {
        uint256 leftover = IERC20(collateralToken).balanceOf(address(this));
        if (leftover > 0) {
            IERC20(collateralToken).safeTransfer(protocolPool, leftover);
        }
        phase = Phase.Finished;
        emit Finished(leftover);
    }

    /// @notice Factory hook to update rake for existing markets (keeps all markets aligned to global rake).
    function setRakeBps(uint256 newRakeBps) external onlyFactory {
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
        if (phase == Phase.Settled || phase == Phase.Finished) revert InvalidPhase();
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
        if (phase == Phase.Settled || phase == Phase.Finished) revert InvalidPhase();
        protocolLiabilityCap = newCap;
        emit ProtocolLiabilityCapUpdated(newCap);
    }

    /// @notice Owner/factory controls to pause commits or claims in emergencies.
    function setCommitsPaused(bool paused) external onlyFactory {
        commitsPaused = paused;
    }

    function setClaimsPaused(bool paused) external onlyFactory {
        claimsPaused = paused;
    }

    /// @notice Extend-only deadline updates. Cannot shorten.
    function extendCommitDeadline(uint256 newDeadline) external onlyFactory {
        if (newDeadline <= commitDeadline) revert DeadlineExtendOnly();
        if (phase != Phase.Commit) revert InvalidPhase();
        commitDeadline = newDeadline;
    }

    function extendRevealDeadline(uint256 newDeadline) external onlyFactory {
        if (newDeadline <= revealDeadline) revert DeadlineExtendOnly();
        if (phase == Phase.Finished) revert InvalidPhase();
        revealDeadline = newDeadline;
    }

    function _computeCommitmentsRoot() internal view returns (bytes32) {
        uint256 count = commitments.length;
        bytes32[] memory nodes = new bytes32[](count);
        for (uint256 i = 0; i < count; ++i) {
            nodes[i] = commitments[i];
        }
        while (count > 1) {
            uint256 next = 0;
            for (uint256 i = 0; i < count; i += 2) {
                if (i + 1 == count) {
                    nodes[next] = keccak256(abi.encodePacked(nodes[i], nodes[i]));
                } else {
                    nodes[next] = keccak256(abi.encodePacked(nodes[i], nodes[i + 1]));
                }
                next++;
            }
            count = next;
        }
        return nodes[0];
    }

    function _computeLeaf(uint256 ticketId, uint256 outcomeId, uint256 amount, bytes32 salt)
        internal
        pure
        returns (bytes32 hash)
    {
        assembly {
            let ptr := mload(0x40)
            mstore(ptr, ticketId)
            mstore(add(ptr, 0x20), outcomeId)
            mstore(add(ptr, 0x40), amount)
            mstore(add(ptr, 0x60), salt)
            hash := keccak256(ptr, 0x80)
            mstore(0x40, add(ptr, 0x80))
        }
    }

    function _verifyLeaf(uint256 ticketId, bytes32 leaf, bytes32[] calldata proof) internal view returns (bool) {
        if (ticketId >= commitments.length) return false;
        if (commitments[ticketId] != leaf) return false;
        bytes32 computed = leaf;
        uint256 index = ticketId;
        for (uint256 i = 0; i < proof.length; ++i) {
            bytes32 sibling = proof[i];
            if ((index & 1) == 1) {
                computed = keccak256(abi.encodePacked(sibling, computed));
            } else {
                computed = keccak256(abi.encodePacked(computed, sibling));
            }
            index >>= 1;
        }
        return computed == commitmentsRoot;
    }

    receive() external payable {
        revert("Native transfers disabled");
    }
}
