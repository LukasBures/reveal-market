// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Interface exposing factory risk accounting hooks used by markets.
interface IMarketFactoryRisk {
    function syncAccounting(address market, uint256 escrow, uint256 floatBalance, uint256 maxLiability) external;

    function marketMaxSize() external view returns (uint256);

    function maxMarketLiability() external view returns (uint256);

    function maxGlobalLiability() external view returns (uint256);

    function totalRecordedLiability() external view returns (uint256);

    function marketLiability(address market) external view returns (uint256);

    function marketFloatAllocation(address market) external view returns (uint256);
}
