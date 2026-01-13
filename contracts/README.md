# Contracts Monorepo

Two Foundry workspaces live under `contracts/`:

- `zen/` – Reveal Market core contracts for the Horizen appchain (MarketFactory, RevealMarket, ProtocolPool, RelayerEscrow, Verifier) with Poseidon-based batch settlement.
- `polygon/` – LP vault and hedging executor for Polygon-based hedging flows (BaseLpVault, HedgeStrategyExecutor).

Repo-level scripts orchestrate both workspaces and keep error selectors/verifier caches in sync.

## Layout & Tooling

- **Workspace split**: Each workspace has its own `foundry.toml`, `lib/`, `src/`, `test/`, `script/`, and cache. Run commands from within the workspace unless using the orchestrators below.
- **Shared scripts**: `contracts/run_tests.sh` runs both workspaces sequentially; `contracts/run_local.sh` shells into each workspace runner. `scripts/generate_error_selectors.py` writes `contracts/cache/errors.json` from Solidity custom errors.
- **Artifacts**: Verifier metadata (`settlement-vk.json`) lives under `contracts/cache/` (and `contracts/zen/cache/`) and is generated from `prover/circuits/build` via `prover/circuits/export_artifacts.sh`. Keep this aligned with the prover and on-chain verifier. Circuit hashes live in `prover/circuits/build/settlement_hashes.json`.

## Quick Commands

```bash
# Run both workspaces (build + tests; gas snapshot checks; fuzz/coverage when requested)
./contracts/run_tests.sh
./contracts/run_local.sh          # same as above; pass "full" to enable fuzz/coverage in each workspace

# Zen only
cd contracts/zen
forge fmt && forge build && forge test -vvv
./run_local.sh        # build + tests + gas snapshot
./run_local.sh full   # add fuzz + coverage

# Polygon only
cd contracts/polygon
forge fmt && forge build && forge test
./run_local.sh        # build + tests + gas snapshot
./run_local.sh full   # add fuzz + coverage
```

## Notes by Workspace

- **Zen**: Fixed ticket commit/reveal with Poseidon leaves and depth-8 Merkle trees (BATCH_SIZE=256). MarketFactory deploys EIP-1167 clones, registers them with RelayerEscrow/ProtocolPool, and stores circuit hash/verifier. Settlement uses `verifyAndSettleBatched` (or `verifyAndSettle` for single-batch). Authorization signer + commit nonce/expiry enforced on commits. Rake skimmed at commit; protocol liability cap enforced from ProtocolPool. Escape hatch allows refunds after commit deadline. Claim pays ERC20 directly to users.
- **Polygon**: BaseLpVault (USDC 6 decimals) mints shares and lets a hedger borrow/repay within utilization caps; HedgeStrategyExecutor validates EIP-712 orders, caps notional/slippage, and calls the vault. Owner uses Ownable2Step; pause/unpause + utilization guardrails are available.

## Deploy/Runbook Reminders

- Horizen defaults: chain id `2651420`, RPC `https://horizen-testnet.rpc.caldera.xyz/http`, explorer `https://horizen-testnet.explorer.caldera.xyz`. Update `script/Deploy.s.sol`/`.env` values when changing networks.
- After regenerating proving keys, update `contracts/cache/settlement-vk.json` and circuit hashes, redeploy verifier as needed, and align backend/prover envs (`RM_CIRCUIT_HASH`, on-chain verifier).
- `scripts/create_market.sh` in `zen/` expects factory/verifier/circuit hash/ticket size/commit cap/protocol cap/deadline and prints JSON payloads for audit.
- Error selectors: rerun `scripts/generate_error_selectors.py` after adding/modifying Solidity custom errors; backend/frontend decoders depend on it.
