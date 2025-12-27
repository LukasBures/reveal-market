// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

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

    address public marketFactory;
    bool public commitsPaused;

    event Deposited(address indexed user, uint256 amount);
    event Withdrawn(address indexed user, uint256 amount);
    event MarketRegistered(address indexed market);
    event MarketFactoryUpdated(address indexed factory);
    event CommitsPausedSet(bool paused);
    event CommitForwarded(address indexed market, bytes32 commitment, uint256 debitedFromUser);
    event CreditReceived(address indexed market, address indexed user, uint256 amount);

    /// @notice View helper matching ERC20 style balanceOf for frontends/indexers.
    function balanceOf(address user) external view returns (uint256) {
        return balances[user];
    }

    error UnknownMarket();
    error InvalidFactory();
    error InsufficientBalance();
    error CommitFailed();
    error InvalidRelayerOwner();
    error UserMismatch();
    error CommitsPaused();
    error NotAuthorized();

    constructor(address owner_, IERC20 collateralToken_) Ownable(owner_) {
        COLLATERAL_TOKEN = collateralToken_;
    }

    /// @notice Sets the factory allowed to register new markets.
    function setMarketFactory(address factory) external onlyOwner {
        if (factory == address(0)) revert InvalidFactory();
        marketFactory = factory;
        emit MarketFactoryUpdated(factory);
    }

    /// @notice Factory hook to whitelist a freshly deployed market.
    function registerMarket(address market) external {
        if (msg.sender != marketFactory) revert InvalidFactory();
        allowedMarket[market] = true;
        emit MarketRegistered(market);
    }

    /// @notice Users deposit ERC20 collateral into their escrow balance (requires prior approval).
    function deposit(uint256 amount) external {
        COLLATERAL_TOKEN.safeTransferFrom(msg.sender, address(this), amount);
        balances[msg.sender] += amount;
        emit Deposited(msg.sender, amount);
    }

    /// @notice Owner can deposit on behalf of a user (e.g., when funding via off-chain rails).
    function depositFor(address user, uint256 amount) external onlyOwner {
        COLLATERAL_TOKEN.safeTransferFrom(msg.sender, address(this), amount);
        balances[user] += amount;
        emit Deposited(user, amount);
    }

    /// @notice Withdraw caller balance to their wallet.
    function withdraw(uint256 amount) external nonReentrant {
        if (balances[msg.sender] < amount) revert InsufficientBalance();
        balances[msg.sender] -= amount;
        COLLATERAL_TOKEN.safeTransfer(msg.sender, amount);
        emit Withdrawn(msg.sender, amount);
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

        balances[user] -= ticket;
        COLLATERAL_TOKEN.safeTransfer(market, ticket);
        IRevealMarket(market).commitWithAuthorization(auth, signature);

        emit CommitForwarded(market, auth.commitment, ticket);
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
        balances[user] += amount;
        emit CreditReceived(msg.sender, user, amount);
    }
}
