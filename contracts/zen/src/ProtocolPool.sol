// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @notice Protocol-owned bankroll that caps per-market liability exposure and collects rake/surplus.
contract ProtocolPool is Ownable2Step, ReentrancyGuard {
    using SafeERC20 for IERC20;

    IERC20 public immutable COLLATERAL_TOKEN;
    address public marketFactory;

    mapping(address => bool) public allowedMarket;
    mapping(address => uint256) public liabilityCap;
    mapping(address => uint256) public consumedLiability;
    mapping(address => uint256) public reservedLiability;
    mapping(address => bool) public marketDrawPaused;
    uint256 public reservedTotal;

    event MarketRegistered(address indexed market, uint256 cap);
    event CapUpdated(address indexed market, uint256 oldCap, uint256 newCap);
    event LiabilityDrawn(address indexed market, uint256 amount, uint256 totalDrawn);
    event LiabilityReserved(address indexed market, uint256 amount);
    event LiabilityReservationReleased(address indexed market, uint256 amount);
    event FundsReceived(address indexed from, uint256 amount);
    event Withdrawn(address indexed to, uint256 amount);
    event MarketFactoryUpdated(address indexed factory);
    event CapacityUpdated(uint256 capacity);
    event DrawsPausedSet(bool paused);
    event MarketDrawPausedSet(address indexed market, bool paused);

    error Unauthorized();
    error InvalidFactory();
    error CapExceeded();
    error InsufficientPool();
    error CapacityExceeded();
    error DrawsPaused();
    error ReservationExceeded();
    error ActiveReservations();
    error InvalidAddress();
    error FeeOnTransferNotSupported();

    uint256 public capacity; // optional global risk budget across markets
    uint256 public capacityLimit;
    bool public capacityEnabled;
    bool public drawsPaused;

    constructor(address owner_, IERC20 collateralToken_) Ownable(owner_) {
        COLLATERAL_TOKEN = collateralToken_;
    }

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
        reservedLiability[market] = 0;
        marketDrawPaused[market] = false;
        emit MarketRegistered(market, cap);
    }

    /// @notice Factory hook to update the liability cap for an existing market.
    function updateLiabilityCap(address market, uint256 newCap) external onlyFactory {
        uint256 old = liabilityCap[market];
        liabilityCap[market] = newCap;
        emit CapUpdated(market, old, newCap);
    }

    /// @notice Called by a market during lock to reserve capacity for a future settlement draw.
    function reserveLiability(address market, uint256 amount) external {
        if (!allowedMarket[msg.sender] || msg.sender != market) revert Unauthorized();
        if (amount == 0) {
            return;
        }
        if (capacityEnabled) {
            if (amount > capacity) revert CapacityExceeded();
            capacity -= amount;
        } else {
            uint256 balance = COLLATERAL_TOKEN.balanceOf(address(this));
            if (balance < reservedTotal || amount > balance - reservedTotal) revert InsufficientPool();
        }
        reservedLiability[market] += amount;
        reservedTotal += amount;
        emit LiabilityReserved(market, amount);
    }

    /// @notice Releases remaining reserved capacity once settlement finalizes or refunds are enabled.
    function releaseLiabilityReservation(address market) external {
        if (!allowedMarket[msg.sender] || msg.sender != market) revert Unauthorized();
        uint256 reserved = reservedLiability[market];
        if (reserved == 0) {
            return;
        }
        reservedLiability[market] = 0;
        reservedTotal -= reserved;
        if (capacityEnabled) {
            capacity += reserved;
            if (capacity > capacityLimit) {
                capacity = capacityLimit;
            }
        }
        emit LiabilityReservationReleased(market, reserved);
    }

    /// @notice Called by markets to draw protocol coverage up to their configured cap.
    function draw(address market, uint256 amount) external nonReentrant {
        if (!allowedMarket[msg.sender] || msg.sender != market) revert Unauthorized();
        uint256 reserved = reservedLiability[market];
        if (reserved == 0 && (drawsPaused || marketDrawPaused[market])) revert DrawsPaused();
        uint256 newConsumed = consumedLiability[market] + amount;
        if (newConsumed > liabilityCap[market]) revert CapExceeded();
        if (reserved != 0) {
            if (amount > reserved) revert ReservationExceeded();
            reservedLiability[market] = reserved - amount;
            reservedTotal -= amount;
        } else if (capacityEnabled) {
            if (amount > capacity) revert CapacityExceeded();
            capacity -= amount;
        }
        uint256 balance = COLLATERAL_TOKEN.balanceOf(address(this));
        if (amount > balance) revert InsufficientPool();

        uint256 marketBalanceBefore = COLLATERAL_TOKEN.balanceOf(market);
        consumedLiability[market] = newConsumed;
        COLLATERAL_TOKEN.safeTransfer(market, amount);
        uint256 balanceAfter = COLLATERAL_TOKEN.balanceOf(address(this));
        if (balanceAfter > balance) revert InsufficientPool();
        uint256 debited = balance - balanceAfter;
        if (debited != amount) revert InsufficientPool();
        uint256 marketBalanceAfter = COLLATERAL_TOKEN.balanceOf(market);
        if (marketBalanceAfter < marketBalanceBefore) revert InsufficientPool();
        uint256 marketReceived = marketBalanceAfter - marketBalanceBefore;
        if (marketReceived < amount) revert InsufficientPool();
        emit LiabilityDrawn(market, amount, newConsumed);
    }

    /// @notice Owner can withdraw idle funds (e.g., to re-seed the pool elsewhere).
    function withdraw(address payable to, uint256 amount) external onlyOwner nonReentrant {
        if (to == address(0)) revert InvalidAddress();
        uint256 balance = COLLATERAL_TOKEN.balanceOf(address(this));
        if (amount > balance) revert InsufficientPool();
        if (balance - amount < reservedTotal) revert InsufficientPool();
        uint256 senderBalanceBefore = balance;
        uint256 recipientBalanceBefore = COLLATERAL_TOKEN.balanceOf(to);
        COLLATERAL_TOKEN.safeTransfer(to, amount);
        uint256 senderBalanceAfter = COLLATERAL_TOKEN.balanceOf(address(this));
        if (senderBalanceAfter > senderBalanceBefore) revert FeeOnTransferNotSupported();
        uint256 senderDebited = senderBalanceBefore - senderBalanceAfter;
        if (senderDebited != amount) revert FeeOnTransferNotSupported();
        uint256 recipientBalanceAfter = COLLATERAL_TOKEN.balanceOf(to);
        if (recipientBalanceAfter < recipientBalanceBefore) revert FeeOnTransferNotSupported();
        uint256 recipientReceived = recipientBalanceAfter - recipientBalanceBefore;
        if (recipientReceived < amount) revert FeeOnTransferNotSupported();
        emit Withdrawn(to, amount);
    }

    /// @notice Sets a global risk budget; zero disables capacity tracking.
    function setCapacity(uint256 newCapacity) external onlyOwner {
        if (reservedTotal != 0) revert ActiveReservations();
        capacity = newCapacity;
        capacityLimit = newCapacity;
        capacityEnabled = newCapacity != 0;
        emit CapacityUpdated(newCapacity);
    }

    /// @notice Emergency pause for all market draws.
    function setDrawsPaused(bool paused) external onlyOwner {
        drawsPaused = paused;
        emit DrawsPausedSet(paused);
    }

    /// @notice Emergency pause for a single market draw.
    function setMarketDrawPaused(address market, bool paused) external onlyOwner {
        marketDrawPaused[market] = paused;
        emit MarketDrawPausedSet(market, paused);
    }

    function deposit(uint256 amount) external nonReentrant {
        COLLATERAL_TOKEN.safeTransferFrom(msg.sender, address(this), amount);
        emit FundsReceived(msg.sender, amount);
    }
}
