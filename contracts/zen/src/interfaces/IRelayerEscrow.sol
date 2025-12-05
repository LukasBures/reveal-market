// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IRelayerEscrow {
    function creditFromMarket(address user, uint256 amount) external;
}
