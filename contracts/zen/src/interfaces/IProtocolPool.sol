// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IProtocolPool {
    function registerMarket(address market, uint256 liabilityCap) external;

    function updateLiabilityCap(address market, uint256 newCap) external;

    function draw(address market, uint256 amount) external;
}
