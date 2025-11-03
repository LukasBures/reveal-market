// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Interface for the fee management contract.
interface IRakeManager {
    function MAX_RAKE_BPS() external view returns (uint256);

    function rakeBps() external view returns (uint256);

    /// @notice Withdraws protocol rake and returns the net amount to distribute.
    /// @param token Collateral token used by the market (address(0) for native).
    /// @param amount Gross pool amount before rake.
    /// @param overrideBps Optional rake override applied by the market (0 means use default).
    /// @return netAmount Net pool amount after rake deduction.
    function takeRake(address token, uint256 amount, uint256 overrideBps) external returns (uint256 netAmount);
}
