# Groth16 Settlement Circuit

This directory hosts the reference circuit and helper scripts needed to generate the Groth16 proving/verification keys consumed by both the `prover` microservice and the Solidity verifier. The Go service boots a rapidsnark-backed prover using the artifacts produced here and refuses to start when they’re missing, guaranteeing that every proof is generated with the real circuit.

> **Prerequisites**
>
> - Node ≥ 18 plus `curl`/`tar` (the script auto-downloads the circom binary, circomlib source, and uses `npx snarkjs@0.7.4` if missing)
> - Optional: `circom` installed globally for faster runs (otherwise the official GitHub binary is cached under `build/.circom-bin/`)
> - Optional: `snarkjs` installed globally (set `USE_SYSTEM_SNARKJS=true` to use it)
> - Internet access to download the Powers of Tau file (default: `powersOfTau28_hez_final_12.ptau` from `storage.googleapis.com/zkevm/ptau/...`)
> - Apple Silicon: Rosetta is required because the upstream circom release is x86_64-only today.

## Files

| File | Description |
| --- | --- |
| `settlement.circom` | Finalized settlement circuit exposing ten public signals (merkleRoot, marketId, winningOutcomeId, totalEscrow, totalLiability, rakeBps, poolYes, poolNo, circuitHash, padding=0) while guarding rake/winner/liability/pool sums. |
| `generate_keys.sh` | Bash script that compiles the circuit, downloads the PTAU file, runs Groth16 setup, computes proving/verification key hashes + circuitHash, and emits deploy-ready JSON. |

## Usage

```bash
cd prover/circuits

# Compile circuit + run Groth16 setup
bash generate_keys.sh

# Outputs (under build/):
#   settlement.r1cs           -> constraint system
#   settlement_js/            -> witness generator artifacts
#   settlement_final.zkey     -> proving key (mount in prover container)
#   settlement_vk.json        -> verification key (canonical source for hashing)
#   settlement_hashes.json    -> proving/verification key hashes + circuitHash
#   settlement_deploy.json    -> deploy-ready verifier JSON (also copied to contracts/cache/settlement-vk.json and contracts/zen/cache/settlement-vk.json)
#   circomlib/                -> cached circomlib sources for deterministic builds
#   .circom-bin/              -> cached circom binary (auto-downloaded when not on PATH)
```

After running the script:

1. Redeploy the Solidity verifier (or rerun `forge script ... Deploy.s.sol`) so the on-chain contract picks up the new verifying key from `contracts/cache/settlement-vk.json`.
2. Mount `build/settlement_final.zkey` (and `build/settlement_js/` if you need the witness builder) inside the `prover` container so it can generate proofs.

> ⚠️ This circuit is intentionally lightweight. Extend it with additional checks (ticket commitment hashes, rake accounting, etc.) before calling the system production-ready.

`./run_local.sh` and `./run_prod.sh` refuse to start the prover unless the artifacts listed above exist under `prover/circuits/build`. Set `SKIP_PROVER_CHECK=true` only when you have already mounted audited assets elsewhere.
