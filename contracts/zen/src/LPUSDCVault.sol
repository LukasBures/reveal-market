// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @title LPUSDCVault – single-asset LP pool for hedger borrowing
/// @notice USDC-only vault where LPs deposit/withdraw, and only the owner can borrow to fund hedges.
contract LPUSDCVault is Ownable2Step {
    using SafeERC20 for IERC20;

    IERC20 public immutable USDC;
    uint256 public totalShares;
    uint256 public totalAssets;
    uint256 public borrowed;
    mapping(address => uint256) public balanceOf;

    event Deposit(address indexed lp, uint256 assets, uint256 shares);
    event Withdraw(address indexed lp, uint256 assets, uint256 shares);
    event Borrow(address indexed borrower, uint256 amount, uint256 utilizationBps);
    event Repay(address indexed repayer, uint256 amount, uint256 utilizationBps);

    error InvalidAmount();
    error ZeroAddress();
    error InsufficientLiquidity();

    constructor(address initialOwner, IERC20 usdc_) Ownable(initialOwner) {
        if (initialOwner == address(0) || address(usdc_) == address(0)) revert ZeroAddress();
        USDC = usdc_;
    }

    /// @notice LPs deposit USDC and receive proportional vault shares.
    function deposit(uint256 assets) external returns (uint256 shares) {
        if (assets == 0) revert InvalidAmount();
        shares = _previewShares(assets);
        balanceOf[msg.sender] += shares;
        totalShares += shares;
        totalAssets += assets;
        USDC.safeTransferFrom(msg.sender, address(this), assets);
        emit Deposit(msg.sender, assets, shares);
    }

    /// @notice LPs redeem shares for underlying USDC.
    function withdraw(uint256 shares) external returns (uint256 assets) {
        if (shares == 0 || shares > balanceOf[msg.sender]) revert InvalidAmount();
        assets = (shares * totalAssets) / totalShares;
        if (assets > _availableLiquidity()) revert InsufficientLiquidity();
        balanceOf[msg.sender] -= shares;
        totalShares -= shares;
        totalAssets -= assets;
        USDC.safeTransfer(msg.sender, assets);
        emit Withdraw(msg.sender, assets, shares);
    }

    /// @notice Only the owner (platform) can borrow USDC to fund hedges.
    function borrow(uint256 amount, address to) external onlyOwner returns (uint256) {
        if (amount == 0 || to == address(0)) revert InvalidAmount();
        if (amount > _availableLiquidity()) revert InsufficientLiquidity();
        borrowed += amount;
        USDC.safeTransfer(to, amount);
        emit Borrow(to, amount, utilization());
        return amount;
    }

    /// @notice Repay borrowed USDC back into the vault.
    function repay(uint256 amount) external returns (uint256 applied) {
        if (amount == 0) revert InvalidAmount();
        USDC.safeTransferFrom(msg.sender, address(this), amount);
        applied = amount > borrowed ? borrowed : amount;
        borrowed -= applied;
        if (amount > applied) {
            // Surplus is treated as hedging profit and credited to LPs.
            totalAssets += (amount - applied);
        }
        emit Repay(msg.sender, applied, utilization());
    }

    /// @notice Current utilization in basis points (10000 = 100%).
    function utilization() public view returns (uint256) {
        if (totalAssets == 0) return 0;
        return (borrowed * 10_000) / totalAssets;
    }

    function _availableLiquidity() internal view returns (uint256) {
        uint256 onHand = USDC.balanceOf(address(this));
        if (borrowed > onHand) return 0;
        return onHand - borrowed;
    }

    function _previewShares(uint256 assets) internal view returns (uint256) {
        if (totalShares == 0 || totalAssets == 0) return assets;
        return (assets * totalShares) / totalAssets;
    }
}
