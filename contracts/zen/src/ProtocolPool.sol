// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";

/// @notice Protocol-owned bankroll that caps per-market liability exposure and collects rake/surplus.
///         External LPs can deposit collateral and bear losses from market draws. LP withdrawal is
///         capped at principal (1:1); market surplus accrues to the protocol, not to LPs.
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

    // ── LP vault state ──────────────────────────────────────────────────
    uint256 public constant LOCK_DURATION = 60 days;
    uint256 public totalShares;

    struct DepositRecord {
        uint256 shares;
        uint256 unlockTime;
    }

    mapping(address => DepositRecord[]) internal _deposits;
    mapping(address => uint256) public lpShareBalance;

    // ── Events ──────────────────────────────────────────────────────────
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
    event LpDeposited(address indexed lp, uint256 assets, uint256 shares, uint256 unlockTime);
    event LpWithdrawn(address indexed lp, uint256 assets, uint256 shares);

    // ── Errors ──────────────────────────────────────────────────────────
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
    error InvalidAmount();
    error InsufficientUnlockedShares();
    error InsufficientIdleLiquidity();
    error FactoryLocked();
    error SlippageExceeded();

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

    /// @notice Sets the factory authorized to register and update markets. Once set, cannot be changed.
    function setMarketFactory(address factory) external onlyOwner {
        if (factory == address(0)) revert InvalidFactory();
        if (marketFactory != address(0) && marketFactory != factory) revert FactoryLocked();
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
        if (newCap < consumedLiability[market] + reservedLiability[market]) revert CapExceeded();
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
        if (consumedLiability[market] + reservedLiability[market] + amount > liabilityCap[market]) {
            revert CapExceeded();
        }
        uint256 balance = COLLATERAL_TOKEN.balanceOf(address(this));
        if (balance < reservedTotal || amount > balance - reservedTotal) revert InsufficientPool();
        if (capacityEnabled) {
            if (amount > capacity) revert CapacityExceeded();
            capacity -= amount;
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
        uint256 balance = COLLATERAL_TOKEN.balanceOf(address(this));
        if (balance < reservedTotal) revert InsufficientPool();
        uint256 reserved = reservedLiability[market];
        if (reserved == 0 && (drawsPaused || marketDrawPaused[market])) revert DrawsPaused();
        uint256 newConsumed = consumedLiability[market] + amount;
        if (newConsumed > liabilityCap[market]) revert CapExceeded();
        if (reserved != 0) {
            if (amount > reserved) revert ReservationExceeded();
            reservedLiability[market] = reserved - amount;
            reservedTotal -= amount;
        } else {
            if (amount > balance - reservedTotal) revert InsufficientPool();
            if (capacityEnabled) {
                if (amount > capacity) revert CapacityExceeded();
                capacity -= amount;
            }
        }
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
    ///         Withdrawals are capped at protocol surplus — LP principal (totalShares) and
    ///         reserved liquidity are both protected.
    function withdraw(address payable to, uint256 amount) external onlyOwner nonReentrant {
        if (to == address(0)) revert InvalidAddress();
        uint256 balance = COLLATERAL_TOKEN.balanceOf(address(this));
        if (amount > balance) revert InsufficientPool();
        uint256 floor = reservedTotal > totalShares ? reservedTotal : totalShares;
        if (balance - amount < floor) revert InsufficientPool();
        _safeTransferExactOut(to, amount);
        emit Withdrawn(to, amount);
    }

    /// @notice Owner can force-release an orphaned reservation for a market that will never
    ///         call releaseLiabilityReservation (e.g., bricked market, stuck settlement).
    function forceReleaseLiability(address market) external onlyOwner {
        uint256 reserved = reservedLiability[market];
        if (reserved == 0) revert InvalidAmount();
        reservedLiability[market] = 0;
        reservedTotal -= reserved;
        emit LiabilityReservationReleased(market, reserved);
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

    // ── LP deposit ──────────────────────────────────────────────────────

    /// @notice Deposit collateral and receive LP shares (1:1). Shares are locked for LOCK_DURATION.
    ///         LPs bear losses from market draws but cannot profit beyond their principal.
    function deposit(uint256 amount) external nonReentrant {
        if (amount == 0) revert InvalidAmount();

        // Transfer tokens in (fee-on-transfer check).
        uint256 balBefore = COLLATERAL_TOKEN.balanceOf(address(this));
        COLLATERAL_TOKEN.safeTransferFrom(msg.sender, address(this), amount);
        uint256 received = COLLATERAL_TOKEN.balanceOf(address(this)) - balBefore;
        if (received != amount) revert FeeOnTransferNotSupported();

        // Shares are always 1:1 with deposited assets.
        uint256 shares = amount;
        totalShares += shares;
        lpShareBalance[msg.sender] += shares;
        uint256 unlockTime = block.timestamp + LOCK_DURATION;
        _deposits[msg.sender].push(DepositRecord({shares: shares, unlockTime: unlockTime}));

        emit FundsReceived(msg.sender, amount);
        emit LpDeposited(msg.sender, amount, shares, unlockTime);
    }

    // ── LP withdrawal ───────────────────────────────────────────────────

    /// @notice Withdraw LP shares that have passed their lock period, subject to idle liquidity.
    /// @param sharesToRedeem Number of shares to burn.
    /// @param minAssets Minimum acceptable asset output (slippage guard). Pass 0 to skip.
    function lpWithdraw(uint256 sharesToRedeem, uint256 minAssets) external nonReentrant {
        if (sharesToRedeem == 0) revert InvalidAmount();
        if (sharesToRedeem > lpShareBalance[msg.sender]) revert InsufficientUnlockedShares();

        uint256 assets = convertToAssets(sharesToRedeem);
        if (assets == 0) revert InvalidAmount();
        if (assets < minAssets) revert SlippageExceeded();

        uint256 balance = COLLATERAL_TOKEN.balanceOf(address(this));
        if (balance <= reservedTotal) revert InsufficientIdleLiquidity();
        uint256 idle = balance - reservedTotal;
        if (assets > idle) revert InsufficientIdleLiquidity();

        _burnUnlockedShares(msg.sender, sharesToRedeem);

        totalShares -= sharesToRedeem;
        lpShareBalance[msg.sender] -= sharesToRedeem;

        _safeTransferExactOut(msg.sender, assets);
        emit LpWithdrawn(msg.sender, assets, sharesToRedeem);
        _compactDeposits(msg.sender);
    }

    // ── View functions ──────────────────────────────────────────────────

    /// @notice Total assets held by the pool (includes reserved funds, excludes consumed).
    function totalAssets() public view returns (uint256) {
        return COLLATERAL_TOKEN.balanceOf(address(this));
    }

    /// @notice Idle liquidity available for LP withdrawals and new market reservations.
    function idleLiquidity() external view returns (uint256) {
        uint256 balance = COLLATERAL_TOKEN.balanceOf(address(this));
        if (balance <= reservedTotal) return 0;
        return balance - reservedTotal;
    }

    /// @notice Convert an asset amount to shares. Always 1:1 (LP shares track principal).
    function convertToShares(uint256 assets) external pure returns (uint256) {
        return assets;
    }

    /// @notice Convert shares to their current redeemable value (capped at 1:1, no profit).
    function convertToAssets(uint256 shares) public view returns (uint256) {
        return _lpShareValue(shares);
    }

    /// @notice Surplus held by the pool above LP principal — withdrawable only by the owner.
    function protocolSurplus() external view returns (uint256) {
        uint256 balance = totalAssets();
        return balance > totalShares ? balance - totalShares : 0;
    }

    /// @notice Number of deposit records for an LP.
    function depositCount(address lp) external view returns (uint256) {
        return _deposits[lp].length;
    }

    /// @notice Read a specific deposit record.
    function depositAt(address lp, uint256 index) external view returns (uint256 shares, uint256 unlockTime) {
        DepositRecord storage d = _deposits[lp][index];
        return (d.shares, d.unlockTime);
    }

    /// @notice Total shares past their lock period for an LP.
    function unlockedShares(address lp) external view returns (uint256) {
        return _unlockedSharesOf(lp);
    }

    /// @notice Maximum shares an LP can redeem right now (capped by lock, idle liquidity, and principal).
    function maxRedeemable(address lp) external view returns (uint256) {
        uint256 unlocked = _unlockedSharesOf(lp);
        if (unlocked == 0 || totalShares == 0) return 0;
        uint256 balance = COLLATERAL_TOKEN.balanceOf(address(this));
        if (balance <= reservedTotal) return 0;
        uint256 idle = balance - reservedTotal;
        uint256 unlockedValue = _lpShareValue(unlocked);
        if (unlockedValue <= idle) return unlocked;
        // Idle can't cover all unlocked shares — cap by what idle can actually pay out.
        // Since value is capped at 1:1, inverse is: idle ZEN buys at most `idle` shares when pool is healthy,
        // or `idle * totalShares / totalAssets` shares when pool is underwater.
        if (balance >= totalShares) return idle; // healthy: 1 share = 1 ZEN
        return Math.mulDiv(idle, totalShares, balance); // underwater: shares are cheaper
    }

    // ── Internal helpers ────────────────────────────────────────────────

    /// @dev LP share value capped at 1:1 (principal). Losses reduce value below 1; surplus does not increase above 1.
    function _lpShareValue(uint256 shares) internal view returns (uint256) {
        if (totalShares == 0) return 0;
        uint256 proportional = Math.mulDiv(shares, totalAssets(), totalShares);
        return proportional < shares ? proportional : shares;
    }

    function _unlockedSharesOf(address lp) internal view returns (uint256 unlocked) {
        DepositRecord[] storage records = _deposits[lp];
        uint256 len = records.length;
        for (uint256 i; i < len;) {
            if (records[i].unlockTime <= block.timestamp && records[i].shares > 0) {
                unlocked += records[i].shares;
            }
            unchecked {
                ++i;
            }
        }
    }

    /// @notice Compact the caller's deposit records by removing zero-share entries.
    function compactDeposits() external {
        _compactDeposits(msg.sender);
    }

    /// @notice Compact deposit records for any LP (permissionless gas refund).
    function compactDepositsFor(address lp) external {
        _compactDeposits(lp);
    }

    function _compactDeposits(address lp) internal {
        DepositRecord[] storage records = _deposits[lp];
        uint256 len = records.length;
        if (len == 0) return;
        uint256 write = 0;
        for (uint256 read = 0; read < len;) {
            if (records[read].shares > 0) {
                if (write != read) records[write] = records[read];
                unchecked {
                    ++write;
                }
            }
            unchecked {
                ++read;
            }
        }
        uint256 toRemove = len - write;
        for (uint256 i = 0; i < toRemove;) {
            records.pop();
            unchecked {
                ++i;
            }
        }
    }

    /// @dev FIFO burn loop — consumes shares from the oldest unlocked deposits first.
    function _burnUnlockedShares(address lp, uint256 sharesToBurn) internal {
        DepositRecord[] storage records = _deposits[lp];
        uint256 len = records.length;
        uint256 remaining = sharesToBurn;
        for (uint256 i; i < len && remaining > 0;) {
            if (records[i].unlockTime > block.timestamp || records[i].shares == 0) {
                unchecked {
                    ++i;
                }
                continue;
            }
            if (records[i].shares <= remaining) {
                remaining -= records[i].shares;
                records[i].shares = 0;
            } else {
                records[i].shares -= remaining;
                remaining = 0;
            }
            unchecked {
                ++i;
            }
        }
        if (remaining > 0) revert InsufficientUnlockedShares();
    }

    /// @dev Fee-on-transfer safe outbound transfer. Reverts if exact amount is not debited/received.
    function _safeTransferExactOut(address to, uint256 amount) internal {
        uint256 senderBalBefore = COLLATERAL_TOKEN.balanceOf(address(this));
        uint256 recipientBalBefore = COLLATERAL_TOKEN.balanceOf(to);
        COLLATERAL_TOKEN.safeTransfer(to, amount);
        uint256 senderBalAfter = COLLATERAL_TOKEN.balanceOf(address(this));
        if (senderBalAfter > senderBalBefore) revert FeeOnTransferNotSupported();
        if (senderBalBefore - senderBalAfter != amount) revert FeeOnTransferNotSupported();
        uint256 recipientBalAfter = COLLATERAL_TOKEN.balanceOf(to);
        if (recipientBalAfter < recipientBalBefore) revert FeeOnTransferNotSupported();
        if (recipientBalAfter - recipientBalBefore < amount) revert FeeOnTransferNotSupported();
    }
}
