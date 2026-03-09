# Contracts (Polygon)

Auxiliary contracts for cross-chain hedging and LP liquidity management. Deployed on Base/Polygon.

## Contracts

| Contract | Description |
|----------|-------------|
| `BaseLpVault` | ERC20 share vault over USDC; hedger can borrow/repay for external hedging |
| `HedgeStrategyExecutor` | EIP-712 signed order executor; set as the vault's `hedger` |

---

## BaseLpVault

An ERC20 share vault (`bLPV`) holding USDC. LPs deposit USDC and receive proportional shares. A designated hedger account can borrow idle USDC for external hedging operations and repay it back; the vault tracks all outstanding borrows as `utilizedAssets` so share value stays accurate.

### Constants

| Constant | Type | Value | Description |
|----------|------|-------|-------------|
| `ASSET_DECIMALS` | `uint8` | `6` | Expected decimals of the underlying asset (USDC) |
| `BPS_DENOMINATOR` | `uint16` | `10000` | Basis points denominator |

### Key state variables

| Variable | Type | Description |
|----------|------|-------------|
| `ASSET` | `IERC20` | Immutable underlying token (USDC, 6 decimals) |
| `hedger` | `address` | Address authorized to call `borrowForHedge` and `repayFromHedge` |
| `utilizedAssets` | `uint256` | USDC currently loaned to the hedger |
| `maxUtilizationBps` | `uint16` | Maximum utilization allowed in bps (default: 10000 = 100%) |
| `maxBorrowPerCall` | `uint256` | Hard cap per single `borrowForHedge` call (default: `type(uint256).max`) |

### Accounting

- `totalAssets()` = on-chain USDC balance + `utilizedAssets`
- Shares are minted at the current `totalAssets / totalSupply` exchange rate
- `convertToShares(assets)` and `convertToAssets(shares)` use proportional math
- `withdraw()` uses ceiling rounding to prevent under-burning shares

### Key functions

| Function | Caller | Description |
|----------|--------|-------------|
| `deposit(assets, receiver)` | Anyone (paused check) | Mint shares proportional to deposited USDC |
| `withdraw(assets, receiver, owner)` | Owner or approved | Burn shares (ceil-rounded) to withdraw exact USDC |
| `redeem(shares, receiver, owner)` | Owner or approved | Burn exact shares to withdraw pro-rata USDC |
| `borrowForHedge(amount, to)` | Hedger (paused check) | Transfer idle USDC to `to`; enforces per-call and bps utilization caps |
| `repayFromHedge(amount, from)` | Hedger (paused check) | Pull USDC back from `from`; reduces `utilizedAssets` |
| `setHedger(newHedger)` | Owner | Update hedger address |
| `setMaxUtilizationBps(bps)` | Owner | Update utilization cap (max 10000) |
| `setMaxBorrowPerCall(cap)` | Owner | Update per-call borrow cap |
| `recoverToken(token, to, amount)` | Owner | Rescue non-USDC tokens accidentally sent to the vault |
| `pause()` / `unpause()` | Owner | Pause/unpause deposits, withdrawals, and hedger operations |
| `idleAssets()` | View | On-chain USDC balance (excludes utilized) |
| `totalAssets()` | View | Total USDC the vault accounts for (idle + utilized) |

### Notes

- The vault rejects fee-on-transfer tokens: received amount must equal transferred amount exactly.
- Native ETH is rejected via `receive()` and `fallback()`.
- Share token uses 18 decimals; USDC asset uses 6 decimals.

---

## HedgeStrategyExecutor

Set as the `hedger` on `BaseLpVault`. Executes signed hedging orders from an off-chain bot/operator using EIP-712. Enforces nonce uniqueness, order expiry, per-order amount caps, per-order slippage caps, and an optional receiver whitelist before forwarding borrows to the vault.

### Constants

| Constant | Type | Value | Description |
|----------|------|-------|-------------|
| `BPS_DENOMINATOR` | `uint16` | `10000` | Basis points denominator |
| `ORDER_TYPEHASH` | `bytes32` | `keccak256(...)` | EIP-712 type hash for `Order` struct |

EIP-712 domain: name `"HedgeStrategyExecutor"`, version `"1"`.

### Order struct

```solidity
struct Order {
    address receiver;       // Destination for borrowed USDC
    uint256 amount;         // USDC to borrow from the vault
    uint256 minOut;         // Off-chain execution hint (emitted for monitoring only)
    uint256 maxSlippageBps; // Per-order slippage cap (checked against global cap)
    uint256 deadline;       // Unix timestamp; order rejected if expired
    bytes32 nonce;          // Unique nonce to prevent replay
}
```

### Key state variables

| Variable | Type | Description |
|----------|------|-------------|
| `VAULT` | `BaseLpVault` | Immutable vault that is borrowed from and repaid to |
| `signer` | `address` | Off-chain EOA authorized to sign orders |
| `maxOrderAmount` | `uint256` | Global per-order borrow cap in USDC (asset units) |
| `maxSlippageBps` | `uint16` | Global per-order slippage cap in bps |
| `usedNonces` | `mapping(bytes32 => bool)` | Replay protection |
| `receiverAllowed` | `mapping(address => bool)` | Optional receiver whitelist |

### Key functions

| Function | Caller | Description |
|----------|--------|-------------|
| `executeBorrow(order, signature)` | Anyone (paused check) | Validate signature + order, then call `vault.borrowForHedge` |
| `hashOrder(order)` | View | Compute EIP-712 order hash (for off-chain signing and testing) |
| `setSigner(newSigner)` | Owner | Update authorized signer |
| `setMaxOrderAmount(amount)` | Owner | Update per-order borrow cap |
| `setMaxSlippageBps(bps)` | Owner | Update per-order slippage cap |
| `setReceiverAllowed(receiver, allowed)` | Owner | Add or remove a receiver from the whitelist |
| `pause()` / `unpause()` | Owner | Pause/unpause order execution |

### Validation order in `executeBorrow`

1. Signature recovery and match against `signer`
2. Receiver is not zero and is in `receiverAllowed`
3. Amount is non-zero and within `maxOrderAmount`
4. `order.maxSlippageBps` is within global `maxSlippageBps`
5. `order.deadline >= block.timestamp`
6. `order.nonce` not previously used
7. Vault's own utilization caps apply inside `borrowForHedge`

---

## Commands

```bash
forge build
forge test

# Gas snapshots + optional extended fuzz
./run_local.sh

# Run test suite only
./run_tests.sh
```

## Toolchain

- Solidity: `0.8.33`
- EVM: `cancun`
- Optimizer: 200 runs, `via_ir` enabled
- Libraries: OpenZeppelin Contracts
