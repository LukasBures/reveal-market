// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {IRevealMarket} from "./IRevealMarket.sol";

interface IRelayerEscrow {
    function approveCommitAuthorization(address market, IRevealMarket.CommitAuth calldata auth) external;

    function revokeCommitAuthorization(address market, IRevealMarket.CommitAuth calldata auth) external;

    function commitAuthorizationHash(address market, IRevealMarket.CommitAuth calldata auth)
        external
        view
        returns (bytes32);

    function creditFromMarket(address user, uint256 amount) external;

    function creditMigrated(address user, uint256 amount) external;

    function registerMarket(address market) external;

    function unregisterMarket(address market) external;

    function setCommitsPaused(bool paused) external;

    function commitsPaused() external view returns (bool);

    function marketFactory() external view returns (address);

    function owner() external view returns (address);

    function COLLATERAL_TOKEN() external view returns (address);

    function withdrawTo(address user, address recipient, uint256 amount) external;

    function excessCollateral() external view returns (uint256);
}
