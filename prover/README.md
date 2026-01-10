# Reveal Market Prover

Go microservice that turns settlement payloads into Groth16 proofs using the compiled batch-settlement circuit. It requires real Circom artifacts at runtime (no mock mode) and wraps rapidsnark + the Circom witness generator behind a simple HTTP API with health/metrics.

```
Worker/Hedger -> Prover API -> witness generator (Node or C++) -> rapidsnark -> proof + public signals
```

## Pipeline

1. Validate request and artifact readiness; enforce max body size (`PROVER_MAX_REQUEST_BYTES`).
2. Build deterministic witness input JSON for the settlement batch (tickets padded to 256, fixed 10-signal order).
3. Generate witness via Node (`generate_witness.js` + WASM) or the C++ binary (if `PROVER_WITNESS_BINARY`/`PROVER_WITNESS_MODE=cpp` is set).
4. Run `rapidsnark` with the proving key to produce `proof.json` + `public.json`.
5. Return proof, public signals, Solidity calldata, circuit hash, and metadata. Optional SSE streaming (`?stream=1` or `Accept: text/event-stream`) emits `accepted` → `proof` (or `error`). Temp dirs are cleaned per request; concurrency is bounded by a semaphore.

Startup fails if required artifacts are missing or hash-mismatched.

## Endpoints

- `GET /healthz` – readiness, circuit hash, uptime, last proof timestamps; HTTP 503 when artifacts missing/unready.
- `GET /heartbeat` – lightweight liveness probe (Docker healthcheck).
- `GET /metrics` – Prometheus counters/gauges (latency, proofs success/failure, artifacts ok, active proofs).
- `GET /metrics/expvar` – expvar view (debug).
- `GET /debug/pprof/*` – Go pprof (trusted environments only).
- `POST /api/v1/proofs/settlement` – settlement proof generation (JSON body), optional SSE via `?stream=1`.

## Artifacts & Prereqs

Runtime requires the compiled circuit under `prover/circuits/build` (or another directory if overridden):

- `settlement_final.zkey`
- `settlement_vk.json`
- `settlement_hashes.json`
- `settlement_js/settlement.wasm`
- `settlement_js/generate_witness.js`
- `settlement_cpp/settlement` (optional C++ witness binary)

Acquire them by:

- Running `prover/circuits/generate_keys.sh` (needs Node 18+ and snarkjs), or
- Downloading an artifact archive via `PROVER_ARTIFACTS_URL` + `PROVER_ARTIFACTS_SHA256` using `prover/scripts/download_artifacts.sh`, or
- Using the optional `prover/artifacts` mirror with `prover/circuits/import_from_artifacts.sh`.

`rapidsnark` must be available (`PROVER_RAPIDSNARK_BINARY` to override). Docker image bundles v0.0.7 for amd64/arm64. Node is required unless using the C++ witness path at runtime; Node/snarkjs are required to regenerate artifacts.

## Configuration (env)

- Core: `PROVER_BACKEND=groth16` (only supported), `PROVER_LISTEN_ADDR` (default `0.0.0.0:8085`), `PROVER_LOG_LEVEL`, `PROVER_VERSION` string.
- Security: `PROVER_SHARED_SECRET` (require `X-Prover-Secret`), `PROVER_MAX_REQUEST_BYTES`.
- Artifacts: `PROVER_CIRCUIT_DIR`, `PROVER_WITNESS_SCRIPT`, `PROVER_WITNESS_BINARY`, `PROVER_WITNESS_MODE`, `PROVER_WASM_PATH`, `PROVER_ZKEY_PATH`, `PROVER_VK_PATH`, `PROVER_HASHES_PATH`, `PROVER_CIRCUIT_HASH` (override, must match hashes file).
- Binaries: `PROVER_NODE_BINARY`, `PROVER_RAPIDSNARK_BINARY`.
- Runtime: `PROVER_TEMP_DIR`, `PROVER_MAX_CONCURRENCY`, `PROVER_PROOF_TIMEOUT_SECONDS`, `PROVER_REQUEST_TIMEOUT_SECONDS`, `PROVER_HEARTBEAT_SECONDS`.

## Running & Testing

```bash
# Ensure circuits/build exists (generate or import)
cd prover/circuits
bash generate_keys.sh   # or: bash import_from_artifacts.sh

# Run the service
cd ../../
PROVER_CIRCUIT_DIR=prover/circuits/build go run ./prover

# Tests (artifact checks + integration harness)
go test ./prover/...
```

Docker: `docker compose up prover` (image installs Node + rapidsnark and expects circuits mounted). Startup fails fast when artifacts are missing.

## Request Shape (settlement)

```jsonc
{
  "marketId": "0x1234",
  "merkleRoot": "0xabc...",
  "winningOutcomeId": "1",
  "poolTotals": ["7000000000000000000", "3000000000000000000"],
  "totalEscrow": "10000000000000000000",
  "totalLiability": "9000000000000000000",
  "rakeBps": "100",
  "circuitHash": "0xdead...",
  "batchIndex": "0",
  "commitmentsCount": "2",
  "tickets": [
    { "ticketId": "0", "outcomeId": "0", "amount": "7", "user": "0xabc...", "salt": "0x01" },
    { "ticketId": "1", "outcomeId": "1", "amount": "3", "user": "0xdef...", "salt": "0x02" }
    // Pad to 256 entries with zeros
  ]
}
```

Public signals order is fixed (10 slots): `[merkleRoot, marketId, winningOutcomeId, totalEscrow, totalLiability, rakeBps, poolYes, poolNo, circuitHash, padding(0)]`. `circuitHash` must match the hashes file/on-chain verifier; mismatches return HTTP 400.

## Operational Notes

- Artifacts are validated at startup; `/healthz` reports readiness and circuit hash. Keep the hash aligned with the on-chain verifier and backend settings.
- Temporary files live under `PROVER_TEMP_DIR` (default system temp) and are cleaned per request; ensure the location is fast (tmpfs recommended).
- Concurrency is bounded; requests over the limit queue behind the semaphore. `PROVER_PROOF_TIMEOUT_SECONDS` wraps witness + proving.
- Streaming responses are best-effort; standard JSON responses are always returned when `stream` is unset.
