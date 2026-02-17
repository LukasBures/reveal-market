// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

interface IRelayerEscrow {
    function creditFromMarket(address user, uint256 amount) external;
}
