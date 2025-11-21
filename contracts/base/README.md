# Base Contracts Workspace

This workspace contains the Base-chain LP vault used to fund hedging on Polymarket. It is self-contained with its own dependencies under `contracts/base/lib/` (OpenZeppelin v5.0.0 and forge-std v1.9.1).

## Structure
- `src/BaseLpVault.sol` – ERC20 share token vault over USDC (6 decimals) with hedger-controlled borrow/repay, pause, utilization cap, and strict accounting.
- `test/BaseLpVault.t.sol` – Comprehensive Forge tests covering deposits/withdrawals/redemptions, utilization limits, price-per-share math, hedger access control, deflationary token guards, zero-address rejection, pause behavior, and event emission.
- `run_local.sh` – Build, test, gas snapshot check (optional fuzz/coverage when run with `full`).
- `run_tests.sh` – Thin wrapper to run the local pipeline.
- `foundry.toml` / `foundry.lock` – Workspace configuration and pinned deps.

## Usage
```bash
cd contracts/base
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
