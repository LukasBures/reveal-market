// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {Clones} from "@openzeppelin/contracts/proxy/Clones.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";

import {ProtocolPool} from "./ProtocolPool.sol";
import {RelayerEscrow} from "./RelayerEscrow.sol";
import {RevealMarket} from "./RevealMarket.sol";

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
    event MarketLiabilityCapUpdated(address indexed market, uint256 liabilityCap);
    event MarketClaimDeadlineExtended(address indexed market, uint256 newDeadline);
    event MarketClaimsSwept(address indexed market, address indexed recipient);
    event RelayerCommitsPaused(bool paused);
    event MarketCommitsPaused(address indexed market, bool paused);
    event MarketClaimsPaused(address indexed market, bool paused);

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
    }

    /// @notice Owner can update the relayer escrow address (e.g., when rotating relayers).
    function setRelayerEscrow(RelayerEscrow relayer) external onlyOwner {
        if (address(relayer) == address(0)) revert InvalidRelayer();
        relayerEscrow = relayer;
        emit RelayerEscrowUpdated(address(relayer));
    }

    /// @notice Owner can update the protocol pool.
    function setProtocolPool(ProtocolPool pool) external onlyOwner {
        if (address(pool) == address(0)) revert InvalidProtocolPool();
        protocolPool = pool;
        emit ProtocolPoolUpdated(address(pool));
    }

    /// @notice Syncs this factory into the relayer + protocol pool hooks.
    function syncFactoryHooks() external onlyOwner {
        protocolPool.setMarketFactory(address(this));
        relayerEscrow.setMarketFactory(address(this));
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
        if (newRelayer.marketFactory() != address(this)) revert InvalidRelayer();
        newRelayer.registerMarket(market);
        RevealMarket(payable(market)).setRelayerEscrow(address(newRelayer));
        emit MarketRelayerUpdated(market, address(newRelayer));
    }

    /// @notice Update the protocol liability cap for a market (before settlement).
    function updateProtocolLiabilityCap(address market, uint256 newCap) external onlyOwner {
        if (!isMarket[market]) revert UnknownMarket();
        RevealMarket(payable(market)).setProtocolLiabilityCap(newCap);
        protocolPool.updateLiabilityCap(market, newCap);
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

    /// @notice Sweep unclaimed payouts after the claim deadline (factory-only guard).
    function sweepUnclaimed(address market, address recipient) external onlyOwner {
        if (!isMarket[market]) revert UnknownMarket();
        RevealMarket(payable(market)).sweepUnclaimed(recipient);
        emit MarketClaimsSwept(market, recipient);
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
        relayerEscrow.setCommitsPaused(paused);
        emit RelayerCommitsPaused(paused);
    }

    /// @notice Deploys a new minimal market clone with the given parameters.
    function createMarket(CreateMarketParams calldata params) external onlyOwner returns (address market) {
        if (factoryPaused) revert FactoryPausedErr();
        if (params.oracle == address(0)) revert InvalidOracle();
        if (params.verifier == address(0)) revert InvalidVerifier();
        if (params.authorizationSigner == address(0)) revert InvalidSigner();
        if (params.fixedTicketSize == 0) revert InvalidTicketSize();
        if (params.commitDeadline <= block.timestamp) revert InvalidDeadlines();
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

        protocolPool.registerMarket(deployedMarket, params.protocolLiabilityCap);
        relayerEscrow.registerMarket(deployedMarket);

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
            protocolPool: address(protocolPool),
            marketId: marketId
        });
    }
}
