// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Interface for the fee management contract.
interface IRakeManager {
    /// @notice Withdraws protocol rake and returns the net amount to distribute.
    /// @param token Collateral token used by the market (address(0) for native).
    /// @param amount Gross pool amount before rake.
    /// @return netAmount Net pool amount after rake deduction.
    function takeRake(address token, uint256 amount) external returns (uint256 netAmount);
}
