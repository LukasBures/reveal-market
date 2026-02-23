// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

import {IRevealMarket} from "./interfaces/IRevealMarket.sol";

/// @notice Trusted relayer escrow that holds all user balances and forwards fixed-size commits to markets.
/// Users deposit/withdraw ERC20 collateral; only the relayer (owner) may initiate commits on their behalf.
contract RelayerEscrow is Ownable2Step, ReentrancyGuard {
    using SafeERC20 for IERC20;
    IERC20 public immutable COLLATERAL_TOKEN;
    mapping(address => uint256) public balances;
    mapping(address => bool) public allowedMarket;
    mapping(address => mapping(bytes32 => bool)) public approvedCommitAuthorizations;
    uint256 public accountedCollateral;

    address public marketFactory;
    bool public commitsPaused;

    event Deposited(address indexed user, uint256 amount);
    event Withdrawn(address indexed user, uint256 amount);
    event MarketRegistered(address indexed market);
    event MarketUnregistered(address indexed market);
    event MarketFactoryUpdated(address indexed factory);
    event CommitsPausedSet(bool paused);
    event CommitForwarded(address indexed market, bytes32 commitment, uint256 debitedFromUser);
    event CommitAuthorizationApproved(
        address indexed user, address indexed market, uint256 indexed nonce, bytes32 authHash
    );
    event CreditReceived(address indexed market, address indexed user, uint256 amount);
    event MigratedCreditReceived(address indexed user, uint256 amount);
    event ExcessCollateralRecovered(address indexed recipient, uint256 amount);
    event BalanceWithdrawnTo(address indexed user, address indexed recipient, uint256 amount);

    /// @notice View helper matching ERC20 style balanceOf for frontends/indexers.
    function balanceOf(address user) external view returns (uint256) {
        return balances[user];
    }

    error UnknownMarket();
    error InvalidFactory();
    error FactoryLocked();
    error InsufficientBalance();
    error FeeOnTransferNotSupported();
    error CommitFailed();
    error InvalidRelayerOwner();
    error UserMismatch();
    error CommitsPaused();
    error NotAuthorized();
    error InsufficientCollateralBacking();
    error InvalidAddress();
    error InvalidMarket();
    error CommitAuthorizationMissing();

    constructor(address owner_, IERC20 collateralToken_) Ownable(owner_) {
        COLLATERAL_TOKEN = collateralToken_;
    }

    /// @notice Sets the factory allowed to register new markets.
    function setMarketFactory(address factory) external onlyOwner {
        if (factory == address(0)) revert InvalidFactory();
        if (marketFactory != address(0) && marketFactory != factory) revert FactoryLocked();
        marketFactory = factory;
        emit MarketFactoryUpdated(factory);
    }

    /// @notice Factory hook to whitelist a freshly deployed market.
    function registerMarket(address market) external {
        if (msg.sender != marketFactory) revert InvalidFactory();
        if (!_isValidMarket(market)) revert InvalidMarket();
        allowedMarket[market] = true;
        emit MarketRegistered(market);
    }

    /// @notice Factory hook to revoke a market from the allowlist.
    function unregisterMarket(address market) external {
        if (msg.sender != marketFactory) revert InvalidFactory();
        allowedMarket[market] = false;
        emit MarketUnregistered(market);
    }

    /// @notice Users deposit ERC20 collateral into their escrow balance (requires prior approval).
    function deposit(uint256 amount) external {
        uint256 beforeBalance = COLLATERAL_TOKEN.balanceOf(address(this));
        COLLATERAL_TOKEN.safeTransferFrom(msg.sender, address(this), amount);
        uint256 received = COLLATERAL_TOKEN.balanceOf(address(this)) - beforeBalance;
        if (received != amount) revert FeeOnTransferNotSupported();
        balances[msg.sender] += received;
        accountedCollateral += received;
        emit Deposited(msg.sender, received);
    }

    /// @notice Owner can deposit on behalf of a user (e.g., when funding via off-chain rails).
    function depositFor(address user, uint256 amount) external onlyOwner {
        if (user == address(0)) revert InvalidAddress();
        uint256 beforeBalance = COLLATERAL_TOKEN.balanceOf(address(this));
        COLLATERAL_TOKEN.safeTransferFrom(msg.sender, address(this), amount);
        uint256 received = COLLATERAL_TOKEN.balanceOf(address(this)) - beforeBalance;
        if (received != amount) revert FeeOnTransferNotSupported();
        balances[user] += received;
        accountedCollateral += received;
        emit Deposited(user, received);
    }

    /// @notice Withdraw caller balance to their wallet.
    function withdraw(uint256 amount) external nonReentrant {
        if (balances[msg.sender] < amount) revert InsufficientBalance();
        balances[msg.sender] -= amount;
        accountedCollateral -= amount;
        _safeTransferExact(msg.sender, amount);
        emit Withdrawn(msg.sender, amount);
    }

    /// @notice Factory migration helper to move a user's balance to another escrow/user wallet.
    function withdrawTo(address user, address recipient, uint256 amount) external nonReentrant {
        if (msg.sender != marketFactory) revert InvalidFactory();
        if (user == address(0) || recipient == address(0)) revert InvalidAddress();
        if (balances[user] < amount) revert InsufficientBalance();
        balances[user] -= amount;
        accountedCollateral -= amount;
        _safeTransferExact(recipient, amount);
        emit BalanceWithdrawnTo(user, recipient, amount);
    }

    /// @notice Relayer-only entry point to forward a fixed ticket to a market using backend authorization.
    function commitOnBehalf(
        address user,
        address market,
        IRevealMarket.CommitAuth calldata auth,
        bytes calldata signature
    ) external nonReentrant onlyOwner {
        if (commitsPaused) revert CommitsPaused();
        if (!allowedMarket[market]) revert UnknownMarket();
        if (auth.user != user || user == address(0)) revert UserMismatch();
        uint256 ticket = IRevealMarket(market).ticketSize();
        if (balances[user] < ticket) revert InsufficientBalance();
        bytes32 authHash = _commitAuthorizationHash(market, auth);
        if (!approvedCommitAuthorizations[user][authHash]) revert CommitAuthorizationMissing();
        approvedCommitAuthorizations[user][authHash] = false;

        uint256 escrowBalanceBefore = COLLATERAL_TOKEN.balanceOf(address(this));
        uint256 marketBalanceBefore = COLLATERAL_TOKEN.balanceOf(market);
        balances[user] -= ticket;
        accountedCollateral -= ticket;
        _safeTransferExact(market, ticket, escrowBalanceBefore, marketBalanceBefore);
        IRevealMarket(market).commitWithAuthorization(auth, signature);

        emit CommitForwarded(market, auth.commitment, ticket);
    }

    /// @notice User-side authorization gate for relayed commits; one approval can be consumed exactly once.
    function approveCommitAuthorization(address market, IRevealMarket.CommitAuth calldata auth) external {
        if (market == address(0)) revert InvalidAddress();
        if (auth.user != msg.sender || auth.user == address(0)) revert UserMismatch();
        bytes32 authHash = _commitAuthorizationHash(market, auth);
        approvedCommitAuthorizations[msg.sender][authHash] = true;
        emit CommitAuthorizationApproved(msg.sender, market, auth.nonce, authHash);
    }

    /// @notice View helper for clients to precompute commit-authorization hashes.
    function commitAuthorizationHash(address market, IRevealMarket.CommitAuth calldata auth)
        external
        view
        returns (bytes32)
    {
        return _commitAuthorizationHash(market, auth);
    }

    /// @notice Emergency pause for relayer commits.
    function setCommitsPaused(bool paused) external {
        if (msg.sender != owner() && msg.sender != marketFactory) revert NotAuthorized();
        commitsPaused = paused;
        emit CommitsPausedSet(paused);
    }

    /// @notice Optional hook for escrow-style payouts when markets do not pay users directly.
    function creditFromMarket(address user, uint256 amount) external {
        if (!allowedMarket[msg.sender]) revert UnknownMarket();
        if (user == address(0)) revert InvalidAddress();
        uint256 beforeBalance = COLLATERAL_TOKEN.balanceOf(address(this));
        COLLATERAL_TOKEN.safeTransferFrom(msg.sender, address(this), amount);
        uint256 received = COLLATERAL_TOKEN.balanceOf(address(this)) - beforeBalance;
        if (received != amount) revert FeeOnTransferNotSupported();
        balances[user] += received;
        accountedCollateral += received;
        emit CreditReceived(msg.sender, user, amount);
    }

    /// @notice Factory-only migration hook to attribute already transferred collateral to user balances.
    function creditMigrated(address user, uint256 amount) external {
        if (msg.sender != marketFactory) revert InvalidFactory();
        if (user == address(0)) revert InvalidAddress();
        if (_excessCollateral() < amount) revert InsufficientCollateralBacking();
        balances[user] += amount;
        accountedCollateral += amount;
        emit MigratedCreditReceived(user, amount);
    }

    /// @notice Returns collateral held by escrow that is not assigned to user balances.
    function excessCollateral() external view returns (uint256) {
        return _excessCollateral();
    }

    /// @notice Owner can recover collateral that is not assigned to user balances.
    function recoverExcessCollateral(address recipient, uint256 amount) external onlyOwner nonReentrant {
        if (recipient == address(0)) revert InvalidAddress();
        if (_excessCollateral() < amount) revert InsufficientCollateralBacking();
        _safeTransferExact(recipient, amount);
        emit ExcessCollateralRecovered(recipient, amount);
    }

    function _excessCollateral() internal view returns (uint256) {
        uint256 balance = COLLATERAL_TOKEN.balanceOf(address(this));
        if (balance <= accountedCollateral) {
            return 0;
        }
        return balance - accountedCollateral;
    }

    function _isValidMarket(address market) internal view returns (bool) {
        if (market == address(0) || market.code.length == 0) return false;
        try IRevealMarket(market).factory() returns (address factory) {
            if (factory != marketFactory) return false;
        } catch {
            return false;
        }
        try IRevealMarket(market).relayerEscrow() returns (address relayer) {
            if (relayer != address(this)) return false;
        } catch {
            return false;
        }
        try IRevealMarket(market).collateralToken() returns (address token) {
            if (token != address(COLLATERAL_TOKEN)) return false;
        } catch {
            return false;
        }
        return true;
    }

    function _commitAuthorizationHash(address market, IRevealMarket.CommitAuth calldata auth)
        internal
        view
        returns (bytes32)
    {
        bytes32 commitment = auth.commitment;
        uint256 ticketId = auth.ticketId;
        address user = auth.user;
        uint256 nonce = auth.nonce;
        uint256 expiry = auth.expiry;
        uint256 ticketValue = auth.ticketValue;
        uint256 chainId = block.chainid;
        address self = address(this);
        bytes32 digest;
        assembly {
            let ptr := mload(0x40)
            mstore(ptr, self)
            mstore(add(ptr, 0x20), market)
            mstore(add(ptr, 0x40), commitment)
            mstore(add(ptr, 0x60), ticketId)
            mstore(add(ptr, 0x80), user)
            mstore(add(ptr, 0xa0), nonce)
            mstore(add(ptr, 0xc0), expiry)
            mstore(add(ptr, 0xe0), ticketValue)
            mstore(add(ptr, 0x100), chainId)
            digest := keccak256(ptr, 0x120)
        }
        return digest;
    }

    function _safeTransferExact(address recipient, uint256 amount) internal {
        uint256 senderBalanceBefore = COLLATERAL_TOKEN.balanceOf(address(this));
        uint256 recipientBalanceBefore = COLLATERAL_TOKEN.balanceOf(recipient);
        _safeTransferExact(recipient, amount, senderBalanceBefore, recipientBalanceBefore);
    }

    function _safeTransferExact(
        address recipient,
        uint256 amount,
        uint256 senderBalanceBefore,
        uint256 recipientBalanceBefore
    ) internal {
        COLLATERAL_TOKEN.safeTransfer(recipient, amount);
        uint256 senderBalanceAfter = COLLATERAL_TOKEN.balanceOf(address(this));
        if (senderBalanceAfter > senderBalanceBefore) revert FeeOnTransferNotSupported();
        uint256 senderDebited = senderBalanceBefore - senderBalanceAfter;
        if (senderDebited != amount) revert FeeOnTransferNotSupported();

        uint256 recipientBalanceAfter = COLLATERAL_TOKEN.balanceOf(recipient);
        if (recipientBalanceAfter < recipientBalanceBefore) revert FeeOnTransferNotSupported();
        uint256 recipientReceived = recipientBalanceAfter - recipientBalanceBefore;
        if (recipientReceived < amount) revert FeeOnTransferNotSupported();
    }
}
