// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Minimal interface exposing factory pause status for markets. Boundaries ensure RevealMarket clones can query pauses without full factory ABI.
interface IMarketFactoryStatus {
    function globalCommitPaused() external view returns (bool);
    function globalClaimPaused() external view returns (bool);
}
