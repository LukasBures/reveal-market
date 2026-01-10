# Polygon Contracts Workspace

Foundry workspace for the Polygon hedging LP vault. Contracts live under `contracts/polygon/src` and are independent from the Horizen/Zen stack.

## Components

- **BaseLpVault** – ERC20 share vault over USDC (6 decimals). Supports deposit/withdraw/redeem, hedger-only borrow/repay, utilization cap, pause, and strict accounting (rejects deflationary tokens). Price-per-share and utilization are surfaced for monitoring.
- **HedgeStrategyExecutor** – EIP-712 order executor that validates nonces/expiry/notional + slippage caps, enforces receiver whitelist, and borrows from the vault to fund hedges. Owner/hedger roles are configurable; pausable.

Ownable2Step is used for admin transfers; pausing protects both contracts.

## Project Structure

```
contracts/polygon/
├── src/
│   ├── BaseLpVault.sol
│   └── HedgeStrategyExecutor.sol
├── test/
│   ├── BaseLpVault.t.sol
│   └── HedgeStrategyExecutor.t.sol
├── script/          # deploy scripts if added
├── run_local.sh     # build + tests + gas snapshot (fuzz/coverage on `full`)
├── run_tests.sh     # wrapper around run_local.sh
├── foundry.toml
└── foundry.lock
```

## Usage

```bash
cd contracts/polygon
forge fmt
forge build
forge test
./run_local.sh        # build + tests + gas snapshot
./run_local.sh full   # add fuzz + coverage where configured
```

## Behaviors to Know

- Vault enforces USDC decimals at construction; other assets revert.
- All external mutations are `nonReentrant` and `whenNotPaused`. Hedger-only methods enforce the configured hedger.
- Utilization = borrowed / total assets; withdrawals are limited to idle capital so hedger utilization cannot block redemptions. `maxUtilizationBps` caps utilization (owner adjustable).
- Hedge executor validates EIP-712 signatures, nonces, expiry, notional caps, slippage, and whitelisted receivers before borrowing.
- Deflationary/fee-on-transfer tokens are rejected via transfer-in amount checks.

## Deployment Notes

- Target chain: Polygon PoS (chain id 137). Provide RPC via Foundry env (`POLYGON_RPC_URL`); use `ETHERSCAN_API_KEY` for verification if desired.
- Ownership is two-step; script ownership transfers and guardian pause flows before production. Set `maxUtilizationBps`, hedger, signer, and receiver whitelist pre-launch.
- Monitor `Deposit`, `Withdraw`, `Borrowed`, `Repaid`, pause/unpause, and ownership events for ops dashboards.

CI/compose calls `contracts/run_tests.sh` and `contracts/polygon/run_local.sh`; keep gas snapshots current when changing logic.
