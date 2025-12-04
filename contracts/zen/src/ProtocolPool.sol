// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @notice Protocol-owned bankroll that caps per-market liability exposure and collects rake/surplus.
contract ProtocolPool is Ownable, ReentrancyGuard {
    address public marketFactory;

    mapping(address => bool) public allowedMarket;
    mapping(address => uint256) public liabilityCap;
    mapping(address => uint256) public consumedLiability;

    event MarketRegistered(address indexed market, uint256 cap);
    event CapUpdated(address indexed market, uint256 oldCap, uint256 newCap);
    event LiabilityDrawn(address indexed market, uint256 amount, uint256 totalDrawn);
    event FundsReceived(address indexed from, uint256 amount);
    event Withdrawn(address indexed to, uint256 amount);
    event MarketFactoryUpdated(address indexed factory);
    event CapacityUpdated(uint256 capacity);

    error Unauthorized();
    error InvalidFactory();
    error CapExceeded();
    error InsufficientPool();
    error CapacityExceeded();

    uint256 public capacity; // optional global risk budget across markets

    constructor(address owner_) Ownable(owner_) {}

    modifier onlyFactory() {
        _onlyFactory();
        _;
    }

    function _onlyFactory() internal view {
        if (msg.sender != marketFactory) revert Unauthorized();
    }

    /// @notice Sets the factory authorized to register and update markets.
    function setMarketFactory(address factory) external onlyOwner {
        if (factory == address(0)) revert InvalidFactory();
        marketFactory = factory;
        emit MarketFactoryUpdated(factory);
    }

    /// @notice Registers a new market with its liability cap.
    function registerMarket(address market, uint256 cap) external onlyFactory {
        allowedMarket[market] = true;
        liabilityCap[market] = cap;
        consumedLiability[market] = 0;
        emit MarketRegistered(market, cap);
    }

    /// @notice Factory hook to update the liability cap for an existing market.
    function updateLiabilityCap(address market, uint256 newCap) external onlyFactory {
        uint256 old = liabilityCap[market];
        liabilityCap[market] = newCap;
        emit CapUpdated(market, old, newCap);
    }

    /// @notice Called by markets to draw protocol coverage up to their configured cap.
    function draw(address market, uint256 amount) external nonReentrant {
        if (!allowedMarket[msg.sender] || msg.sender != market) revert Unauthorized();
        uint256 newConsumed = consumedLiability[market] + amount;
        if (newConsumed > liabilityCap[market]) revert CapExceeded();
        if (capacity != 0 && amount > capacity) revert CapacityExceeded();
        if (amount > address(this).balance) revert InsufficientPool();

        consumedLiability[market] = newConsumed;
        if (capacity != 0) {
            capacity -= amount;
        }
        (bool sent,) = market.call{value: amount}("");
        require(sent, "transfer failed");
        emit LiabilityDrawn(market, amount, newConsumed);
    }

    /// @notice Owner can withdraw idle funds (e.g., to re-seed the pool elsewhere).
    function withdraw(address payable to, uint256 amount) external onlyOwner nonReentrant {
        if (amount > address(this).balance) revert InsufficientPool();
        (bool sent,) = to.call{value: amount}("");
        require(sent, "transfer failed");
        emit Withdrawn(to, amount);
    }

    /// @notice Sets a global risk budget; zero disables capacity tracking.
    function setCapacity(uint256 newCapacity) external onlyOwner {
        capacity = newCapacity;
        emit CapacityUpdated(newCapacity);
    }

    receive() external payable {
        emit FundsReceived(msg.sender, msg.value);
    }
}
