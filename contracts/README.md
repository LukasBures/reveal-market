# Reveal Market On-Chain Stack

This directory houses the full smart-contract layer for Reveal Market. It contains everything required to deploy and operate privacy-friendly prediction markets on Horizen-compatible EVM chains:

- Solidity sources (`src/`)
- Foundry tests/mocks (`test/`)
- Deployment scripts (`script/`)
- Build config (`foundry.toml`, `run_local.sh`)
- Low-level documentation/specs (`docs/`, `cache/`)

The contracts convert every API-created market into a verifiable on-chain asset with:

1. **Private commit → reveal → settle flows** guarded by deadlines, guardians, and nonces.
2. **Transparent rake routing** enforced through a global manager.
3. **Groth16 proof verification** tying each settlement to a specific market + proof nonce.
4. **Factory orchestration** so ops teams can spin up new markets via minimal proxies.

> ⚠️ **Current state:** The repo ships with a mock prover that hashes payloads for demo receipts. The Solidity contracts, circuit artifacts, and prover interface are production-ready, but you must generate/import real Groth16 keys (see `proover/circuits/`) before marketing the system as zk-auditable.

Below is a detailed breakdown so new contributors, auditors, or integration partners can quickly understand and extend the system.

---

## Directory Map

```
contracts/
├── README.md                   # This document
├── PLAN.txt / TODO.md          # High-level roadmaps and prioritized items
├── foundry.toml                # Foundry configuration
├── run_local.sh                # Local build/test utility
├── cache/                      # Deployment artifacts (verifying keys, last deploy JSON)
├── docs/                       # Line-by-line guides + circuit specs
├── script/Deploy.s.sol         # Canonical deployment script
├── src/
│   ├── MarketFactory.sol
│   ├── RevealMarket.sol
│   ├── RakeManager.sol
│   ├── Verifier.sol
│   ├── interfaces/
│   ├── utils/Pairing.sol
│   └── verifiers/VerifierStub.sol
└── test/
    ├── RevealMarket.t.sol
    ├── MarketFactory.t.sol
    ├── RakeManager.t.sol
    ├── Verifier.t.sol
    ├── Pairing.t.sol
    ├── FactoryLifecycle.t.sol
    ├── RevealMarketFuzz.t.sol
    ├── RevealMarketSecurity.t.sol
    └── mocks/
```

---

## Contract Deep Dive

### `RevealMarket.sol`

| Feature | Details |
| --- | --- |
| Lifecycle | `Commit → Locked → Settled` (or `Cancelled`). Commits store hashed tickets with stake + salt. Lock enforces reveal sequencing. |
| Oracle integration | `postResult` accepts an outcome hash from the configured oracle. |
| Proof verification | `verifyProof(bytes proof, uint256[6] pubSignals)` enforces: winning pool, total pool, outcome hash, circuit version, proof nonce, and market binding. Emits `ProofReceipt` on success and prevents replay via on-chain nonce tracking. |
| Settlement | `_finalizeSettlement` deducts rake through `IRakeManager`, records `MarketResolved`, and provides `resolutionSummary()` to indexers. |
| Claims & refunds | Winners reveal their outcome+salt to claim proportional payout; losers stay private forever. Refunds available after reveal deadline or upon cancellation. |
| Controls | Guardian/factory can pause commits/claims, update oracle, cancel markets, or `emergencySettle`. |
| Security | Reentrancy guard wraps state mutations; `_settlementInProgress` prevents controller reentrancy; commit/claim phases enforced by modifiers. |

**Key Files**: `src/RevealMarket.sol`, `docs/RevealMarket_line_by_line.md`, tests under `test/RevealMarket*.t.sol`.

### `MarketFactory.sol`

| Feature | Details |
| --- | --- |
| Deployment | Uses EIP-1167 minimal proxies (`Clones`) to spawn `RevealMarket` instances. |
| Shared config | Stores implementation, rake manager, treasury, verifier, default collateral. |
| Collateral allowlist | Maintains which ERC20s are allowed; zero address sentinel means “use default collateral”. |
| Pause controls | Global commit/claim pauses plus per-market pause/guardian overrides. |
| Metadata | Emits `MarketCreated`, `MarketPaused`, `MarketMetadataUpdated` for off-chain indexers. |

**Key Files**: `src/MarketFactory.sol`, tests in `test/MarketFactory.t.sol` & `test/FactoryLifecycle.t.sol`.

### `RakeManager.sol`

| Feature | Details |
| --- | --- |
| Fee cap | `MAX_RAKE_BPS = 200` (2%); owner can adjust default rake or treasury. |
| Deduction | `takeRake(token, amount, overrideBps)` returns net pool after rake, emits `RakeTaken`. |
| Ownership | `Ownable2Step` so treasury/rake config can rotate safely. |

**Key Files**: `src/RakeManager.sol`, tests in `test/RakeManager.t.sol`. Reentrancy-specific mocks live under `test/mocks/`.

### `Verifier.sol` & helpers

| Feature | Details |
| --- | --- |
| Verifying key storage | Stores `α`, `β`, `γ`, `δ`, and the IC vector; owner can rotate keys. |
| Inputs | Enforces exactly 6 public signals (winning pool, total pool, outcome hash, circuit version, nonce, market address). |
| Pairing | Uses custom `Pairing` library with BN254 precompiles. Any invalid point/field element reverts; invalid proofs return `false`. |
| Stub | `verifiers/VerifierStub.sol` remains available for local dev when `USE_STUB_VERIFIER=1`. |

**Key Files**: `src/Verifier.sol`, `src/utils/Pairing.sol`, `docs/Verifier_line_by_line.md`, `docs/settlement-circuit.md`.

---

## Build, Test, and Tooling

### Quick Start

```bash
curl -L https://foundry.paradigm.xyz | bash
foundryup

cd contracts
forge install
forge build
forge test --gas-report
```

Use `./run_local.sh` for the standard build/test/snapshot flow. `./run_local.sh full` adds fuzzing (`FOUNDRY_PROFILE=ci.fuzz`) and coverage reports.

### Testing Coverage

- `test/RevealMarket.t.sol` – Unit tests for each path (commits, claims, refunds, proof guards, events).
- `test/RevealMarketNative.t.sol` – Mirrors ERC20 tests but with native collateral.
- `test/RevealMarketSecurity.t.sol` – Reentrancy + guardian control scenarios.
- `test/RevealMarketFuzz.t.sol` – Fuzz harness for commit/claim flows.
- `test/FactoryLifecycle.t.sol` – Full end-to-end deployment + guardian operations.
- `test/MarketFactory.t.sol`, `test/RakeManager.t.sol`, `test/Verifier.t.sol` – Component-level suites, including new verifying-key rotation guards and pairing helper checks.
- `test/Pairing.t.sol` – Unit coverage for the BN254 helper (negation, scalar multiplication) used by the verifier.

`forge snapshot` is configured (`foundry.toml`) to track gas budgets over time; CI should fail when regressions exceed thresholds.

---

## Deployment & Configuration

1. **Prepare verifying key JSON**: `contracts/cache/settlement-vk.json` must contain the actual circuit points (`alpha1`, `beta2`, `gamma2`, `delta2`, `ic`, `circuitHash`, `expectedInputs`). The file checked into Git is a placeholder—replace it with your audited Groth16 outputs before real deployments.
2. **Environment variables for `Deploy.s.sol`**:
   - `DEPLOYER_KEY`
   - `ORACLE_ADDRESS`
   - `TREASURY_ADDRESS`
   - `COLLATERAL_ADDRESS`
   - `RAKE_BPS`
   - Optional: `SETTLEMENT_VK_PATH`, `USE_STUB_VERIFIER`
3. **Run**:
   ```bash
   cd contracts
   forge script script/Deploy.s.sol:Deploy \
     --rpc-url $RPC_URL \
     --broadcast \
     --verify # optional
   ```
4. The script writes `contracts/cache/last-deployment.json` containing all deployed addresses + circuit metadata. Feed this into backend/worker env vars (`RM_FACTORY_ADDRESS`, `RM_VERIFIER_ADDRESS`, etc.).
5. When refreshing the verifying key, run `proover/circuits/generate_keys.sh` to produce `build/settlement_vk.json` and copy that file into `contracts/cache/settlement-vk.json` before redeploying the verifier.

**Note:** `USE_STUB_VERIFIER` should never be `1` outside dev/test networks.

---

## Integration Notes

- **Backend/Worker**: Reads factory + verifier addresses from deployment artifacts; constructs markets through the factory; tracks `proofNonce` and `ProofReceipt` events for audit surfaces.
- **Frontend**: Proof viewer (`frontend/app/proofs`) consumes receipts and zkVerify IDs when the backend surfaces them.
- **zkVerify**: Current code emits the necessary data (nonce + outcome hash) to send proofs to zkVerify. The worker must forward proofs and store returned receipts.

---

## Roadmap Snapshot

Refer to [`TODO.md`](./TODO.md) for the canonical backlog. Highlights:

1. **Dual zkVerify attestations** – pipeline plus UI exposure.
2. **Resolution telemetry** – richer `MarketResolved` payloads (winners array, UMA question IDs).
3. **Deployment automation** – extend scripts to emit per-market JSON manifests.
4. **Invariant / static analysis** – add Forge invariants + Slither hooks to CI.
5. **Testnet playbooks** – presets for Horizen ZEN testnet, including sample markets and documentation.

---

## References

- [`docs/settlement-circuit.md`](./docs/settlement-circuit.md) – public-signal layout, nonce semantics, zk integration plan.
- [`docs/RevealMarket_line_by_line.md`](./docs/RevealMarket_line_by_line.md) – annotated contract walkthrough.
- [`docs/Verifier_line_by_line.md`](./docs/Verifier_line_by_line.md) – verifying key management and pairing explanation.
- [`PLAN.txt`](./PLAN.txt) – historical scope/milestone log.

Questions? Reach out via hello@revealmarket.xyz or [@RevealMarket](https://x.com/RevealMarket). Auditors/partners should review this README alongside the docs and deployment artifacts before integration.
