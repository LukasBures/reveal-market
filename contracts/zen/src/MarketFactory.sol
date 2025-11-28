// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {Clones} from "@openzeppelin/contracts/proxy/Clones.sol";

import {RevealMarket} from "./RevealMarket.sol";
import {IMarketFactoryRisk} from "./interfaces/IMarketFactoryRisk.sol";
import {IMarketFactoryStatus} from "./interfaces/IMarketFactoryStatus.sol";
import {IRakeManager} from "./interfaces/IRakeManager.sol";

/// @title MarketFactory – deploys ZEN-only RevealMarket instances with risk controls.
contract MarketFactory is Ownable2Step, IMarketFactoryRisk, IMarketFactoryStatus {
    using Clones for address;

    struct CreateMarketParams {
        string eventId;
        uint256 commitDeadline;
        uint256 revealDeadline;
        address oracle;
        uint256 rakeBpsOverride;
        uint256 payoutMultiplier;
        RevealMarket.PayoutCurve payoutCurve;
        uint256 floatAmount;
        uint256 maxMarketSize;
        uint256 minCommitmentSize;
        uint256 maxTicketsPerUser;
        uint256 maxCommitments;
    }

    event MarketCreated(
        address indexed market,
        string indexed eventId,
        uint256 commitDeadline,
        uint256 revealDeadline,
        uint256 payoutMultiplier,
        uint8 payoutCurve,
        uint256 floatAmount,
        uint256 rakeBps,
        uint256 maxMarketSize
    );
    event GuardianUpdated(address indexed newGuardian);
    event GlobalCommitPauseSet(bool paused, address indexed triggeredBy);
    event GlobalClaimPauseSet(bool paused, address indexed triggeredBy);
    event MarketPaused(address indexed market, bool commitPaused, bool claimPaused, address indexed triggeredBy);
    event MarketGuardianUpdated(address indexed market, address indexed newGuardian);
    event LimitsUpdated(uint256 marketMaxSize, uint256 maxMarketLiability, uint256 maxGlobalLiability);
    event FloatSeeded(address indexed market, uint256 amount);

    address public implementation;
    address public rakeManager;
    address public treasury;
    address public verifier;
    address public guardian;
    address public pricingSigner;
    bool public override globalCommitPaused;
    bool public override globalClaimPaused;

    uint256 public override marketMaxSize;
    uint256 public override maxMarketLiability;
    uint256 public override maxGlobalLiability;
    uint256 public override totalRecordedLiability;

    address[] private _markets;
    mapping(address => bool) public isMarket;
    mapping(address => uint256) public override marketLiability;
    mapping(address => uint256) public override marketFloatAllocation;
    mapping(address => uint256) public marketSizeLimit;

    error ZeroAddress();
    error InvalidPayoutMultiplier();
    error InvalidDeadlines();
    error NotGuardianOrOwner();
    error UnknownMarket();
    error InvalidRakeBps();
    error InvalidFloatPayment();
    error MarketSizeExceeded();
    error MarketLiabilityExceeded();
    error GlobalLiabilityExceeded();
    error NotTreasuryOrOwner();

    modifier onlyGuardianOrOwner() {
        _onlyGuardianOrOwner();
        _;
    }

    constructor(address implementation_, address rakeManager_, address treasury_, address verifier_, address pricingSigner_)
        Ownable(msg.sender)
    {
        if (
            implementation_ == address(0) || rakeManager_ == address(0) || treasury_ == address(0) || verifier_ == address(0)
                || pricingSigner_ == address(0)
        ) revert ZeroAddress();

        implementation = implementation_;
        rakeManager = rakeManager_;
        treasury = treasury_;
        verifier = verifier_;
        guardian = msg.sender;
        pricingSigner = pricingSigner_;
        emit GuardianUpdated(msg.sender);
    }

    // ───────────────────────────────
    // Admin setters
    // ───────────────────────────────
    function setImplementation(address implementation_) external onlyOwner {
        if (implementation_ == address(0)) revert ZeroAddress();
        implementation = implementation_;
    }

    function setRakeManager(address rakeManager_) external onlyOwner {
        if (rakeManager_ == address(0)) revert ZeroAddress();
        rakeManager = rakeManager_;
    }

    function setTreasury(address treasury_) external onlyOwner {
        if (treasury_ == address(0)) revert ZeroAddress();
        treasury = treasury_;
    }

    function setVerifier(address verifier_) external onlyOwner {
        if (verifier_ == address(0)) revert ZeroAddress();
        verifier = verifier_;
    }

    function setPricingSigner(address pricingSigner_) external onlyOwner {
        if (pricingSigner_ == address(0)) revert ZeroAddress();
        pricingSigner = pricingSigner_;
    }

    function setGuardian(address newGuardian) external onlyOwner {
        if (newGuardian == address(0)) revert ZeroAddress();
        guardian = newGuardian;
        emit GuardianUpdated(newGuardian);
    }

    function setRiskLimits(uint256 marketMaxSize_, uint256 maxMarketLiability_, uint256 maxGlobalLiability_)
        external
        onlyOwner
    {
        marketMaxSize = marketMaxSize_;
        maxMarketLiability = maxMarketLiability_;
        maxGlobalLiability = maxGlobalLiability_;
        _enforceGlobalLiability(totalRecordedLiability);
        emit LimitsUpdated(marketMaxSize_, maxMarketLiability_, maxGlobalLiability_);
    }

    // ───────────────────────────────
    // Global controls
    // ───────────────────────────────
    function setGlobalCommitPaused(bool paused) external onlyGuardianOrOwner {
        globalCommitPaused = paused;
        emit GlobalCommitPauseSet(paused, msg.sender);
    }

    function setGlobalClaimPaused(bool paused) external onlyGuardianOrOwner {
        globalClaimPaused = paused;
        emit GlobalClaimPauseSet(paused, msg.sender);
    }

    // ───────────────────────────────
    // Per-market controls
    // ───────────────────────────────
    function setMarketPauses(address market, bool commitPaused, bool claimPaused) external onlyGuardianOrOwner {
        if (!isMarket[market]) revert UnknownMarket();
        RevealMarket(payable(market)).setCommitPaused(commitPaused);
        RevealMarket(payable(market)).setClaimPaused(claimPaused);
        emit MarketPaused(market, commitPaused, claimPaused, msg.sender);
    }

    function setMarketGuardian(address market, address newGuardian) external onlyGuardianOrOwner {
        if (!isMarket[market]) revert UnknownMarket();
        RevealMarket(payable(market)).setGuardian(newGuardian);
        emit MarketGuardianUpdated(market, newGuardian);
    }

    // ───────────────────────────────
    // Market creation / funding
    // ───────────────────────────────
    function createMarket(CreateMarketParams calldata params) external payable onlyOwner returns (address market) {
        if (params.oracle == address(0)) revert ZeroAddress();
        if (params.commitDeadline <= block.timestamp || params.revealDeadline <= params.commitDeadline) {
            revert InvalidDeadlines();
        }
        if (params.payoutMultiplier == 0) revert InvalidPayoutMultiplier();
        uint256 maxRake = IRakeManager(rakeManager).maxRakeBps();
        if (params.rakeBpsOverride > maxRake) revert InvalidRakeBps();
        if (msg.value != params.floatAmount) revert InvalidFloatPayment();

        market = implementation.clone();
        uint256 marketSize = params.maxMarketSize == 0 ? marketMaxSize : params.maxMarketSize;
        RevealMarket.InitConfig memory cfg = RevealMarket.InitConfig({
            eventId: params.eventId,
            commitDeadline: params.commitDeadline,
            revealDeadline: params.revealDeadline,
            oracle: params.oracle,
            verifier: verifier,
            rakeManager: rakeManager,
            treasury: treasury,
            guardian: guardian,
            rakeBpsOverride: params.rakeBpsOverride,
            payoutMultiplier: params.payoutMultiplier,
            payoutCurve: params.payoutCurve,
            maxMarketSize: marketSize,
            pricingSigner: pricingSigner,
            minCommitmentSize: params.minCommitmentSize,
            maxTicketsPerUser: params.maxTicketsPerUser,
            maxCommitments: params.maxCommitments
        });
        RevealMarket(payable(market)).initialize(cfg);

        _markets.push(market);
        isMarket[market] = true;
        marketSizeLimit[market] = marketSize;
        if (params.floatAmount > 0) {
            RevealMarket(payable(market)).fundMarket{value: params.floatAmount}(params.floatAmount);
            marketFloatAllocation[market] = params.floatAmount;
            emit FloatSeeded(market, params.floatAmount);
        }

        emit MarketCreated(
            market,
            params.eventId,
            params.commitDeadline,
            params.revealDeadline,
            params.payoutMultiplier,
            uint8(params.payoutCurve),
            params.floatAmount,
            params.rakeBpsOverride,
            marketSize
        );
    }

    function seedMarketFloat(address market, uint256 amount) external payable {
        if (msg.sender != owner() && msg.sender != treasury) revert NotTreasuryOrOwner();
        if (!isMarket[market]) revert UnknownMarket();
        if (amount == 0 || msg.value != amount) revert InvalidFloatPayment();
        RevealMarket(payable(market)).fundMarket{value: amount}(amount);
        emit FloatSeeded(market, amount);
    }

    // ───────────────────────────────
    // View functions
    // ───────────────────────────────
    function getMarkets() external view returns (address[] memory) {
        return _markets;
    }

    // ───────────────────────────────
    // Risk accounting (IMarketFactoryRisk)
    // ───────────────────────────────
    function syncAccounting(address market, uint256 escrow, uint256 floatBalance, uint256 liability) external override {
        if (market != msg.sender || !isMarket[msg.sender]) revert UnknownMarket();
        uint256 totalBalance = escrow + floatBalance;

        uint256 perMarketLimit = marketSizeLimit[market];
        if (perMarketLimit == 0) {
            perMarketLimit = marketMaxSize;
        }
        if (perMarketLimit != 0 && totalBalance > perMarketLimit) revert MarketSizeExceeded();
        if (maxMarketLiability != 0 && liability > maxMarketLiability) revert MarketLiabilityExceeded();

        uint256 updatedGlobal = totalRecordedLiability - marketLiability[msg.sender] + liability;
        _enforceGlobalLiability(updatedGlobal);
        totalRecordedLiability = updatedGlobal;
        marketLiability[msg.sender] = liability;
        marketFloatAllocation[msg.sender] = floatBalance;
    }

    // ───────────────────────────────
    // Internal helpers
    // ───────────────────────────────
    function _onlyGuardianOrOwner() internal view {
        if (msg.sender != owner() && msg.sender != guardian) revert NotGuardianOrOwner();
    }

    function _enforceGlobalLiability(uint256 candidate) internal view {
        if (maxGlobalLiability != 0 && candidate > maxGlobalLiability) revert GlobalLiabilityExceeded();
    }
}
