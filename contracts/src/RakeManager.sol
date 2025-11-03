// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";

import {IRakeManager} from "./interfaces/IRakeManager.sol";

/// @title RakeManager
/// @notice Handles protocol rake distribution to the treasury.
contract RakeManager is Ownable2Step, IRakeManager {
    event RakeTaken(address indexed token, uint256 totalAmount, uint256 rakeAmount, address treasury);

    uint256 public constant MAX_RAKE_BPS = 200;
    uint256 private constant BPS_DENOMINATOR = 10_000;

    address payable public treasury;
    uint256 public rakeBps;

    constructor(address initialOwner, address payable treasury_, uint256 rakeBps_) Ownable(initialOwner) {
        if (treasury_ == address(0)) revert InvalidTreasury();
        if (rakeBps_ > MAX_RAKE_BPS) revert InvalidRakeBps();
        treasury = treasury_;
        rakeBps = rakeBps_;
    }

    error InvalidTreasury();
    error InvalidRakeBps();

    /// @notice Updates the rake rate in basis points.
    /// @param newRate New rake rate (max 200 bps / 2%).
    function setRakeBps(uint256 newRate) external onlyOwner {
        if (newRate > MAX_RAKE_BPS) revert InvalidRakeBps();
        rakeBps = newRate;
    }

    /// @notice Updates the treasury address receiving rake.
    /// @param newTreasury Treasury address.
    function setTreasury(address payable newTreasury) external onlyOwner {
        if (newTreasury == address(0)) revert InvalidTreasury();
        treasury = newTreasury;
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
        uint256 appliedBps = overrideBps == 0 ? rakeBps : overrideBps;
        if (appliedBps > MAX_RAKE_BPS) revert InvalidRakeBps();
        uint256 rakeAmount = (amount * appliedBps) / BPS_DENOMINATOR;
        emit RakeTaken(token, amount, rakeAmount, treasury);
        return amount - rakeAmount;
    }
}
