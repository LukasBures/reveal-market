# Reveal Market Prover

Go microservice that turns settlement payloads into Groth16 proof receipts using Horizen’s reference circuit. It exposes a simple HTTP API, heartbeat endpoints, and structured logs that mirror the API/worker format so downstream services can treat proof generation as another regulated dependency.

The service now boots a rapidsnark-backed pipeline by default:

1. Write witness inputs to disk (derived from the worker request).
2. Execute the Circom-generated `generate_witness.js` with Node to create `witness.wtns`.
3. Call `rapidsnark` with the mounted `settlement_final.zkey` to emit `proof.json` + `public.json`.
4. Convert the proof + public signals into Solidity calldata directly inside Go—no `snarkjs` roundtrips.
5. Return a cache- and log-safe response with proof JSON, public signals, calldata, backend metadata, and Groth16 circuit hash.

If the compiled artifacts are missing (for example, on a brand-new clone), the service refuses to start so you never return mocked data by accident. Generate the Circom assets (below) before launching the Docker stack.

## Prerequisites

- Node.js ≥ 18 plus the Circom witness artifacts generated via `prover/circuits/generate_keys.sh`, which produces:
  - `circuits/build/settlement_final.zkey`
  - `circuits/build/settlement_js/settlement.wasm`
  - `circuits/build/settlement_js/generate_witness.js`
- `snarkjs` is still required locally when running `generate_keys.sh` because the setup script shells out to it for Groth16 key generation, but runtime proof generation relies on the rapidsnark binary.

> **Tip:** `docker/prover/Dockerfile` installs Node + `rapidsnark@0.0.2` via npm and mounts `./prover/circuits` into `/app/circuits`. Run `bash prover/circuits/generate_keys.sh` on the host before `./run_local.sh` so the container can read the compiled assets at runtime. The npm registry only exposes `rapidsnark` as `0.0.2` today, so CI and Docker pin to that version to avoid ETARGET install failures; bump the pin once a newer release appears upstream.
> **Network defaults:** Proof payloads align with Horizen Testnet (chain id `2651420`). Keep circuit hashes, signer addresses, and `RM_PRICING_CHAIN_ID` consistent across services when swapping networks.

## Architecture Overview

```
┌────────────┐   JSON payload   ┌──────────────────────┐   witness.wtns   ┌──────────────────────┐
│ HTTP API   │ ───────────────▶ │ generate_witness.js  │ ───────────────▶ │  rapidsnark CLI      │
└────────────┘                  │  (Node + Circom)     │                  │  (proof + signals)   │
       ▲                        └──────────────────────┘                  └──────────────────────┘
       │                                 │                                      │
       │                                 ▼                                      ▼
       │                        /tmp/groth16-*/input.json            /tmp/groth16-*/{proof,public}.json
       │
       └────── structured response (proof JSON + calldata + metadata)
```

- Each request is validated and converted into a deterministic witness input JSON file.
- Node executes `generate_witness.js`, which loads `settlement.wasm` to produce `witness.wtns`.
- The rapidsnark binary consumes the proving key + witness to emit `proof.json` and `public.json`.
- The Go service parses both outputs, normalizes them into Solidity calldata/public signals, and returns a signed response with timestamps, backend metadata, and warnings (if any).

Concurrency is guarded by a semaphore so at most `PROVER_MAX_CONCURRENCY` rapidsnark processes run at once. Temporary files live under `PROVER_TEMP_DIR` and are removed after each job, keeping the filesystem clean and ensuring secrets never persist longer than needed.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `PROVER_BACKEND` | `groth16` | Only Groth16 (rapidsnark) is supported; the process exits if artifacts are missing or invalid. |
| `PROVER_LISTEN_ADDR` | `0.0.0.0:8085` | HTTP bind address. |
| `PROVER_VERSION` | `dev` | Version string surfaced in `/healthz` and proof responses. |
| `PROVER_CIRCUIT_DIR` | `circuits/build` | Base directory for circuit artifacts. |
| `PROVER_WITNESS_SCRIPT` | `${PROVER_CIRCUIT_DIR}/settlement_js/generate_witness.js` | Path to the Circom witness script. |
| `PROVER_WASM_PATH` | `${PROVER_CIRCUIT_DIR}/settlement_js/settlement.wasm` | Path to the WASM file used by the witness script. |
| `PROVER_ZKEY_PATH` | `${PROVER_CIRCUIT_DIR}/settlement_final.zkey` | Groth16 proving key. |
| `PROVER_NODE_BINARY` | `node` | Node.js executable used to run the witness script. |
| `PROVER_RAPIDSNARK_BINARY` | `rapidsnark` | CLI used for Groth16 proving. |
| `PROVER_TEMP_DIR` | system temp | Directory for ephemeral witness/proof files. |
| `PROVER_MAX_CONCURRENCY` | `runtime.NumCPU()` | Max concurrent Groth16 jobs (semaphore backed). |
| `PROVER_PROOF_TIMEOUT_SECONDS` | `120` | Per-proof timeout for witness + proving stages. |
| `PROVER_REQUEST_TIMEOUT_SECONDS` | `90` | HTTP handler timeout (wrapping Groth16 generation). |
| `PROVER_HEARTBEAT_SECONDS` | `60` | Emit structured heartbeat logs every N seconds. |
| `PROVER_CIRCUIT_HASH` | computed from `.zkey` | Optional manual override for the circuit hash returned in responses. |

Keep the compiled artifacts mounted read-only so the prover never touches mocked data.

## API Surface

| Endpoint | Method | Description |
| --- | --- | --- |
| `/healthz` | GET | Returns status, backend mode, circuit hash, uptime, and last heartbeat/proof timestamps. |
| `/heartbeat` | GET | Lightweight liveness check used by Docker. |
| `/api/v1/proofs/settlement` | POST | Accepts the settlement payload and responds with Groth16 proof data. |

**Request body** mirrors `settlementProofRequest`:

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
  "tickets": [
    {
      "user": "0x111...",
      "outcomeId": "1",
      "amount": "1000000000000000000",
      "salt": "0x1",
      "ticketHash": "0x2",
      "leaf": "0x2",
      "merklePath": [],
      "merkleIndex": 0
    }
  ],
  "metadata": {}
}
```

Public signals emitted by the circuit are fixed at ten slots in this order:
`[merkleRoot, marketId, winningOutcomeId, totalEscrow, totalLiability, rakeBps, poolYes, poolNo, circuitHash, padding(0)]`.

**Response body** (`settlementProofResponse`):

```jsonc
{
  "proof": "{ \"pi_a\": [\"...\"], ... }",   // Raw rapidsnark proof JSON string
  "public_signals": ["123456", "34567", "..."],
  "proof_calldata": [
    ["0x...","0x...", "..."],                // First array = Solidity proof fields
    ["0x...", "..."]                         // Second array = public signal calldata
  ],
  "backend": "groth16-rapidsnark",
  "circuit_hash": "0x...",
  "prover_version": "dev",
  "request_id": "req-1",
  "generated_at": "2024-01-01T00:00:00Z",
  "warnings": ["failed to compute solidity calldata"] // optional
}
```

Errors are returned as JSON with `error` and `message` fields (`invalid_request`, `prover_error`, etc.). Validation happens before expensive witness/proving work, so clients get fast failures when payloads are malformed.

## Local Testing

1. Generate the circuit artifacts.

   ```bash
   cd prover/circuits
   bash generate_keys.sh
   ```

2. Ensure Node + rapidsnark are installed (`npm install -g rapidsnark`).
3. Run the service from the repo root:

   ```bash
   PROVER_BACKEND=groth16 PROVER_CIRCUIT_DIR=prover/circuits/build go run ./prover
   ```

4. Submit a sample payload:

   ```bash
   curl -X POST http://localhost:8085/api/v1/proofs/settlement \
     -H "Content-Type: application/json" \
     -d '{"marketId":"0x123","merkleRoot":"0xbeef","winningOutcomeId":"1","poolTotals":["70","30"],"totalEscrow":"100","totalLiability":"90","rakeBps":"100","circuitHash":"0xdead","tickets":[{"user":"0x1","outcomeId":"1","amount":"10","salt":"0x1","ticketHash":"0x2","leaf":"0x2","merklePath":[],"merkleIndex":0}]}'
   ```

If the artifacts are missing or the Groth16 toolchain fails, the service exits with a non-zero status so orchestrators can alert immediately—no mock mode is available.

> **CI note:** `go test ./...` now includes an integration test that exercises the full request → witness → rapidsnark pipeline using deterministic stub binaries plus fresh artifacts created in `t.TempDir()`. GitHub Actions additionally installs rapidsnark and verifies `rapidsnark --version` so we know the binary is runnable in automation.

## Testing

```bash
cd prover
./run_tests.sh            # wraps `go test -v ./...`
# Fails fast if circuits/build artifacts are missing (check_artifacts.sh)
go run ./cmd/verify-artifacts  # CLI to verify settlement_final.zkey + settlement_js/* exist
```

The script is also invoked by repo-root `./run_tests.sh`, keeping local workflows aligned with CI’s Go job.

## Observability

- Logs follow the global format (`timestamp | LEVEL | prover | file:line | event | request_id | json`).
- `/metrics` exposes `expvar` counters (successes, failures, last latency, artifacts_ok). Scrape it with your Prometheus sidecar or use `curl` for quick debugging.
- `/debug/pprof/*` ships with Go’s built-in profiling handlers so you can capture CPU/heap profiles in staging before tuning concurrency.
- The Groth16 engine logs command output/errors when witness or proving fail, making rapidsnark issues easy to audit.
- `/healthz` includes `ready`, `backend`, and `artifacts_ok` fields so orchestrators can alert when the prover downgrades or artifacts go missing.
- Response payloads carry a `warnings` array (e.g., if calldata export fails) with enough context for downstream teams to debug.

## Operational Tips

- **Key management / artifacts** – `prover/circuits/build` must contain `settlement_final.zkey`, `settlement_js/settlement.wasm`, and `settlement_js/generate_witness.js`. Use `prover/circuits/generate_keys.sh` (requires `snarkjs`, Node) and store the outputs in a bucket with restricted access (read-only mount into the container). Refresh keys before releasing new circuits and rerun `check_artifacts.sh` to validate integrity.
- **Concurrency tuning** – Start with the default `PROVER_MAX_CONCURRENCY=runtime.NumCPU()` and raise it incrementally only after measuring CPU saturation and memory usage (rapidsnark typically peaks around 250–350 MB per job for this circuit).
- **Artifact hygiene** – Store `settlement_final.zkey` and the WASM/witness assets in a secret-managed bucket (S3 with bucket policies, GCS with CMEK) and mount them read-only into the container so proofs can’t be spoofed by tampering with files on disk.
- **Graceful restarts** – Because each job spawns a fresh rapidsnark process, `SIGTERM` simply waits for the current subprocesses to exit. Consider draining the worker (pause proof requests) before restarting for zero dropped jobs.
- **Alerting** – Monitor `prover.request.failed` logs and add Prometheus alerts for rising 5xx counts, long proof latencies, or repeated rapidsnark exits to detect artifact corruption early.
- **TLS / exposure** – If exposing the prover externally, front it with a reverse proxy (e.g., Caddy or Nginx) that terminates TLS and rate-limits the proof endpoint. Only `/healthz` and `/metrics` should be internet-reachable in most deployments; lock `/api/v1/proofs/settlement` behind internal networks.
- **Deployment steps** – Generate/mount artifacts, set env (`PROVER_LISTEN_ADDR`, `PROVER_CIRCUIT_DIR`, `PROVER_RAPIDSNARK_BINARY`, `PROVER_NODE_BINARY`, timeout/concurrency), run `./run_tests.sh` (fails if artifacts missing), then start the service. Post-deploy smoke: hit `/healthz` and submit a small proof payload; alert on `artifacts_ok=0` or repeated `prover.request.failed`.

## Docker Notes

- `docker-compose.yml` mounts `./prover/circuits` into the container so locally generated artifacts are available.
- The Dockerfile installs Node 20 + `rapidsnark@0.0.2`; override `PROVER_RAPIDSNARK_BINARY` if you need a different version.
- Running `./run_local.sh` rebuilds the prover image, so re-run after regenerating circuits.
