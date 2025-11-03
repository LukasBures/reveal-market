# Reveal Market Smart Contracts

This package contains the on-chain core for the Reveal Market MVP. It is a Foundry workspace composed of three primary contracts deployed to EVM-compatible networks:

| Contract | Purpose |
| --- | --- |
| `RevealMarket` | Commit → lock → settle prediction market with zk-proof based outcome verification, per-market controls, and guardian safeguards. |
| `MarketFactory` | Deploys EIP‑1167 clones of `RevealMarket`, manages global configuration (rake manager, verifier, treasury, collateral allow-list) and emergency switches. |
| `RakeManager` | Maintains protocol rake parameters (<= 2%), calculates net payouts, and emits fee accounting events. |
| `Verifier` | Temporary stub that always accepts proofs; to be replaced by the generated Groth16/Noir verifier before mainnet launch. |

A Foundry script (`script/Deploy.s.sol`) deploys the stack (rake manager → verifier → market implementation → factory) and logs addresses for convenience.

---

## Repository Layout

```
contracts/
├── src/                   # Solidity contracts
│   ├── RevealMarket.sol
│   ├── MarketFactory.sol
│   ├── RakeManager.sol
│   ├── Verifier.sol
│   ├── interfaces/        # External-facing interfaces
│   └── utils/             # Helper libraries (if any)
├── test/                  # Forge tests (unit, fuzz, security)
│   ├── RevealMarket.t.sol
│   ├── RevealMarketFuzz.t.sol
│   ├── RevealMarketSecurity.t.sol
│   ├── MarketFactory.t.sol
│   ├── FactoryLifecycle.t.sol
│   ├── RakeManager.t.sol
│   └── Verifier.t.sol
├── script/                # Deployment scripts (Foundry)
│   └── Deploy.s.sol
├── foundry.toml           # Project configuration
├── run_local.sh           # Helper script (build + test + gas snapshot)
├── PLAN.txt               # Original delivery scope & milestones
└── TODO.md                # Outstanding work items / enhancements
```

Dependencies live under `lib/` (via `forge install`) and include:
- `forge-std` (testing utilities)
- `openzeppelin-contracts`
- `solmate`

---

## Development Environment

1. **Install Foundry**
   ```bash
   curl -L https://foundry.paradigm.xyz | bash
   foundryup
   ```
2. **Install dependencies**
   ```bash
   cd contracts
   forge install
   ```
3. **Optional tools**
   - `slither` / `solhint` for static analysis (not yet wired into CI).
   - Node.js (>=18) if you plan to integrate with Hardhat/ethers scripts.

The project targets Solidity `^0.8.24` with optimizer enabled (200 runs, EVM `paris`).

---

## Build & Test

Basic workflow:
```bash
cd contracts
forge build
forge test --gas-report
```

The helper script `run_local.sh` runs the common flow (build → tests → gas snapshot) and optionally extended fuzz/coverage:
```bash
./run_local.sh          # build + test + snapshot check
./run_local.sh full     # + fuzz suite + coverage summary
```

Tests cover:
- Lifecycle (commit, lock, settle, claim, refund) with positive/negative pathways.
- Factory configuration, guardian controls, and market metadata wiring.
- Security/regression cases (reentrancy, double-claim prevention, deadline enforcement).
- Fuzz suite for edge-case tickets and pool math.

Gas snapshots are stored in `.gas-snapshot`; use `forge snapshot` to update baselines.

---

## Deployment

Use the Foundry script to deploy the full stack. Set required env vars and run:

```bash
export DEPLOYER_KEY=0x...              # private key (hex)
export ORACLE_ADDRESS=0x...            # off-chain oracle EOAs
export TREASURY_ADDRESS=0x...
export RAKE_BPS=100                    # e.g. 1% rake
export MARKET_METADATA_URI="ipfs://..."
export COLLATERAL_ADDRESS=0x0000000000000000000000000000000000000000  # native collateral

forge script script/Deploy.s.sol --broadcast --rpc-url $RPC_URL
```

This deploys:
1. `RakeManager` with the configured treasury/rake.
2. Stub `Verifier`.
3. `RevealMarket` implementation logic contract.
4. `MarketFactory` pointing to the deployed dependencies.

After deployment you can optionally call `factory.createMarket(...)` to instantiate a demo market (commented example at bottom of the script).

---

## Contract Overview

- **RevealMarket**
  - Phases: `Commit → Locked → Settled → Cancelled`.
  - Users submit hash commitments + stakes, optionally in ERC20 collateral.
  - Oracle posts outcome hash, proof is verified (currently stubbed), winners claim payouts net of rake.
  - Guardian + factory-level switches allow pausing commits/claims, updating guardians, emergency settlement, and cancellation with refunds.
  - Supports per-market rake overrides (`RakeConfigured` event). `appliedRakeBps()` reports the rate in effect.
  - Uses `SafeTransferLib` and `ReentrancyGuard` for safety.

- **MarketFactory**
  - Deploys minimal proxies of `RevealMarket` and registers them.
  - Maintains global allow list of collateral tokens (including native).
  - `createMarket` accepts an optional rake override (in BPS) alongside the global default.
  - `MarketCreated` emits `(market, eventId, commitDeadline, revealDeadline, collateral, rakeBps)` so indexers know the fee.
  - Guardian/owner toggles allow pausing all commits/claims, updating metadata URIs, or replacing the implementation/verifier/rake manager.

- **RakeManager**
  - Tracks rake BPS (max 2%) and treasury address.
  - Emits `RakeTaken` events to aid accounting.
  - Actual transfer is handled by `RevealMarket` using the returned net amount.

- **Verifier (stub)**
  - Always returns true but emits `ProofChecked`.
  - Replace with the generated Groth16/Noir verifier before mainnet (see `contracts/TODO.md`).

---

## Scripts & Tooling

- **Gas Snapshot**: `forge snapshot --check` ensures no unexpected gas regressions.
- **Coverage**: `forge coverage --report summary`
- **Fuzz**: `FOUNDRY_PROFILE=ci.fuzz forge test --match-test testFuzz`
- **Linting**: Add `slither .` / `solhint` once configured (see TODO).

---

## Known Limitations (MVP)

- `Verifier.sol` is a placeholder. Integrate the generated verifier + real `pubSignals` layout before production.
- Market metadata is currently a free-form string; schema enforcement and on-chain storage constraints not yet defined.
- Rake calculation assumes `takeRake` caller transfers the fee—no direct transfer occurs in the rake manager.
- No invariants/foundry `InvariantTest` suite yet; recommended before audit.
- Deployment script does not automatically create markets; manual step required.

See [`TODO.md`](./TODO.md) for the prioritized backlog.
