# Polygon Contracts Workspace

This workspace contains the Polygon hedging LP vault used to fund hedging on Polymarket. It is self-contained with its own dependencies under `contracts/polygon/lib/` (OpenZeppelin v5.0.0 and forge-std v1.9.1).

## Structure
- `src/BaseLpVault.sol` – ERC20 share token vault over USDC (6 decimals) with hedger-controlled borrow/repay, pause, utilization cap, and strict accounting.
- `src/HedgeStrategyExecutor.sol` – EIP-712 order executor that acts as the vault hedger, enforces nonces/expiry/notional+slippage caps, and borrows USDC to whitelisted receivers.
- `test/BaseLpVault.t.sol` – Comprehensive Forge tests covering deposits/withdrawals/redemptions, utilization limits, price-per-share math, hedger access control, deflationary token guards, zero-address rejection, pause behavior, and event emission.
- `test/HedgeStrategyExecutor.t.sol` – Tests the EIP-712 path, replay protection, caps, pause, and whitelist enforcement.
- `run_local.sh` – Build, test, gas snapshot check (optional fuzz/coverage when run with `full`).
- `run_tests.sh` – Thin wrapper to run the local pipeline.
- `foundry.toml` / `foundry.lock` – Workspace configuration and pinned deps.

## Usage
```bash
cd contracts/polygon
forge test            # run all tests
./run_local.sh        # build + tests + gas snapshot check
./run_local.sh full   # plus fuzz + coverage (best-effort)
```

## Notes
- USDC decimals are enforced at construction; any other asset reverts.
- All external mutations are `nonReentrant` and `whenNotPaused`; hedger-only functions are gated by `hedger`.
- Deflationary/fee-on-transfer assets are rejected via transfer-in amount checks.
- Total assets are `idle + utilized`; withdrawals are limited to idle capital so hedger utilization cannot break redemptions.
- `maxUtilizationBps` caps utilization (default 100%); owner can reduce this to limit hedger risk.

## Deployment / Runbook (Polygon)

- **Chain**: Polygon PoS (Chain ID 137). Configure RPC + gas params via Foundry/forge env (`POLYGON_RPC_URL`, `ETHERSCAN_API_KEY` for verification if desired).
- **Contracts**: `BaseLpVault` (USDC 6 decimals), `HedgeStrategyExecutor`. Owner is `Ownable2Step`; transfer ownership using `transferOwnership` then `acceptOwnership`.
- **Verifier/keys**: If wiring to on-chain verifiers, set the verifying key addresses and guardian/hedger roles at deploy time. Keep admin keys in a secure wallet and script ownership transfers (e.g., `forge script script/Deploy.s.sol --rpc-url ... --broadcast`).
- **Pause/guards**: Before go-live set `maxUtilizationBps`, whitelist receivers, and test pause/unpause. Hedger-only functions are protected; ensure guardian can pause in incident response.
- **Monitoring**: Subscribe to `Deposit`, `Withdraw`, `Borrowed`, `Repaid`, and pause/ownership events for indexers. Track vault share price and utilization; alert on utilization spikes or pauses.
- **CI/Smoke**: `./run_local.sh` (or `run_tests.sh`) must pass before deploy. Include a dry-run deploy script against Polygon testnet with `--fork-url` to validate gas and configs.
