// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

import {IRevealMarket} from "./interfaces/IRevealMarket.sol";

/// @notice Trusted relayer escrow that holds all user balances and forwards fixed-size commits to markets.
/// Users deposit/withdraw ERC20 collateral; only the relayer (owner) may initiate commits on their behalf.
contract RelayerEscrow is Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;
    IERC20 public immutable COLLATERAL_TOKEN;
    mapping(address => uint256) public balances;
    mapping(address => bool) public allowedMarket;

    address public marketFactory;

    event Deposited(address indexed user, uint256 amount);
    event Withdrawn(address indexed user, uint256 amount);
    event MarketRegistered(address indexed market);
    event MarketFactoryUpdated(address indexed factory);
    event CommitForwarded(address indexed market, bytes32 commitment, uint256 debitedFromUser);
    event CreditReceived(address indexed market, address indexed user, uint256 amount);

    error UnknownMarket();
    error InvalidFactory();
    error InsufficientBalance();
    error CommitFailed();
    error InvalidRelayerOwner();

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
        if (!allowedMarket[market]) revert UnknownMarket();
        uint256 ticket = IRevealMarket(market).ticketSize();
        if (balances[user] < ticket) revert InsufficientBalance();

        balances[user] -= ticket;
        COLLATERAL_TOKEN.safeTransfer(market, ticket);
        (bool success,) =
            market.call(abi.encodeWithSelector(IRevealMarket.commitWithAuthorization.selector, auth, signature));
        if (!success) revert CommitFailed();

        emit CommitForwarded(market, auth.commitment, ticket);
    }

    /// @notice Markets pay winnings back into escrow, crediting the target user without exposing them on-market.
    function creditFromMarket(address user, uint256 amount) external {
        if (!allowedMarket[msg.sender]) revert UnknownMarket();
        balances[user] += amount;
        emit CreditReceived(msg.sender, user, amount);
    }
}
