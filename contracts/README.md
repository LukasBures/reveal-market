# Contracts

Foundry workspaces for on-chain components.

## Workspaces

| Workspace | Description |
|-----------|-------------|
| `contracts/zen` | Core RevealMarket contracts deployed on Horizen Testnet (chain ID 2651420) |
| `contracts/polygon` | Auxiliary hedging/LP contracts deployed on Base/Polygon |

## Build and Test

```bash
# In either workspace
forge build
forge test

# Run gas snapshots and optional extended fuzz for both workspaces
contracts/run_local.sh

# Run tests for both workspaces
contracts/run_tests.sh
```

## Toolchain

- Solidity: `0.8.33`
- EVM: `cancun`
- Optimizer: 200 runs, `via_ir` enabled
- Foundry fuzz runs: 32 (local), 64 (CI)
- Libraries: OpenZeppelin Contracts, solmate (zen only)

## Monitoring

One-shot monitoring report: `contracts/scripts/monitoring_report.sh`
