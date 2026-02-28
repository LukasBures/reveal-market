// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {IERC20, IERC20Metadata, ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @title BaseLpVault
/// @notice LP vault holding USDC and issuing ERC20 shares; hedger can borrow/repay for external hedging.
/// @dev The vault is intentionally simple: ERC20 shares over a 6-decimal USDC asset, proportional mint/burn,
/// hedger-controlled borrow/repay, utilization caps (bps + per-call), pause + reentrancy guards, and explicit
/// rejection of fee-on-transfer assets. All accounting is share-based to prevent dilution.
contract BaseLpVault is ERC20, Ownable, Pausable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    /// @dev USDC on Base uses 6 decimals; enforced at construction.
    uint8 public constant ASSET_DECIMALS = 6;
    /// @dev Basis points denominator for utilization math.
    uint16 public constant BPS_DENOMINATOR = 10_000;

    /// @dev Underlying asset (USDC); immutable so approvals stay predictable.
    IERC20 public immutable ASSET;
    /// @dev Address allowed to borrow/repay on behalf of LPs.
    address public hedger;
    /// @dev Assets currently loaned to the hedger (counts toward totalAssets via utilization).
    uint256 public utilizedAssets;
    /// @dev Max utilization in basis points (default 100%).
    uint16 public maxUtilizationBps;
    /// @dev Hard cap per borrow call to bound instantaneous outflows.
    uint256 public maxBorrowPerCall;

    event Deposit(address indexed caller, address indexed owner, uint256 assets, uint256 shares);
    event Withdraw(
        address indexed caller, address indexed receiver, address indexed owner, uint256 assets, uint256 shares
    );
    event BorrowForHedge(
        address indexed hedger, address indexed to, uint256 amount, uint256 utilizedAfter, uint256 utilizationBps
    );
    event RepayFromHedge(
        address indexed hedger, address indexed from, uint256 amount, uint256 utilizedAfter, uint256 utilizationBps
    );
    event HedgerUpdated(address indexed previousHedger, address indexed newHedger);
    event MaxUtilizationBpsUpdated(uint16 previousMaxUtilizationBps, uint16 newMaxUtilizationBps);
    event MaxBorrowPerCallUpdated(uint256 previousMaxBorrowPerCall, uint256 newMaxBorrowPerCall);
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
    error BorrowAmountExceedsLimit();

    /// @param asset_ USDC token (must be 6 decimals).
    /// @param owner_ Owner of the vault (config + pause authority).
    /// @param hedger_ Borrow/repay authority for hedging.
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
        maxBorrowPerCall = type(uint256).max;

        emit HedgerUpdated(address(0), hedger_);
    }

    modifier onlyHedger() {
        _onlyHedger();
        _;
    }

    function decimals() public pure override returns (uint8) {
        return 18;
    }

    /// @notice Total assets = on-chain balance + outstanding borrows.
    function totalAssets() public view returns (uint256) {
        uint256 balance = _assetBalance();
        uint256 total = balance + utilizedAssets;
        if (total < balance) {
            revert TotalAssetsOverflow();
        }
        return total;
    }

    /// @notice Assets currently held by the vault (excludes utilizedAssets).
    function idleAssets() public view returns (uint256) {
        return _assetBalance();
    }

    /// @notice Convert asset amount to shares at current exchange rate.
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

    /// @notice Convert shares to asset amount at current exchange rate.
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

    /// @dev Ceil-rounded share conversion used by withdraw() to prevent underburning.
    function _convertToSharesCeil(uint256 assets) internal view returns (uint256) {
        if (assets == 0) return 0;
        uint256 supply = totalSupply();
        if (supply == 0) return assets;
        return Math.mulDiv(assets, supply, totalAssets(), Math.Rounding.Ceil);
    }

    /// @notice Deposit USDC and receive vault shares.
    function deposit(uint256 assets, address receiver) external nonReentrant whenNotPaused returns (uint256 shares) {
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

    /// @notice Burn shares to withdraw a specific asset amount (requires idle liquidity).
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

        shares = _convertToSharesCeil(assets);
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

    /// @notice Burn shares to redeem pro-rata assets (requires idle liquidity).
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

    /// @notice Hedger-only borrow of idle assets for external hedging. Enforces per-call and bps caps.
    function borrowForHedge(uint256 amount, address to) external nonReentrant whenNotPaused onlyHedger {
        if (amount == 0) {
            revert InvalidAmount();
        }
        if (amount > maxBorrowPerCall) {
            revert BorrowAmountExceedsLimit();
        }
        if (amount > idleAssets()) {
            revert InsufficientIdleAssets();
        }
        if (to == address(0)) {
            revert InvalidReceiver();
        }

        uint256 balanceBefore = _assetBalance();
        uint256 newUtilized = utilizedAssets + amount;
        if (newUtilized < utilizedAssets) {
            revert UtilizationOverflow();
        }

        uint256 totalBefore = balanceBefore + utilizedAssets;
        uint256 utilizationBps = totalBefore == 0 ? 0 : Math.mulDiv(newUtilized, BPS_DENOMINATOR, totalBefore);
        _enforceUtilizationCap(utilizationBps);

        utilizedAssets = newUtilized;
        ASSET.safeTransfer(to, amount);

        emit BorrowForHedge(msg.sender, to, amount, newUtilized, utilizationBps);
    }

    /// @notice Hedger-only repay of utilized assets back to the vault. Requires exact amount (no fee-on-transfer).
    function repayFromHedge(uint256 amount, address from) external nonReentrant whenNotPaused onlyHedger {
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
        uint256 totalBefore = balanceBefore + utilizedAssets;
        uint256 newUtilized = utilizedAssets - amount;
        uint256 utilizationBps = totalBefore == 0 ? 0 : Math.mulDiv(newUtilized, BPS_DENOMINATOR, totalBefore);
        utilizedAssets = newUtilized;

        emit RepayFromHedge(msg.sender, from, amount, newUtilized, utilizationBps);
    }

    /// @notice Owner sets the hedger address (single-step).
    function setHedger(address newHedger) external onlyOwner {
        if (newHedger == address(0)) {
            revert InvalidHedger(address(0));
        }
        address previous = hedger;
        hedger = newHedger;

        emit HedgerUpdated(previous, newHedger);
    }

    /// @notice Owner sets the utilization cap (bps).
    function setMaxUtilizationBps(uint16 newMaxUtilizationBps) external onlyOwner {
        if (newMaxUtilizationBps > BPS_DENOMINATOR) {
            revert InvalidAmount();
        }
        uint16 previous = maxUtilizationBps;
        maxUtilizationBps = newMaxUtilizationBps;

        emit MaxUtilizationBpsUpdated(previous, newMaxUtilizationBps);
    }

    /// @notice Owner sets the per-call borrow cap.
    function setMaxBorrowPerCall(uint256 newMaxBorrowPerCall) external onlyOwner {
        uint256 previous = maxBorrowPerCall;
        maxBorrowPerCall = newMaxBorrowPerCall;
        emit MaxBorrowPerCallUpdated(previous, newMaxBorrowPerCall);
    }

    /// @notice Owner can rescue non-ASSET tokens accidentally sent to the vault.
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

    receive() external payable {
        revert InvalidAsset(address(0)); // Vault never accepts native ETH.
    }

    fallback() external payable {
        revert InvalidAsset(address(0)); // Reject unexpected calls/ETH.
    }
}
