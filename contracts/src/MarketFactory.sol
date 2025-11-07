// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol"; // Pulls base ownership helpers.
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol"; // Enables two-step ownership transfers.
import {Clones} from "@openzeppelin/contracts/proxy/Clones.sol"; // Provides minimal proxy clone helpers.

import {RevealMarket} from "./RevealMarket.sol";
import {IRakeManager} from "./interfaces/IRakeManager.sol";

/// @title MarketFactory
/// @notice Deploys RevealMarket clones with shared configuration.
contract MarketFactory is Ownable2Step {
    using Clones for address;

    event MarketCreated(
        address indexed market,
        string indexed eventId,
        uint256 commitDeadline,
        uint256 revealDeadline,
        address collateral,
        uint256 rakeBps
    );
    event CollateralStatusUpdated(address indexed collateral, bool allowed);
    event DefaultCollateralUpdated(address indexed collateral);
    event AllowlistPauseSet(bool paused, address indexed triggeredBy);
    event GuardianUpdated(address indexed newGuardian);
    event GlobalCommitPauseSet(bool paused, address indexed triggeredBy);
    event GlobalClaimPauseSet(bool paused, address indexed triggeredBy);
    event MarketPaused(address indexed market, bool commitPaused, bool claimPaused, address indexed triggeredBy);
    event MarketGuardianUpdated(address indexed market, address indexed newGuardian);
    event MarketMetadataUpdated(address indexed market, string metadataURI);

    address public implementation; // Address of the RevealMarket implementation clone target.
    address public rakeManager; // Shared rake manager all markets consult.
    address public treasury; // Treasury that ultimately receives rake flows.
    address public verifier; // Shared verifier contract address.
    address public defaultCollateral; // Default collateral token used when none supplied.
    address public guardian; // Guardian allowed to pause/emergency control.
    bool public allowlistPaused; // Global switch preventing collateral allowlist edits/usage.
    bool public globalCommitPaused; // Factory-level flag markets read before accepting commits.
    bool public globalClaimPaused; // Factory-level flag markets read before allowing claims.

    address[] private _markets; // Flat list of all markets deployed by this factory.
    mapping(address => bool) public isMarket; // Quick lookup to ensure an address was factory-deployed.
    mapping(address => bool) public isCollateralAllowed; // Tracks which collateral tokens are permitted.

    constructor(
        address implementation_,
        address rakeManager_,
        address treasury_,
        address verifier_,
        address collateral_
    )
        Ownable(msg.sender)
    {
        if (
            implementation_ == address(0) ||
            rakeManager_ == address(0) ||
            treasury_ == address(0) ||
            verifier_ == address(0)
        ) revert ZeroAddress();

        implementation = implementation_; // Set the implementation clone target.
        rakeManager = rakeManager_; // Wire up the shared rake manager.
        treasury = treasury_; // Store treasury address for rake flows.
        verifier = verifier_; // Store the shared verifier.
        defaultCollateral = collateral_; // Persist the default collateral pointer.

        if (collateral_ != address(0)) {
            isCollateralAllowed[collateral_] = true; // Auto-allow the provided default collateral.
        }
        isCollateralAllowed[address(0)] = true; // Allow sentinel zero address meaning "use default".

        guardian = msg.sender; // Deploying owner starts as guardian as well.
        emit GuardianUpdated(msg.sender); // Surface guardian selection on-chain.
    }

    // ───────────────────────────────
    // Errors
    // ───────────────────────────────
    error ZeroAddress();
    error InvalidDeadlines();
    error CollateralNotAllowed(address collateral);
    error CannotDisableDefaultCollateral();
    error AllowlistPaused();
    error NotGuardianOrOwner();
    error UnknownMarket();
    error InvalidRakeBps();

    // ───────────────────────────────
    // Modifiers
    // ───────────────────────────────
    modifier onlyGuardianOrOwner() {
        _onlyGuardianOrOwner();
        _;
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

    function setDefaultCollateral(address collateral_) external onlyOwner {
        if (allowlistPaused) revert AllowlistPaused(); // Prevent swaps while the allowlist is frozen.
        if (!isCollateralAllowed[collateral_]) revert CollateralNotAllowed(collateral_); // Ensure token is whitelisted.
        defaultCollateral = collateral_; // Swap the default collateral pointer.
        emit DefaultCollateralUpdated(collateral_); // Announce the change.
    }

    function setCollateralStatus(address collateral, bool allowed) external onlyOwner {
        if (allowlistPaused) revert AllowlistPaused();
        if (!allowed && collateral == defaultCollateral) revert CannotDisableDefaultCollateral(); // Protect default.
        isCollateralAllowed[collateral] = allowed; // Toggle allowlist state.
        emit CollateralStatusUpdated(collateral, allowed); // Emit event for indexers.
    }

    function setGuardian(address newGuardian) external onlyOwner {
        if (newGuardian == address(0)) revert ZeroAddress();
        guardian = newGuardian;
        emit GuardianUpdated(newGuardian);
    }

    // ───────────────────────────────
    // Global controls
    // ───────────────────────────────
    function setAllowlistPaused(bool paused) external onlyGuardianOrOwner {
        allowlistPaused = paused; // Store the new allowlist pause state.
        emit AllowlistPauseSet(paused, msg.sender);
    }

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
        if (!isMarket[market]) revert UnknownMarket(); // Only allow factory markets.
        RevealMarket(payable(market)).setCommitPaused(commitPaused); // Propagate commit pause.
        RevealMarket(payable(market)).setClaimPaused(claimPaused); // Propagate claim pause.
        emit MarketPaused(market, commitPaused, claimPaused, msg.sender); // Publish update.
    }

    function setMarketGuardian(address market, address newGuardian) external onlyGuardianOrOwner {
        if (!isMarket[market]) revert UnknownMarket(); // Require known market.
        RevealMarket(payable(market)).setGuardian(newGuardian); // Delegate to market for guardian enforcement.
        emit MarketGuardianUpdated(market, newGuardian); // Publish the guardian change.
    }

    // ───────────────────────────────
    // Market creation
    // ───────────────────────────────
    function createMarket(
        string calldata eventId,
        uint256 commitDeadline,
        uint256 revealDeadline,
        address oracle,
        address collateral,
        uint256 rakeBpsOverride
    ) external onlyOwner returns (address market) {
        if (oracle == address(0)) revert ZeroAddress(); // Oracle must be set.
        if (commitDeadline <= block.timestamp || revealDeadline <= commitDeadline) revert InvalidDeadlines(); // Validate timing.

        market = implementation.clone(); // Deploy the minimal proxy clone.
        address marketCollateral = collateral == address(0) ? defaultCollateral : collateral; // Resolve collateral choice.
        if (!isCollateralAllowed[marketCollateral]) revert CollateralNotAllowed(marketCollateral); // Enforce allowlist.
        if (rakeBpsOverride > IRakeManager(rakeManager).maxRakeBps()) revert InvalidRakeBps(); // Enforce rake cap.

        RevealMarket(payable(market)).initialize(
            eventId,
            commitDeadline,
            revealDeadline,
            oracle,
            verifier,
            rakeManager,
            treasury,
            marketCollateral,
            guardian,
            rakeBpsOverride
        );

        _markets.push(market); // Track the deployed market address.
        isMarket[market] = true; // Mark it as factory-created.

        emit MarketCreated(market, eventId, commitDeadline, revealDeadline, marketCollateral, rakeBpsOverride);
    }

    // ───────────────────────────────
    // View functions
    // ───────────────────────────────
    function getMarkets() external view returns (address[] memory) {
        return _markets; // Return the in-memory copy of deployed market addresses.
    }

    // ───────────────────────────────
    // Internal helpers
    // ───────────────────────────────
    function _onlyGuardianOrOwner() internal view {
        if (msg.sender != owner() && msg.sender != guardian) revert NotGuardianOrOwner();
    }
}
