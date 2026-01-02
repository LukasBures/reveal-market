# Contracts Monorepo

This directory now namespaces chain-specific workspaces:

- `zen/` – Reveal Market contracts targeting the Horizen/ZEN appchain (Foundry workspace with `src/`, `test/`, `script/`, `lib/`, docs, cache, run scripts, etc.).
- `polygon/` – Polygon hedging LP vault (self-contained Foundry workspace with its own `lib/`, `src/`, `test/`, and run scripts).

Notes
- CI/build tooling runs each workspace separately (see `.github/workflows/cicd.yml` and `contracts/run_tests.sh`).
- Keep deployment artifacts (verifying keys, last deploy JSON) scoped per chain under their respective workspace.
- Shared patterns (e.g., Verifier, MarketFactory) can be duplicated per chain; avoid cross-chain remappings.
- Horizen Testnet defaults: chain id `2651420`, RPC `https://horizen-testnet.rpc.caldera.xyz/http`, explorer `https://horizen-testnet.explorer.caldera.xyz`. Update `script/Deploy.s.sol` envs accordingly when targeting other networks.

## What’s implemented today

- **Zen workspace** – Fixed-ticket commit/reveal flow with `RelayerEscrow`, `ProtocolPool`, `MarketFactory` (EIP-1167 clones), `RevealMarket`, and Groth16 `Verifier`. Commitments use Poseidon leaves and are locked in depth-8 batch roots (BATCH_SIZE=256); settlement uses `verifyAndSettleBatched` to sum per-batch proofs and enforces circuit hash + pool top-up limits. Tests cover authorization, deadlines, rake, surplus handling, cap enforcement, batch roots, and verifier wiring.
- **Polygon workspace** – LP vault and hedging contracts for Base/Polymarket integration (self-contained Foundry project) with its own scripts/tests; keep artifacts isolated from Zen to avoid address collisions.
- **Artifacts & vk caches** – `cache/` holds generated verifier metadata (`settlement-vk.json`) synced with prover exports; the circuit hash is field-reduced in `settlement_hashes.json`. `contracts/run_tests.sh` calls each workspace runner, while CI uses `contracts/zen/run_local.sh` and `contracts/polygon/run_local.sh` (no `full` by default).
- **Error selector generation** – `scripts/generate_error_selectors.py` produces `contracts/cache/errors.json` so backend/frontend decoders stay aligned with Solidity custom errors; run it when Solidity errors change.

## Development & testing

```bash
# Run both workspaces sequentially (build + tests + gas snapshot + fuzz when requested)
./run_tests.sh

# Zen only
cd zen
forge fmt
forge build
forge test -vvv

# Polygon only
cd polygon
forge fmt
forge test
```

Use `run_local.sh full` inside a workspace for the CI-equivalent pipeline (build → tests → gas snapshot, plus fuzz/coverage when `full` is passed).

## Deploy/useful scripts

- `zen/run_deploy.sh` reads `.env` for RPC, chain id, deployer key, collateral token, oracle, authorization signer, and verifier inputs; `zen/scripts/create_market.sh` reads `.env` for factory/verifier addresses plus circuit hash, ticket size, max commitments, protocol cap, and commit deadline. Keep envs per chain.
- `run_local.sh` in each workspace wraps Forge commands with sensible defaults; CI uses the same scripts.
- After regenerating proving keys, re-export `settlement-vk.json` and update the verifier address/circuit hash across backend/worker/prover envs.
