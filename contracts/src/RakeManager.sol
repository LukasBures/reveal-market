// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol"; // Basic ownership helpers.
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol"; // Two-step ownership pattern.

import {IRakeManager} from "./interfaces/IRakeManager.sol";

/**
 * @title RakeManager – protocol-fee policy registry
 *
 * Every market defers to this contract to determine how much rake is taken from the gross pool and where it flows.
 * The manager enforces a global cap (2%) and exposes a tiny API so other contracts can:
 *   - read the maximum allowable rake (`maxRakeBps`),
 *   - deduct fees from a contribution via `takeRake`,
 *   - rotate the treasury/rakeBps through owner-only setters.
 *
 * Keeping fee logic isolated instead of embedding it inside RevealMarket gives us:
 *   • a single upgrade surface for treasury changes,
 *   • simpler auditing (one contract drives all rake math),
 *   • compatibility with new market types without redeploying core logic.
 */

/// @title RakeManager
/// @notice Handles protocol rake distribution to the treasury.
contract RakeManager is Ownable2Step, IRakeManager {
    event RakeTaken(address indexed token, uint256 totalAmount, uint256 rakeAmount, address treasury);

    uint256 public constant MAX_RAKE_BPS = 200; // Hard cap (2%) for rake settings.
    uint256 private constant BPS_DENOMINATOR = 10_000; // Basis points denominator helper.

    address payable public treasury; // Treasury receiving rake transfers.
    uint256 public rakeBps; // Current rake configuration.

    constructor(address initialOwner, address payable treasury_, uint256 rakeBps_) Ownable(initialOwner) {
        if (treasury_ == address(0)) revert InvalidTreasury();
        if (rakeBps_ > MAX_RAKE_BPS) revert InvalidRakeBps();
        treasury = treasury_; // Persist treasury address.
        rakeBps = rakeBps_; // Persist initial rake rate.
    }

    error InvalidTreasury();
    error InvalidRakeBps();

    /// @notice Updates the rake rate in basis points.
    /// @param newRate New rake rate (max 200 bps / 2%).
    function setRakeBps(uint256 newRate) external onlyOwner {
        if (newRate > MAX_RAKE_BPS) revert InvalidRakeBps();
        rakeBps = newRate; // Store the validated rate.
    }

    /// @notice Updates the treasury address receiving rake.
    /// @param newTreasury Treasury address.
    function setTreasury(address payable newTreasury) external onlyOwner {
        if (newTreasury == address(0)) revert InvalidTreasury();
        treasury = newTreasury; // Persist the updated treasury destination.
    }

    /// @inheritdoc IRakeManager
    function maxRakeBps() external pure override returns (uint256) {
        return MAX_RAKE_BPS;
    }

    /// @notice Deducts protocol rake from a contribution amount.
    /// @param token Collateral token used for this calculation (address(0) for native ETH).
    /// @param amount Gross pool amount pre-rake.
    /// @return netAmount Net amount remaining after rake deduction.
    function takeRake(address token, uint256 amount, uint256 overrideBps)
        external
        override
        returns (uint256 netAmount)
    {
        uint256 appliedBps = overrideBps == 0 ? rakeBps : overrideBps; // Choose override or default rate.
        if (appliedBps > MAX_RAKE_BPS) revert InvalidRakeBps(); // Guard against overshooting cap.
        uint256 rakeAmount = (amount * appliedBps) / BPS_DENOMINATOR; // Compute rake share.
        emit RakeTaken(token, amount, rakeAmount, treasury); // Emit for auditability.
        return amount - rakeAmount; // Return net pool amount.
    }
}
