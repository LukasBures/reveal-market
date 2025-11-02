// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Minimal interface exposing factory pause status for markets.
interface IMarketFactoryStatus {
    function globalCommitPaused() external view returns (bool);
    function globalClaimPaused() external view returns (bool);
}
