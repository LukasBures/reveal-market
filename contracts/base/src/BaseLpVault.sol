// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20, IERC20Metadata, ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @title BaseLpVault
/// @notice LP vault holding USDC and issuing ERC20 shares; hedger can borrow/repay for external hedging.
contract BaseLpVault is ERC20, Ownable, Pausable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    uint8 public constant ASSET_DECIMALS = 6;
    uint16 public constant BPS_DENOMINATOR = 10_000;

    IERC20 public immutable ASSET;
    address public hedger;
    uint256 public utilizedAssets;
    uint16 public maxUtilizationBps;

    event Deposit(address indexed caller, address indexed owner, uint256 assets, uint256 shares);
    event Withdraw(address indexed caller, address indexed receiver, address indexed owner, uint256 assets, uint256 shares);
    event BorrowForHedge(address indexed hedger, address indexed to, uint256 amount, uint256 utilizedAfter, uint256 utilizationBps);
    event RepayFromHedge(address indexed hedger, address indexed from, uint256 amount, uint256 utilizedAfter, uint256 utilizationBps);
    event HedgerUpdated(address indexed previousHedger, address indexed newHedger);
    event MaxUtilizationBpsUpdated(uint16 previousMaxUtilizationBps, uint16 newMaxUtilizationBps);
    event RecoveredToken(address indexed token, address indexed to, uint256 amount);

    error InvalidAsset(address asset);
    error InvalidAssetDecimals(uint8 expected, uint8 actual);
    error InvalidAmount();
    error ZeroShares();
    error NotHedger(address caller);
    error InvalidHedger(address hedger);
    error InvalidReceiver();
    error InvalidOwner();
    error InsufficientIdleAssets();
    error RepayExceedsUtilized();
    error UtilizationOverflow();
    error TotalAssetsOverflow();
    error UtilizationCapExceeded();
    error InvalidToken();

    constructor(IERC20 asset_, address owner_, address hedger_) ERC20("Base LP Vault", "bLPV") Ownable(owner_) {
        if (address(asset_) == address(0)) {
            revert InvalidAsset(address(0));
        }

        uint8 assetDecimals = IERC20Metadata(address(asset_)).decimals();
        if (assetDecimals != ASSET_DECIMALS) {
            revert InvalidAssetDecimals(ASSET_DECIMALS, assetDecimals);
        }
        if (hedger_ == address(0)) {
            revert InvalidHedger(address(0));
        }

        ASSET = asset_;
        hedger = hedger_;
        maxUtilizationBps = BPS_DENOMINATOR;

        emit HedgerUpdated(address(0), hedger_);
    }

    modifier onlyHedger() {
        _onlyHedger();
        _;
    }

    function decimals() public pure override returns (uint8) {
        return 18;
    }

    function totalAssets() public view returns (uint256) {
        uint256 balance = _assetBalance();
        uint256 total = balance + utilizedAssets;
        if (total < balance) {
            revert TotalAssetsOverflow();
        }
        return total;
    }

    function idleAssets() public view returns (uint256) {
        return _assetBalance();
    }

    function convertToShares(uint256 assets) public view returns (uint256) {
        if (assets == 0) {
            return 0;
        }
        uint256 supply = totalSupply();
        if (supply == 0) {
            return assets;
        }
        return Math.mulDiv(assets, supply, totalAssets());
    }

    function convertToAssets(uint256 shares) public view returns (uint256) {
        if (shares == 0) {
            return 0;
        }
        uint256 supply = totalSupply();
        if (supply == 0) {
            return 0;
        }
        return Math.mulDiv(shares, totalAssets(), supply);
    }

    function deposit(uint256 assets, address receiver)
        external
        nonReentrant
        whenNotPaused
        returns (uint256 shares)
    {
        if (assets == 0) {
            revert InvalidAmount();
        }

        if (receiver == address(0)) {
            revert InvalidReceiver();
        }

        shares = convertToShares(assets);
        if (shares == 0) {
            revert ZeroShares();
        }

        uint256 balanceBefore = _assetBalance();
        ASSET.safeTransferFrom(msg.sender, address(this), assets);

        uint256 received = _assetBalance() - balanceBefore;
        if (received != assets) {
            revert InvalidAmount(); // defensive against fee-on-transfer or deflationary tokens.
        }

        _mint(receiver, shares);

        emit Deposit(msg.sender, receiver, assets, shares);
    }

    function withdraw(uint256 assets, address receiver, address owner_)
        external
        nonReentrant
        whenNotPaused
        returns (uint256 shares)
    {
        if (assets == 0) {
            revert InvalidAmount();
        }
        if (receiver == address(0)) {
            revert InvalidReceiver();
        }
        if (owner_ == address(0)) {
            revert InvalidOwner();
        }
        if (assets > idleAssets()) {
            revert InsufficientIdleAssets();
        }

        shares = convertToShares(assets);
        if (shares == 0) {
            revert ZeroShares();
        }

        if (msg.sender != owner_) {
            _spendAllowance(owner_, msg.sender, shares);
        }

        _burn(owner_, shares);
        ASSET.safeTransfer(receiver, assets);

        emit Withdraw(msg.sender, receiver, owner_, assets, shares);
    }

    function redeem(uint256 shares, address receiver, address owner_)
        external
        nonReentrant
        whenNotPaused
        returns (uint256 assets)
    {
        if (shares == 0) {
            revert InvalidAmount();
        }
        if (receiver == address(0)) {
            revert InvalidReceiver();
        }
        if (owner_ == address(0)) {
            revert InvalidOwner();
        }

        if (msg.sender != owner_) {
            _spendAllowance(owner_, msg.sender, shares);
        }

        assets = convertToAssets(shares);
        if (assets == 0) {
            revert InvalidAmount();
        }
        if (assets > idleAssets()) {
            revert InsufficientIdleAssets();
        }

        _burn(owner_, shares);
        ASSET.safeTransfer(receiver, assets);

        emit Withdraw(msg.sender, receiver, owner_, assets, shares);
    }

    function borrowForHedge(uint256 amount, address to)
        external
        nonReentrant
        whenNotPaused
        onlyHedger
    {
        if (amount == 0) {
            revert InvalidAmount();
        }
        if (amount > idleAssets()) {
            revert InsufficientIdleAssets();
        }
        if (to == address(0)) {
            revert InvalidReceiver();
        }

        uint256 newUtilized = utilizedAssets + amount;
        if (newUtilized < utilizedAssets) {
            revert UtilizationOverflow();
        }
        uint256 utilizationBps = _utilizationBps(newUtilized);
        _enforceUtilizationCap(utilizationBps);
        utilizedAssets = newUtilized;
        ASSET.safeTransfer(to, amount);

        emit BorrowForHedge(msg.sender, to, amount, newUtilized, utilizationBps);
    }

    function repayFromHedge(uint256 amount, address from)
        external
        nonReentrant
        whenNotPaused
        onlyHedger
    {
        if (amount == 0) {
            revert InvalidAmount();
        }
        if (amount > utilizedAssets) {
            revert RepayExceedsUtilized();
        }

        uint256 balanceBefore = _assetBalance();
        ASSET.safeTransferFrom(from, address(this), amount);
        uint256 received = _assetBalance() - balanceBefore;
        if (received != amount) {
            revert InvalidAmount();
        }
        uint256 newUtilized = utilizedAssets - amount;
        uint256 utilizationBps = _utilizationBps(newUtilized);
        utilizedAssets = newUtilized;

        emit RepayFromHedge(msg.sender, from, amount, newUtilized, utilizationBps);
    }

    function setHedger(address newHedger) external onlyOwner {
        if (newHedger == address(0)) {
            revert InvalidHedger(address(0));
        }
        address previous = hedger;
        hedger = newHedger;

        emit HedgerUpdated(previous, newHedger);
    }

    function setMaxUtilizationBps(uint16 newMaxUtilizationBps) external onlyOwner {
        if (newMaxUtilizationBps > BPS_DENOMINATOR) {
            revert InvalidAmount();
        }
        uint16 previous = maxUtilizationBps;
        maxUtilizationBps = newMaxUtilizationBps;

        emit MaxUtilizationBpsUpdated(previous, newMaxUtilizationBps);
    }

    function recoverToken(address token, address to, uint256 amount) external onlyOwner nonReentrant {
        if (token == address(0) || to == address(0)) {
            revert InvalidReceiver();
        }
        if (token == address(ASSET)) {
            revert InvalidToken();
        }
        IERC20(token).safeTransfer(to, amount);
        emit RecoveredToken(token, to, amount);
    }

    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }

    function _assetBalance() internal view returns (uint256) {
        return ASSET.balanceOf(address(this));
    }

    function _onlyHedger() internal view {
        if (msg.sender != hedger) {
            revert NotHedger(msg.sender);
        }
    }

    function _enforceUtilizationCap(uint256 utilizationBps) internal view {
        if (utilizationBps > maxUtilizationBps) {
            revert UtilizationCapExceeded();
        }
    }

    function _utilizationBps(uint256 newUtilized) internal view returns (uint256) {
        uint256 total = totalAssets();
        if (total == 0) {
            return 0;
        }
        return Math.mulDiv(newUtilized, BPS_DENOMINATOR, total);
    }
}
