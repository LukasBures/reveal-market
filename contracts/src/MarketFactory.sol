// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {Clones} from "@openzeppelin/contracts/proxy/Clones.sol";

import {RevealMarket} from "./RevealMarket.sol";

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
        string metadataURI
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

    address public implementation;
    address public rakeManager;
    address public treasury;
    address public verifier;
    address public defaultCollateral;
    address public guardian;
    bool public allowlistPaused;
    bool public globalCommitPaused;
    bool public globalClaimPaused;

    address[] private _markets;
    mapping(address => bool) public isMarket;
    mapping(address => bool) public isCollateralAllowed;

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
            implementation_ == address(0) || rakeManager_ == address(0) || treasury_ == address(0)
                || verifier_ == address(0)
        ) {
            revert ZeroAddress();
        }
        implementation = implementation_;
        rakeManager = rakeManager_;
        treasury = treasury_;
        verifier = verifier_;
        defaultCollateral = collateral_;
        if (collateral_ != address(0)) {
            isCollateralAllowed[collateral_] = true;
        }
        isCollateralAllowed[address(0)] = true;
        guardian = msg.sender;
        emit GuardianUpdated(msg.sender);
    }

    error ZeroAddress();
    error InvalidDeadlines();
    error CollateralNotAllowed(address collateral);
    error CannotDisableDefaultCollateral();
    error AllowlistPaused();
    error NotGuardianOrOwner();
    error UnknownMarket();

    modifier onlyGuardianOrOwner() {
        _onlyGuardianOrOwner();
        _;
    }

    /// @notice Updates the implementation contract used for clones.
    function setImplementation(address implementation_) external onlyOwner {
        if (implementation_ == address(0)) revert ZeroAddress();
        implementation = implementation_;
    }

    /// @notice Updates the rake manager contract reference.
    function setRakeManager(address rakeManager_) external onlyOwner {
        if (rakeManager_ == address(0)) revert ZeroAddress();
        rakeManager = rakeManager_;
    }

    /// @notice Updates the treasury address for future markets.
    function setTreasury(address treasury_) external onlyOwner {
        if (treasury_ == address(0)) revert ZeroAddress();
        treasury = treasury_;
    }

    /// @notice Updates the verifier contract reference.
    function setVerifier(address verifier_) external onlyOwner {
        if (verifier_ == address(0)) revert ZeroAddress();
        verifier = verifier_;
    }

    /// @notice Updates the default collateral token used for new markets when none specified.
    function setDefaultCollateral(address collateral_) external onlyOwner {
        if (allowlistPaused) revert AllowlistPaused();
        if (!isCollateralAllowed[collateral_]) revert CollateralNotAllowed(collateral_);
        defaultCollateral = collateral_;
        emit DefaultCollateralUpdated(collateral_);
    }

    /// @notice Adds or removes a collateral token from the allowed set.
    function setCollateralStatus(address collateral, bool allowed) external onlyOwner {
        if (allowlistPaused) revert AllowlistPaused();
        if (!allowed && collateral == defaultCollateral) revert CannotDisableDefaultCollateral();
        isCollateralAllowed[collateral] = allowed;
        emit CollateralStatusUpdated(collateral, allowed);
    }

    /// @notice Updates the guardian address.
    function setGuardian(address newGuardian) external onlyOwner {
        if (newGuardian == address(0)) revert ZeroAddress();
        guardian = newGuardian;
        emit GuardianUpdated(newGuardian);
    }

    /// @notice Toggles the allowlist pause state.
    function setAllowlistPaused(bool paused) external onlyGuardianOrOwner {
        allowlistPaused = paused;
        emit AllowlistPauseSet(paused, msg.sender);
    }

    /// @notice Sets the global commit pause impacting all markets.
    function setGlobalCommitPaused(bool paused) external onlyGuardianOrOwner {
        globalCommitPaused = paused;
        emit GlobalCommitPauseSet(paused, msg.sender);
    }

    /// @notice Sets the global claim pause impacting all markets.
    function setGlobalClaimPaused(bool paused) external onlyGuardianOrOwner {
        globalClaimPaused = paused;
        emit GlobalClaimPauseSet(paused, msg.sender);
    }

    /// @notice Pauses or unpauses a specific market's local controls.
    function setMarketPauses(address market, bool commitPaused, bool claimPaused) external onlyGuardianOrOwner {
        if (!isMarket[market]) revert UnknownMarket();
        RevealMarket(market).setCommitPaused(commitPaused);
        RevealMarket(market).setClaimPaused(claimPaused);
        emit MarketPaused(market, commitPaused, claimPaused, msg.sender);
    }

    /// @notice Updates a market's guardian.
    function setMarketGuardian(address market, address newGuardian) external onlyGuardianOrOwner {
        if (!isMarket[market]) revert UnknownMarket();
        RevealMarket(market).setGuardian(newGuardian);
        emit MarketGuardianUpdated(market, newGuardian);
    }

    /// @notice Updates a market's metadata URI.
    function setMarketMetadata(address market, string calldata metadataURI_) external onlyGuardianOrOwner {
        if (!isMarket[market]) revert UnknownMarket();
        RevealMarket(market).updateMetadataURI(metadataURI_);
        emit MarketMetadataUpdated(market, metadataURI_);
    }

    /// @notice Deploys a new RevealMarket clone.
    /// @param eventId Human-readable event identifier.
    /// @param commitDeadline Timestamp when commits close.
    /// @param revealDeadline Timestamp when reveal window closes.
    /// @param oracle Oracle account authorized to post results.
    /// @param collateral Collateral token address (address(0) to use factory default).
    /// @return market Newly created market address.
    function createMarket(
        string calldata eventId,
        uint256 commitDeadline,
        uint256 revealDeadline,
        address oracle,
        address collateral,
        string calldata metadataURI
    ) external onlyOwner returns (address market) {
        if (oracle == address(0)) revert ZeroAddress();
        if (commitDeadline <= block.timestamp || revealDeadline <= commitDeadline) revert InvalidDeadlines();

        market = implementation.clone();
        address marketCollateral = collateral == address(0) ? defaultCollateral : collateral;
        if (!isCollateralAllowed[marketCollateral]) revert CollateralNotAllowed(marketCollateral);
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
            metadataURI
        );

        _markets.push(market);
        isMarket[market] = true;

        emit MarketCreated(market, eventId, commitDeadline, revealDeadline, marketCollateral, metadataURI);
    }

    /// @notice Returns the list of deployed markets.
    function getMarkets() external view returns (address[] memory) {
        return _markets;
    }

    function _onlyGuardianOrOwner() internal view {
        if (msg.sender != owner() && msg.sender != guardian) revert NotGuardianOrOwner();
    }
}
