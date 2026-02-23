// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {Clones} from "@openzeppelin/contracts/proxy/Clones.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {IRevealMarket} from "./interfaces/IRevealMarket.sol";
import {IVerifier} from "./interfaces/IVerifier.sol";

import {ProtocolPool} from "./ProtocolPool.sol";
import {RelayerEscrow} from "./RelayerEscrow.sol";
import {RevealMarket} from "./RevealMarket.sol";

interface IVerifierOwnable {
    function owner() external view returns (address);
}

/// @notice Deploys minimal RevealMarket clones with trusted configuration and registers them with the relayer + protocol pool.
contract MarketFactory is Ownable2Step {
    using Clones for address;

    struct CreateMarketParams {
        address oracle;
        address verifier;
        bytes32 circuitHash;
        uint256 commitDeadline;
        uint256 fixedTicketSize;
        uint256 maxCommitments;
        address authorizationSigner;
        uint256 protocolLiabilityCap;
    }

    address public immutable IMPLEMENTATION;
    address public immutable COLLATERAL_TOKEN;
    RelayerEscrow public relayerEscrow;
    ProtocolPool public protocolPool;

    uint256 public nextMarketId = 1;
    uint256 public globalRakeBps = 200; // 2%
    bool public factoryPaused;
    mapping(address => bool) public isMarket;
    mapping(uint256 => address) public marketForId;
    mapping(address => address) public marketRelayer;
    mapping(address => bool) public knownRelayers;
    address[] public relayerHistory;
    mapping(address => uint256) private activeRelayerRefCount;
    mapping(address => uint256) private activeRelayerIndexPlusOne;
    address[] public activeRelayers;
    mapping(address => bool) public approvedVerifier;
    mapping(address => bytes32) public approvedVerifierCodehash;
    mapping(address => bytes32) public approvedVerifierKeyHash;
    mapping(address => bytes32) public pinnedVerifierCodehash;
    mapping(address => bytes32) public pinnedVerifierKeyHash;
    uint256 public constant MAX_RELAYER_PAUSE_BATCH = 64;

    struct MarketParams {
        address market;
        address oracle;
        address verifier;
        bytes32 circuitHash;
        uint256 commitDeadline;
        uint256 ticketSize;
        uint256 maxCommitments;
        address authorizationSigner;
        uint256 protocolLiabilityCap;
        uint256 rakeBps;
        address relayerEscrow;
        address protocolPool;
        uint256 marketId;
    }

    event MarketCreated(
        uint256 indexed marketId,
        address indexed market,
        address indexed oracle,
        bytes32 circuitHash,
        uint256 ticketSize,
        uint256 commitDeadline,
        uint256 liabilityCap
    );
    event RelayerEscrowUpdated(address indexed relayer);
    event ProtocolPoolUpdated(address indexed pool);
    event GlobalRakeUpdated(uint256 rakeBps);
    event MarketRakeSynced(address indexed market, uint256 rakeBps);
    event FactoryPaused(bool paused);
    event AuthorizationSignerUpdated(address indexed market, address indexed signer);
    event OracleUpdated(address indexed market, address indexed oracle);
    event MarketRelayerUpdated(address indexed market, address indexed relayer);
    event MarketVerifierUpdated(address indexed market, address indexed verifier, bytes32 indexed circuitHash);
    event MarketLockedVerifierKeyRefreshed(address indexed market, bytes32 indexed keyHash);
    event VerifierApprovalUpdated(address indexed verifier, bytes32 codehash, bytes32 keyHash, bool approved);
    event MarketLiabilityCapUpdated(address indexed market, uint256 liabilityCap);
    event MarketProtocolPoolUpdated(address indexed market, address indexed protocolPool);
    event MarketClaimDeadlineExtended(address indexed market, uint256 newDeadline);
    event MarketRefundDeadlineExtended(address indexed market, uint256 newDeadline);
    event MarketClaimsSwept(address indexed market, address indexed recipient);
    event RelayerCommitsPaused(bool paused);
    event RelayerCommitsPausedBatch(bool paused, uint256 start, uint256 processed);
    event RelayerPausePropagationFailed(address indexed relayer);
    event RelayerUnregisterFailed(address indexed market, address indexed relayer);
    event EscrowBalanceMigrated(
        address indexed market, address indexed user, address fromRelayer, address toRelayer, uint256 amount
    );
    event MarketCommitsPaused(address indexed market, bool paused);
    event MarketClaimsPaused(address indexed market, bool paused);
    event MarketRefundsEnabled(address indexed market);
    event MarketRefundsSwept(address indexed market, address indexed recipient);

    error InvalidImplementation();
    error InvalidRelayer();
    error InvalidProtocolPool();
    error InvalidCollateralToken();
    error InvalidOracle();
    error InvalidVerifier();
    error InvalidSigner();
    error InvalidTicketSize();
    error InvalidDeadlines();
    error InvalidRakeBps();
    error UnknownMarket();
    error FactoryPausedErr();
    error DependencyNotHooked();
    error InvalidVerifierInputs();
    error InvalidCircuitHash();
    error VerifierNotApproved();
    error VerifierDrift();
    error VerifierOwnerMismatch();
    error RelayerPauseFailed(address relayer);
    error InvalidPauseRange();
    error PauseBatchTooLarge();
    error RelayerRotationLocked();
    error ProtocolPoolRotationLocked();

    constructor(
        address implementation_,
        ProtocolPool protocolPool_,
        RelayerEscrow relayerEscrow_,
        address collateralToken_,
        address owner_
    ) Ownable(owner_) {
        if (implementation_ == address(0)) revert InvalidImplementation();
        if (address(protocolPool_) == address(0)) revert InvalidProtocolPool();
        if (address(relayerEscrow_) == address(0)) revert InvalidRelayer();
        if (collateralToken_ == address(0)) revert InvalidCollateralToken();
        IMPLEMENTATION = implementation_;
        protocolPool = protocolPool_;
        relayerEscrow = relayerEscrow_;
        COLLATERAL_TOKEN = collateralToken_;
        _trackRelayer(address(relayerEscrow_));
    }

    /// @notice Owner can update the relayer escrow address (e.g., when rotating relayers).
    function setRelayerEscrow(RelayerEscrow relayer) external onlyOwner {
        if (address(relayer) == address(0)) revert InvalidRelayer();
        if (address(relayer.COLLATERAL_TOKEN()) != COLLATERAL_TOKEN) revert InvalidRelayer();
        if (relayer.marketFactory() != address(this)) revert DependencyNotHooked();
        relayerEscrow = relayer;
        _trackRelayer(address(relayer));
        emit RelayerEscrowUpdated(address(relayer));
    }

    /// @notice Owner can update the protocol pool.
    function setProtocolPool(ProtocolPool pool) external onlyOwner {
        if (address(pool) == address(0)) revert InvalidProtocolPool();
        if (address(pool.COLLATERAL_TOKEN()) != COLLATERAL_TOKEN) revert InvalidProtocolPool();
        if (pool.marketFactory() != address(this)) revert DependencyNotHooked();
        protocolPool = pool;
        emit ProtocolPoolUpdated(address(pool));
    }

    /// @notice Syncs this factory into the relayer + protocol pool hooks.
    function syncFactoryHooks() external view onlyOwner {
        if (protocolPool.marketFactory() != address(this)) revert DependencyNotHooked();
        if (relayerEscrow.marketFactory() != address(this)) revert DependencyNotHooked();
    }

    /// @notice Explicit verifier attestation gate; market creation/rotation is blocked unless approved.
    function setVerifierApproval(address verifier, bool approved) external onlyOwner {
        if (verifier == address(0)) revert InvalidVerifier();
        if (approved) {
            _requireVerifierOwnership(verifier);
            if (IVerifier(verifier).expectedInputs() != 10) revert InvalidVerifierInputs();
            bytes32 codehash = verifier.codehash;
            bytes32 keyHash = IVerifier(verifier).verifyingKeyHash();
            bytes32 pinnedCodehash = pinnedVerifierCodehash[verifier];
            if (pinnedCodehash == bytes32(0)) {
                pinnedVerifierCodehash[verifier] = codehash;
                pinnedVerifierKeyHash[verifier] = keyHash;
            } else if (pinnedCodehash != codehash || pinnedVerifierKeyHash[verifier] != keyHash) {
                revert VerifierDrift();
            }
            approvedVerifier[verifier] = true;
            approvedVerifierCodehash[verifier] = pinnedVerifierCodehash[verifier];
            approvedVerifierKeyHash[verifier] = pinnedVerifierKeyHash[verifier];
            emit VerifierApprovalUpdated(
                verifier, approvedVerifierCodehash[verifier], approvedVerifierKeyHash[verifier], true
            );
            return;
        }

        approvedVerifier[verifier] = false;
        emit VerifierApprovalUpdated(
            verifier, approvedVerifierCodehash[verifier], approvedVerifierKeyHash[verifier], false
        );
    }

    /// @notice Runtime verifier policy check used by markets during settlement.
    function isVerifierCurrentlyApproved(address verifier, bytes32 expectedCircuitHash) external view returns (bool) {
        if (verifier == address(0)) return false;
        if (!approvedVerifier[verifier]) return false;
        try IVerifierOwnable(verifier).owner() returns (address verifierOwner) {
            if (verifierOwner != owner()) return false;
        } catch {
            return false;
        }
        if (verifier.codehash != approvedVerifierCodehash[verifier]) return false;
        if (IVerifier(verifier).expectedInputs() != 10) return false;
        if (IVerifier(verifier).circuitHash() != expectedCircuitHash) return false;
        if (IVerifier(verifier).verifyingKeyHash() != approvedVerifierKeyHash[verifier]) return false;
        return true;
    }

    /// @notice Updates the global rake applied to all markets.
    function setGlobalRakeBps(uint256 rakeBps) external onlyOwner {
        if (rakeBps > 10_000) revert InvalidRakeBps();
        globalRakeBps = rakeBps;
        emit GlobalRakeUpdated(rakeBps);
    }

    /// @notice Pushes the current global rake to an existing market.
    function syncMarketRake(address market) external onlyOwner {
        if (!isMarket[market]) revert UnknownMarket();
        RevealMarket(payable(market)).setRakeBps(globalRakeBps);
        emit MarketRakeSynced(market, globalRakeBps);
    }

    /// @notice Override rake for a specific market (before settlement).
    function setMarketRake(address market, uint256 rakeBps) external onlyOwner {
        if (!isMarket[market]) revert UnknownMarket();
        RevealMarket(payable(market)).setRakeBps(rakeBps);
        emit MarketRakeSynced(market, rakeBps);
    }

    /// @notice Pause/unpause market creation.
    function setFactoryPaused(bool paused) external onlyOwner {
        factoryPaused = paused;
        emit FactoryPaused(paused);
    }

    /// @notice Rotate the authorization signer for a specific market (key hygiene).
    function updateAuthorizationSigner(address market, address newSigner) external onlyOwner {
        if (!isMarket[market]) revert UnknownMarket();
        if (newSigner == address(0)) revert InvalidSigner();
        RevealMarket(payable(market)).setAuthorizationSigner(newSigner);
        emit AuthorizationSignerUpdated(market, newSigner);
    }

    /// @notice Rotate the oracle for a specific market.
    function updateOracle(address market, address newOracle) external onlyOwner {
        if (!isMarket[market]) revert UnknownMarket();
        if (newOracle == address(0)) revert InvalidOracle();
        RevealMarket(payable(market)).setOracle(newOracle);
        emit OracleUpdated(market, newOracle);
    }

    /// @notice Point a market at a new relayer escrow (e.g., relayer rotation).
    function updateMarketRelayer(address market, RelayerEscrow newRelayer) external onlyOwner {
        if (!isMarket[market]) revert UnknownMarket();
        if (address(newRelayer) == address(0)) revert InvalidRelayer();
        if (address(newRelayer.COLLATERAL_TOKEN()) != COLLATERAL_TOKEN) revert InvalidRelayer();
        if (newRelayer.marketFactory() != address(this)) revert InvalidRelayer();
        RevealMarket rm = RevealMarket(payable(market));
        if (rm.phase() != IRevealMarket.Phase.Commit || rm.nextTicketId() != 0) revert RelayerRotationLocked();
        address oldRelayer = rm.relayerEscrow();
        if (oldRelayer == address(newRelayer)) return;
        try RelayerEscrow(payable(oldRelayer)).unregisterMarket(market) {}
        catch {
            emit RelayerUnregisterFailed(market, oldRelayer);
        }
        _deactivateRelayer(oldRelayer);
        rm.setRelayerEscrow(address(newRelayer));
        newRelayer.registerMarket(market);
        _trackRelayer(address(newRelayer));
        _activateRelayer(address(newRelayer));
        marketRelayer[market] = address(newRelayer);
        emit MarketRelayerUpdated(market, address(newRelayer));
    }

    /// @notice Moves user balances from an old relayer escrow to the market's active relayer.
    function migrateMarketRelayerBalances(address market, RelayerEscrow oldRelayer, address[] calldata users)
        external
        onlyOwner
    {
        if (!isMarket[market]) revert UnknownMarket();
        address targetRelayerAddress = RevealMarket(payable(market)).relayerEscrow();
        if (address(oldRelayer) == targetRelayerAddress) revert InvalidRelayer();

        RelayerEscrow targetRelayer = RelayerEscrow(payable(targetRelayerAddress));
        for (uint256 i = 0; i < users.length; ++i) {
            address user = users[i];
            uint256 balance = oldRelayer.balances(user);
            if (balance == 0) continue;
            oldRelayer.withdrawTo(user, targetRelayerAddress, balance);
            targetRelayer.creditMigrated(user, balance);
            emit EscrowBalanceMigrated(market, user, address(oldRelayer), targetRelayerAddress, balance);
        }
    }

    /// @notice Rotate verifier metadata for an existing market.
    function updateMarketVerifier(address market, address newVerifier, bytes32 newCircuitHash) external onlyOwner {
        if (!isMarket[market]) revert UnknownMarket();
        _validateVerifier(newVerifier, newCircuitHash);
        RevealMarket(payable(market)).setVerifier(newVerifier, newCircuitHash);
        emit MarketVerifierUpdated(market, newVerifier, newCircuitHash);
    }

    /// @notice Refreshes a locked market's verifier key anchor before any batch proof is accepted.
    function refreshMarketLockedVerifierKey(address market) external onlyOwner {
        if (!isMarket[market]) revert UnknownMarket();
        RevealMarket rm = RevealMarket(payable(market));
        _validateVerifier(rm.verifier(), rm.circuitHash());
        rm.refreshLockedVerifierKeyHash();
        emit MarketLockedVerifierKeyRefreshed(market, rm.lockedVerifierKeyHash());
    }

    /// @notice Re-route an existing market to a new protocol pool during commit phase.
    function updateMarketProtocolPool(address market, ProtocolPool newPool) external onlyOwner {
        if (!isMarket[market]) revert UnknownMarket();
        if (address(newPool) == address(0)) revert InvalidProtocolPool();
        if (address(newPool.COLLATERAL_TOKEN()) != COLLATERAL_TOKEN) revert InvalidProtocolPool();
        if (newPool.marketFactory() != address(this)) revert DependencyNotHooked();

        RevealMarket rm = RevealMarket(payable(market));
        if (rm.phase() != IRevealMarket.Phase.Commit || rm.nextTicketId() != 0) revert ProtocolPoolRotationLocked();
        uint256 cap = rm.protocolLiabilityCap();
        newPool.registerMarket(market, cap);
        rm.setProtocolPool(address(newPool));
        emit MarketProtocolPoolUpdated(market, address(newPool));
    }

    /// @notice Update the protocol liability cap for a market (before settlement).
    function updateProtocolLiabilityCap(address market, uint256 newCap) external onlyOwner {
        if (!isMarket[market]) revert UnknownMarket();
        RevealMarket rm = RevealMarket(payable(market));
        rm.setProtocolLiabilityCap(newCap);
        ProtocolPool(rm.protocolPool()).updateLiabilityCap(market, newCap);
        emit MarketLiabilityCapUpdated(market, newCap);
    }

    /// @notice Extend a market's commit deadline (factory-only guard).
    function extendMarketCommitDeadline(address market, uint256 newDeadline) external onlyOwner {
        if (!isMarket[market]) revert UnknownMarket();
        RevealMarket(payable(market)).extendCommitDeadline(newDeadline);
    }

    /// @notice Extend a market's claim deadline (factory-only guard).
    function extendMarketClaimDeadline(address market, uint256 newDeadline) external onlyOwner {
        if (!isMarket[market]) revert UnknownMarket();
        RevealMarket(payable(market)).extendClaimDeadline(newDeadline);
        emit MarketClaimDeadlineExtended(market, newDeadline);
    }

    /// @notice Extend a market's cancelled refund deadline (factory-only guard).
    function extendMarketRefundDeadline(address market, uint256 newDeadline) external onlyOwner {
        if (!isMarket[market]) revert UnknownMarket();
        RevealMarket(payable(market)).extendRefundDeadline(newDeadline);
        emit MarketRefundDeadlineExtended(market, newDeadline);
    }

    /// @notice Sweep unclaimed payouts after the claim deadline (factory-only guard).
    function sweepUnclaimed(address market, address recipient) external onlyOwner {
        if (!isMarket[market]) revert UnknownMarket();
        RevealMarket(payable(market)).sweepUnclaimed(recipient);
        emit MarketClaimsSwept(market, recipient);
    }

    /// @notice Enables refunds for a market after commit window close or lock timeout.
    function enableMarketRefunds(address market) external onlyOwner {
        if (!isMarket[market]) revert UnknownMarket();
        RevealMarket(payable(market)).enableRefunds();
        emit MarketRefundsEnabled(market);
    }

    /// @notice Sweep unrefunded collateral for cancelled markets after refund deadline.
    function sweepCancelledRefunds(address market, address recipient) external onlyOwner {
        if (!isMarket[market]) revert UnknownMarket();
        RevealMarket(payable(market)).sweepCancelledRefunds(recipient);
        emit MarketRefundsSwept(market, recipient);
    }

    /// @notice Pause or unpause commits on a market (emergency stop).
    function setMarketCommitsPaused(address market, bool paused) external onlyOwner {
        if (!isMarket[market]) revert UnknownMarket();
        RevealMarket(payable(market)).setCommitsPaused(paused);
        emit MarketCommitsPaused(market, paused);
    }

    /// @notice Pause or unpause claims on a market (emergency stop).
    function setMarketClaimsPaused(address market, bool paused) external onlyOwner {
        if (!isMarket[market]) revert UnknownMarket();
        RevealMarket(payable(market)).setClaimsPaused(paused);
        emit MarketClaimsPaused(market, paused);
    }

    /// @notice Emergency pause for relayer escrow commits (guardian stop).
    function setRelayerCommitsPaused(bool paused) external onlyOwner {
        uint256 len = activeRelayers.length;
        if (len == 0) {
            emit RelayerCommitsPaused(paused);
            return;
        }
        uint256 start = 0;
        while (start < len) {
            uint256 count = len - start;
            if (count > MAX_RELAYER_PAUSE_BATCH) {
                count = MAX_RELAYER_PAUSE_BATCH;
            }
            _setRelayerCommitsPausedBatch(paused, start, count);
            emit RelayerCommitsPausedBatch(paused, start, count);
            start += count;
        }
        emit RelayerCommitsPaused(paused);
    }

    /// @notice Emergency pause fanout in bounded chunks for large active relayer sets.
    function setRelayerCommitsPausedBatch(bool paused, uint256 start, uint256 count) external onlyOwner {
        _setRelayerCommitsPausedBatch(paused, start, count);
        emit RelayerCommitsPausedBatch(paused, start, count);
    }

    /// @notice Deploys a new minimal market clone with the given parameters.
    function createMarket(CreateMarketParams calldata params) external onlyOwner returns (address market) {
        if (factoryPaused) revert FactoryPausedErr();
        if (params.oracle == address(0)) revert InvalidOracle();
        if (params.verifier == address(0)) revert InvalidVerifier();
        if (params.authorizationSigner == address(0)) revert InvalidSigner();
        if (params.fixedTicketSize == 0) revert InvalidTicketSize();
        if (params.commitDeadline <= block.timestamp) revert InvalidDeadlines();
        if (protocolPool.marketFactory() != address(this)) revert DependencyNotHooked();
        if (relayerEscrow.marketFactory() != address(this)) revert DependencyNotHooked();
        if (address(protocolPool.COLLATERAL_TOKEN()) != COLLATERAL_TOKEN) revert InvalidProtocolPool();
        if (address(relayerEscrow.COLLATERAL_TOKEN()) != COLLATERAL_TOKEN) revert InvalidRelayer();
        _validateVerifier(params.verifier, params.circuitHash);
        uint256 appliedRakeBps = globalRakeBps;

        uint256 marketId = nextMarketId++;
        address payable deployedMarket = payable(IMPLEMENTATION.cloneDeterministic(bytes32(marketId)));

        RevealMarket(deployedMarket)
            .initialize(
                RevealMarket.InitParams({
                    factory: address(this),
                    protocolPool: address(protocolPool),
                    relayerEscrow: address(relayerEscrow),
                    oracle: params.oracle,
                    verifier: params.verifier,
                    circuitHash: params.circuitHash,
                    collateralToken: COLLATERAL_TOKEN,
                    commitDeadline: params.commitDeadline,
                    ticketSize: params.fixedTicketSize,
                    maxCommitments: params.maxCommitments,
                    authorizationSigner: params.authorizationSigner,
                    protocolLiabilityCap: params.protocolLiabilityCap,
                    marketId: marketId,
                    rakeBps: appliedRakeBps
                })
            );

        isMarket[deployedMarket] = true;
        marketForId[marketId] = deployedMarket;
        marketRelayer[deployedMarket] = address(relayerEscrow);

        protocolPool.registerMarket(deployedMarket, params.protocolLiabilityCap);
        relayerEscrow.registerMarket(deployedMarket);
        _trackRelayer(address(relayerEscrow));
        _activateRelayer(address(relayerEscrow));

        market = deployedMarket;

        emit MarketCreated(
            marketId,
            deployedMarket,
            params.oracle,
            params.circuitHash,
            params.fixedTicketSize,
            params.commitDeadline,
            params.protocolLiabilityCap
        );
    }

    /// @notice Predicts the deterministic clone address for a given market id.
    function predictMarketAddress(uint256 marketId) external view returns (address) {
        return IMPLEMENTATION.predictDeterministicAddress(bytes32(marketId), address(this));
    }

    /// @notice Returns the deployed address for a market id or reverts if unknown.
    function marketAddress(uint256 marketId) public view returns (address) {
        address market = marketForId[marketId];
        if (market == address(0)) revert UnknownMarket();
        return market;
    }

    /// @notice Returns the initialization/runtime parameters for a given market id.
    function getMarketParams(uint256 marketId) external view returns (MarketParams memory params) {
        address market = marketAddress(marketId);
        RevealMarket rm = RevealMarket(payable(market));
        params = MarketParams({
            market: market,
            oracle: rm.oracle(),
            verifier: rm.verifier(),
            circuitHash: rm.circuitHash(),
            commitDeadline: rm.commitDeadline(),
            ticketSize: rm.ticketSize(),
            maxCommitments: rm.maxCommitments(),
            authorizationSigner: rm.authorizationSigner(),
            protocolLiabilityCap: rm.protocolLiabilityCap(),
            rakeBps: rm.rakeBps(),
            relayerEscrow: rm.relayerEscrow(),
            protocolPool: rm.protocolPool(),
            marketId: marketId
        });
    }

    function _validateVerifier(address verifier, bytes32 expectedCircuitHash) internal view {
        if (verifier == address(0)) revert InvalidVerifier();
        if (!approvedVerifier[verifier]) revert VerifierNotApproved();
        _requireVerifierOwnership(verifier);
        if (IVerifier(verifier).expectedInputs() != 10) revert InvalidVerifierInputs();
        if (IVerifier(verifier).circuitHash() != expectedCircuitHash) revert InvalidCircuitHash();
        if (verifier.codehash != approvedVerifierCodehash[verifier]) revert VerifierDrift();
        if (IVerifier(verifier).verifyingKeyHash() != approvedVerifierKeyHash[verifier]) revert VerifierDrift();
    }

    function _requireVerifierOwnership(address verifier) internal view {
        try IVerifierOwnable(verifier).owner() returns (address verifierOwner) {
            if (verifierOwner != owner()) revert VerifierOwnerMismatch();
        } catch {
            revert VerifierOwnerMismatch();
        }
    }

    function _setRelayerCommitsPausedBatch(bool paused, uint256 start, uint256 count) internal {
        uint256 len = activeRelayers.length;
        if (start > len) revert InvalidPauseRange();
        if (count == 0) revert InvalidPauseRange();
        if (count > MAX_RELAYER_PAUSE_BATCH) revert PauseBatchTooLarge();
        if (start + count > len) revert InvalidPauseRange();

        for (uint256 i = 0; i < count; ++i) {
            address relayer = activeRelayers[start + i];
            try RelayerEscrow(payable(relayer)).setCommitsPaused(paused) {
                try RelayerEscrow(payable(relayer)).commitsPaused() returns (bool relayerPaused) {
                    if (relayerPaused != paused) {
                        emit RelayerPausePropagationFailed(relayer);
                    }
                } catch {
                    emit RelayerPausePropagationFailed(relayer);
                }
            } catch {
                emit RelayerPausePropagationFailed(relayer);
            }
        }
    }

    function _activateRelayer(address relayer) internal {
        uint256 refs = activeRelayerRefCount[relayer];
        activeRelayerRefCount[relayer] = refs + 1;
        if (refs != 0) return;
        activeRelayerIndexPlusOne[relayer] = activeRelayers.length + 1;
        activeRelayers.push(relayer);
    }

    function _deactivateRelayer(address relayer) internal {
        uint256 refs = activeRelayerRefCount[relayer];
        if (refs == 0) return;
        if (refs > 1) {
            activeRelayerRefCount[relayer] = refs - 1;
            return;
        }

        activeRelayerRefCount[relayer] = 0;
        uint256 index = activeRelayerIndexPlusOne[relayer];
        if (index == 0) return;
        uint256 idx = index - 1;
        uint256 lastIdx = activeRelayers.length - 1;
        if (idx != lastIdx) {
            address moved = activeRelayers[lastIdx];
            activeRelayers[idx] = moved;
            activeRelayerIndexPlusOne[moved] = idx + 1;
        }
        activeRelayers.pop();
        activeRelayerIndexPlusOne[relayer] = 0;
    }

    function _trackRelayer(address relayer) internal {
        if (knownRelayers[relayer]) {
            return;
        }
        knownRelayers[relayer] = true;
        relayerHistory.push(relayer);
    }
}
