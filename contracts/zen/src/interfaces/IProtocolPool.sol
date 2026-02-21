// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

interface IProtocolPool {
    function registerMarket(address market, uint256 liabilityCap) external;

    function updateLiabilityCap(address market, uint256 newCap) external;

    function draw(address market, uint256 amount) external;

    function reserveLiability(address market, uint256 amount) external;

    function releaseLiabilityReservation(address market) external;

    function drawsPaused() external view returns (bool);

    function marketDrawPaused(address market) external view returns (bool);
}
