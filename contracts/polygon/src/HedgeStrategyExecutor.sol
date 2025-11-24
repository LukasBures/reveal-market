// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {BaseLpVault} from "./BaseLpVault.sol";

/// @title HedgeStrategyExecutor
/// @notice Executes signed hedging orders on behalf of the vault by borrowing USDC to a whitelisted receiver.
/// @dev This contract is set as the vault's `hedger` and enforces additional risk rails (nonces, expiry, caps).
/// Orders are created and signed off-chain by a designated signer (bot/operator) using EIP-712.
contract HedgeStrategyExecutor is EIP712, Ownable, Pausable, ReentrancyGuard {
    /// @dev Basis points denominator for slippage/notional caps.
    uint16 public constant BPS_DENOMINATOR = 10_000;

    /// @dev EIP-712 struct hash for hedging orders.
    bytes32 public constant ORDER_TYPEHASH = keccak256(
        "Order(address receiver,uint256 amount,uint256 minOut,uint256 maxSlippageBps,uint256 deadline,bytes32 nonce)"
    );

    /// @dev Vault that sources USDC and accounts for utilization.
    BaseLpVault public immutable VAULT;

    /// @dev Off-chain signer authorized to approve hedging orders.
    address public signer;

    /// @dev Hard cap on a single order's borrow amount (in asset units).
    uint256 public maxOrderAmount;

    /// @dev Maximum slippage (bps) allowed per order; guards against extreme intents.
    uint16 public maxSlippageBps;

    /// @dev Nonce usage tracking to block replays.
    mapping(bytes32 => bool) public usedNonces;

    /// @dev Optional recipient whitelist to bound where funds can be sent.
    mapping(address => bool) public receiverAllowed;

    event SignerUpdated(address indexed previousSigner, address indexed newSigner);
    event MaxOrderAmountUpdated(uint256 previousMax, uint256 newMax);
    event MaxSlippageBpsUpdated(uint16 previousMax, uint16 newMax);
    event ReceiverAllowed(address indexed receiver, bool allowed);
    event HedgeOrderExecuted(
        bytes32 indexed orderHash,
        address indexed receiver,
        uint256 amount,
        uint256 minOut,
        uint256 maxSlippageBps,
        uint256 deadline
    );

    error InvalidSigner();
    error InvalidReceiver();
    error InvalidAmount();
    error NonceUsed();
    error OrderExpired();
    error SlippageTooHigh();
    error ReceiverNotAllowed();

    struct Order {
        address receiver; // Destination for borrowed USDC (e.g., hedging EOA / relayer).
        uint256 amount; // USDC amount to borrow from the vault.
        uint256 minOut; // Off-chain execution hint (min out / slippage control); emitted for monitoring.
        uint256 maxSlippageBps; // Per-order slippage cap (sanity-checked against global cap).
        uint256 deadline; // Expires the order to prevent replaying stale intents.
        bytes32 nonce; // Unique nonce to prevent replay.
    }

    /// @param vault_ Vault that will be borrowed from and repaid to.
    /// @param signer_ EOA that signs hedging orders.
    /// @param owner_ Admin for risk params and pausing.
    /// @param maxOrderAmount_ Per-order borrow cap in asset units.
    /// @param maxSlippageBps_ Per-order slippage cap (bps).
    constructor(BaseLpVault vault_, address signer_, address owner_, uint256 maxOrderAmount_, uint16 maxSlippageBps_)
        EIP712("HedgeStrategyExecutor", "1")
        Ownable(owner_)
    {
        if (address(vault_) == address(0)) {
            revert InvalidReceiver();
        }
        if (signer_ == address(0)) {
            revert InvalidSigner();
        }
        if (maxOrderAmount_ == 0) {
            revert InvalidAmount();
        }
        if (maxSlippageBps_ > BPS_DENOMINATOR) {
            revert SlippageTooHigh();
        }

        VAULT = vault_;
        signer = signer_;
        maxOrderAmount = maxOrderAmount_;
        maxSlippageBps = maxSlippageBps_;
    }

    /// @notice Execute a signed hedging order, borrowing USDC from the vault to the receiver.
    /// @dev Reverts on signature/nonce/expiry/cap/whitelist violations. Utilization caps are enforced in the vault.
    function executeBorrow(Order calldata order, bytes calldata signature)
        external
        nonReentrant
        whenNotPaused
        returns (bytes32 orderHash)
    {
        orderHash = _hashTypedDataV4(
            keccak256(
                abi.encode(
                    ORDER_TYPEHASH,
                    order.receiver,
                    order.amount,
                    order.minOut,
                    order.maxSlippageBps,
                    order.deadline,
                    order.nonce
                )
            )
        );

        (address recoveredSigner, ECDSA.RecoverError recoverError, ) = ECDSA.tryRecover(orderHash, signature);
        if (recoverError != ECDSA.RecoverError.NoError || recoveredSigner != signer) {
            revert InvalidSigner();
        }

        _validateOrder(order);

        usedNonces[order.nonce] = true;

        // Borrow and ship funds to the receiver; accounting + utilization caps enforced by the vault.
        VAULT.borrowForHedge(order.amount, order.receiver);

        emit HedgeOrderExecuted(
            orderHash, order.receiver, order.amount, order.minOut, order.maxSlippageBps, order.deadline
        );
    }

    /// @notice Hash an order with the EIP-712 domain; useful for off-chain signing/testing.
    function hashOrder(Order calldata order) external view returns (bytes32) {
        return _hashTypedDataV4(
            keccak256(
                abi.encode(
                    ORDER_TYPEHASH,
                    order.receiver,
                    order.amount,
                    order.minOut,
                    order.maxSlippageBps,
                    order.deadline,
                    order.nonce
                )
            )
        );
    }

    /// @notice Update the authorized signer.
    function setSigner(address newSigner) external onlyOwner {
        if (newSigner == address(0)) {
            revert InvalidSigner();
        }
        address previous = signer;
        signer = newSigner;
        emit SignerUpdated(previous, newSigner);
    }

    /// @notice Update the per-order borrow cap.
    function setMaxOrderAmount(uint256 newMaxOrderAmount) external onlyOwner {
        if (newMaxOrderAmount == 0) {
            revert InvalidAmount();
        }
        uint256 previous = maxOrderAmount;
        maxOrderAmount = newMaxOrderAmount;
        emit MaxOrderAmountUpdated(previous, newMaxOrderAmount);
    }

    /// @notice Update the per-order slippage cap (bps).
    function setMaxSlippageBps(uint16 newMaxSlippageBps) external onlyOwner {
        if (newMaxSlippageBps > BPS_DENOMINATOR) {
            revert SlippageTooHigh();
        }
        uint16 previous = maxSlippageBps;
        maxSlippageBps = newMaxSlippageBps;
        emit MaxSlippageBpsUpdated(previous, newMaxSlippageBps);
    }

    /// @notice Toggle whether a receiver is allowed to obtain borrowed funds.
    function setReceiverAllowed(address receiver, bool allowed) external onlyOwner {
        if (receiver == address(0)) {
            revert InvalidReceiver();
        }
        receiverAllowed[receiver] = allowed;
        emit ReceiverAllowed(receiver, allowed);
    }

    /// @notice Pause order execution.
    function pause() external onlyOwner {
        _pause();
    }

    /// @notice Unpause order execution.
    function unpause() external onlyOwner {
        _unpause();
    }

    function _validateOrder(Order calldata order) internal view {
        if (order.receiver == address(0)) {
            revert InvalidReceiver();
        }
        if (!receiverAllowed[order.receiver]) {
            revert ReceiverNotAllowed();
        }
        if (order.amount == 0 || order.amount > maxOrderAmount) {
            revert InvalidAmount();
        }
        if (order.maxSlippageBps > maxSlippageBps) {
            revert SlippageTooHigh();
        }
        if (order.deadline < block.timestamp) {
            revert OrderExpired();
        }
        if (usedNonces[order.nonce]) {
            revert NonceUsed();
        }
    }

    receive() external payable {
        revert InvalidReceiver(); // Never accept native assets.
    }

    fallback() external payable {
        revert InvalidReceiver();
    }
}
