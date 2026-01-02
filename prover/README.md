# Reveal Market Prover

Go microservice that turns settlement payloads into Groth16 proof receipts using Horizen’s reference circuit. It exposes a simple HTTP API, heartbeat endpoints, Prometheus metrics, and structured logs that mirror the API/worker format so downstream services can treat proof generation as another regulated dependency. There is no mock mode: startup fails if artifacts are missing, and `/healthz` reports `ready=false` when artifacts or backend checks fail.

The service now boots a rapidsnark-backed pipeline by default:

1. Write witness inputs to disk (derived from the worker request: batch ticket arrays + public signals).
2. Execute the Circom-generated `generate_witness.js` with Node (or the C++ witness binary) to create `witness.wtns`.
3. Call `rapidsnark` with the mounted `settlement_final.zkey` to emit `proof.json` + `public.json`.
4. Convert the proof + public signals into Solidity calldata directly inside Go—no `snarkjs` roundtrips.
5. Return a cache- and log-safe response with proof JSON, public signals, calldata, backend metadata, and Groth16 circuit hash.

If the compiled artifacts are missing (for example, on a brand-new clone), the service refuses to start so you never return mocked data by accident. Generate the Circom assets (below) or sync vetted artifacts from `prover/artifacts` before launching the Docker stack.

## Prerequisites

- Node.js ≥ 18 plus the Circom witness artifacts generated via `prover/circuits/generate_keys.sh` (or imported from `prover/artifacts`), which produces:
  - `circuits/build/settlement_final.zkey`
  - `circuits/build/settlement_vk.json`
  - `circuits/build/settlement_hashes.json`
  - `circuits/build/settlement_deploy.json`
  - `circuits/build/settlement_js/settlement.wasm`
  - `circuits/build/settlement_js/generate_witness.js`
  - `circuits/build/settlement_cpp/settlement` (optional C++ witness binary)
- `snarkjs` is still required locally when running `generate_keys.sh` because the setup script shells out to it for Groth16 key generation, but runtime proof generation relies on the rapidsnark binary.
- `rapidsnark` CLI on PATH (or pinned via `PROVER_RAPIDSNARK_BINARY`). Docker images install v0.0.7 from GitHub releases for AMD64/ARM64; local dev can use `npm i -g rapidsnark@0.0.2` if you prefer the NPM build.
- Fast storage for `/tmp` (or set `PROVER_TEMP_DIR` to tmpfs) to reduce witness/proof I/O latency.

If you set `PROVER_WITNESS_BINARY` (or `PROVER_WITNESS_MODE=cpp`), Node is optional at runtime; it is still required to run `generate_keys.sh`.

> **Tip:** `docker/prover/Dockerfile` installs Node 20 and pulls `rapidsnark v0.0.7` from official releases, mounting `./prover/circuits` into `/app/circuits`. Run `bash prover/circuits/generate_keys.sh` on the host before `./run_local.sh` so the container can read the compiled assets at runtime. The npm registry only exposes `rapidsnark` as `0.0.2`; stick to the bundled binary unless you need a different build.
> **Network defaults:** Proof payloads align with Horizen Testnet (chain id `2651420`). Keep circuit hashes, signer addresses, and `RM_PRICING_CHAIN_ID` consistent across services when swapping networks.

The vetted, source-of-truth artifacts live in the `prover/artifacts` submodule. Use `prover/circuits/export_artifacts.sh` to write `prover/circuits/build/*` plus `contracts/*/cache/settlement-vk.json` (from `settlement_deploy.json`) into that repo, and `prover/circuits/import_from_artifacts.sh` to sync them back into the main checkout.

## Current implementation snapshot
- Artifact checks (`check_artifacts.sh`, `go run ./cmd/verify-artifacts`) run before tests/startup; service refuses to start when `settlement_final.zkey`, `settlement_vk.json`, `settlement_hashes.json`, or WASM/witness assets are missing or hash mismatched.
- Concurrency guarded by semaphore (`PROVER_MAX_CONCURRENCY`); per-proof timeout wraps witness + rapidsnark; temporary directories cleaned after each job.
- Integration tests include stubbed rapidsnark/Node plus real artifact flow in CI; repo-root `./run_tests.sh` calls into the same checks.
- Metrics: `prover_request_latency_seconds` histogram, counters (`prover_proofs_success_total`, `prover_proofs_failure_total`), gauges (`prover_active_proofs`, `prover_artifacts_ok`, `prover_last_proof_latency_ms`, `prover_up`); `/healthz` carries circuit hash/readiness.

## MVP Scope

The current settlement circuit now enforces:
- `winningOutcomeId` is 0 or 1 and `rakeBps` <= 10000.
- `commitmentsCount` <= 256 with active tickets constrained to outcome 0/1 and inactive amounts forced to zero.
- Poseidon leaf hashing + depth-8 Merkle root for a 256-ticket batch.
- Pool totals and `totalLiability` computed directly from the active ticket amounts.
- `circuitHash` is field-reduced mod BN254 and must match the on-chain verifier configuration.
- `padding` equals zero (to keep a 10-signal ABI).

It still does not verify external market metadata, authorization signatures, or multi-batch aggregation beyond what the on-chain contract enforces. Treat the proofs as a batch integrity check until the circuit is extended and new artifacts are generated.

## Architecture Overview

```
┌────────────┐   JSON payload   ┌─────────────────────────────┐   witness.wtns   ┌──────────────────────┐
│ HTTP API   │ ───────────────▶ │ witness generator (Node/C++) │ ───────────────▶ │  rapidsnark CLI      │
└────────────┘                  │  generate_witness.js / C++  │                  │  (proof + signals)   │
       ▲                        └──────────────────────┘                  └──────────────────────┘
       │                                 │                                      │
       │                                 ▼                                      ▼
       │                        /tmp/groth16-*/input.json            /tmp/groth16-*/{proof,public}.json
       │
       └────── structured response (proof JSON + calldata + metadata)
```

- Each request is validated and converted into a deterministic witness input JSON file.
- A witness generator runs either via Node (`generate_witness.js` + `settlement.wasm`) or the C++ binary (`settlement_cpp/settlement`) to produce `witness.wtns`.
- The rapidsnark binary consumes the proving key + witness to emit `proof.json` and `public.json`.
- The Go service parses both outputs, normalizes them into Solidity calldata/public signals, and returns a response with timestamps, backend metadata, and warnings (if any).

Concurrency is guarded by a semaphore so at most `PROVER_MAX_CONCURRENCY` rapidsnark processes run at once. Temporary files live under `PROVER_TEMP_DIR` and are removed after each job, keeping the filesystem clean and ensuring secrets never persist longer than needed. Internal buffer pools reduce allocations when hashing artifacts or encoding witness inputs.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `PROVER_BACKEND` | `groth16` | Only Groth16 (rapidsnark) is supported; the process exits if artifacts are missing or invalid. |
| `PROVER_LISTEN_ADDR` | `0.0.0.0:8085` | HTTP bind address. |
| `PROVER_VERSION` | `dev` | Version string surfaced in `/healthz` and proof responses. |
| `PROVER_LOG_LEVEL` | `INFO` | Log level (`DEBUG`, `INFO`, `WARN`, `ERROR`). |
| `PROVER_SHARED_SECRET` | empty | Optional shared secret; when set, clients must send `X-Prover-Secret`. |
| `PROVER_CIRCUIT_DIR` | `circuits/build` | Base directory for circuit artifacts. |
| `PROVER_WITNESS_SCRIPT` | `${PROVER_CIRCUIT_DIR}/settlement_js/generate_witness.js` | Path to the Circom witness script (used when `PROVER_WITNESS_BINARY` is unset). |
| `PROVER_WITNESS_BINARY` | empty | Optional path to the C++ witness generator (e.g., `${PROVER_CIRCUIT_DIR}/settlement_cpp/settlement`). |
| `PROVER_WITNESS_MODE` | empty | Set to `cpp` to default `PROVER_WITNESS_BINARY` to the compiled C++ witness binary. |
| `PROVER_WASM_PATH` | `${PROVER_CIRCUIT_DIR}/settlement_js/settlement.wasm` | Path to the WASM file used by the Node witness script. |
| `PROVER_ZKEY_PATH` | `${PROVER_CIRCUIT_DIR}/settlement_final.zkey` | Groth16 proving key. |
| `PROVER_VK_PATH` | `${PROVER_CIRCUIT_DIR}/settlement_vk.json` | Verification key used for artifact hash validation. |
| `PROVER_HASHES_PATH` | `${PROVER_CIRCUIT_DIR}/settlement_hashes.json` | Circuit hash manifest used to validate artifacts. |
| `PROVER_NODE_BINARY` | `node` | Node.js executable used to run the witness script. |
| `PROVER_RAPIDSNARK_BINARY` | `rapidsnark` | CLI used for Groth16 proving. |
| `PROVER_TEMP_DIR` | system temp | Directory for ephemeral witness/proof files. |
| `PROVER_MAX_CONCURRENCY` | `runtime.NumCPU()` | Max concurrent Groth16 jobs (semaphore backed). |
| `PROVER_PROOF_TIMEOUT_SECONDS` | `120` | Per-proof timeout for witness + proving stages. |
| `PROVER_REQUEST_TIMEOUT_SECONDS` | `120` | HTTP handler timeout (wrapping Groth16 generation). |
| `PROVER_HEARTBEAT_SECONDS` | `60` | Emit structured heartbeat logs every N seconds. |
| `PROVER_CIRCUIT_HASH` | `settlement_hashes.json` | Optional manual override for the circuit hash returned in responses (must match the hashes file). |
| `PROVER_MAX_REQUEST_BYTES` | `1048576` | Max request body size in bytes before returning HTTP 413. |

Keep the compiled artifacts mounted read-only so the prover never touches mocked data.

## API Surface

| Endpoint | Method | Description |
| --- | --- | --- |
| `/healthz` | GET | Returns status, backend mode, circuit hash, uptime, and last heartbeat/proof timestamps. Returns HTTP 503 when `ready=false`. |
| `/heartbeat` | GET | Lightweight liveness check used by Docker. |
| `/api/v1/proofs/settlement` | POST | Accepts the settlement payload and responds with Groth16 proof data. |

Streaming responses are supported by passing `?stream=1` or an `Accept: text/event-stream` header. Events include `accepted`, `proof`, `error`, and `cancelled`.
If `PROVER_SHARED_SECRET` is set, include `X-Prover-Secret` on requests or the service will return HTTP 401.

**Request body** mirrors `settlementProofRequest` (one payload per batch root):

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
    // Pad to 256 entries with zeros.
  ]
}
```

`merkleRoot` must match the batch root stored on-chain for the provided `batchIndex`. `tickets` must be length 256; pad inactive entries with zeros and set `commitmentsCount` to the active count.

Public signals emitted by the circuit are fixed at ten slots in this order:
`[merkleRoot, marketId, winningOutcomeId, totalEscrow, totalLiability, rakeBps, poolYes, poolNo, circuitHash, padding(0)]`.

Fetch the expected `circuit_hash` from `/healthz` and include it in requests. Mismatches return HTTP 400.

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

Errors are returned as JSON with `error` and `message` fields (`invalid_request`, `prover_error`, etc.). Validation happens before expensive witness/proving work, so clients get fast failures when payloads are malformed. Requests above `PROVER_MAX_REQUEST_BYTES` return HTTP 413. The API returns HTTP 503 if the backend marks itself unready (e.g., artifacts missing).

## Local Testing

1. Ensure the circuit artifacts exist (generate or import).

   ```bash
   cd prover/circuits
   bash generate_keys.sh
   # Or, if you use the artifacts submodule:
   # bash import_from_artifacts.sh
   ```

2. Ensure Node + rapidsnark are installed (use the Docker binary or the official rapidsnark release; the npm package is older).
3. Run the service from the repo root:

   ```bash
   PROVER_BACKEND=groth16 PROVER_CIRCUIT_DIR=prover/circuits/build go run ./prover
   ```

4. Submit a sample payload:

```bash
curl -X POST http://localhost:8085/api/v1/proofs/settlement \
  -H "Content-Type: application/json" \
  -d '{"marketId":"0x123","merkleRoot":"0xbeef","winningOutcomeId":"1","poolTotals":["70","30"],"totalEscrow":"100","totalLiability":"90","rakeBps":"100","circuitHash":"0xdead","batchIndex":"0","commitmentsCount":"2","tickets":[{"ticketId":"0","outcomeId":"0","amount":"70","user":"0x1","salt":"0x1"},{"ticketId":"1","outcomeId":"1","amount":"30","user":"0x2","salt":"0x2"}]}'
```

Pad `tickets` to 256 entries (zeros for inactive rows).

If the artifacts are missing or the Groth16 toolchain fails, the service exits with a non-zero status so orchestrators can alert immediately—no mock mode is available.

> **CI note:** `go test ./...` now includes an integration test that exercises the full request → witness → rapidsnark pipeline using deterministic stub binaries plus fresh artifacts created in `t.TempDir()`. GitHub Actions installs rapidsnark and seeds circuit artifacts either via `prover/scripts/download_artifacts.sh` (`PROVER_ARTIFACTS_URL` and optionally `PROVER_ARTIFACTS_SHA256`) or the `prover/artifacts` submodule before running `go run ./cmd/verify-artifacts` and `./run_tests.sh`.

## Testing

```bash
cd prover
./run_tests.sh            # wraps `go test -v ./...`
# Fails fast if circuits/build artifacts are missing (check_artifacts.sh)
go run ./cmd/verify-artifacts  # CLI to verify required artifacts + hashes
```

The script is also invoked by repo-root `./run_tests.sh`, keeping local workflows aligned with CI’s Go job. `go test` includes an integration test that stubs Node/rapidsnark to exercise the full flow; real binaries are exercised in CI and in Docker.

## Observability

- Logs follow the global format (`timestamp | LEVEL | prover | file:line | event | request_id | json`), including command-level stderr for witness/proving failures.
- `/metrics` exposes Prometheus-friendly counters/gauges plus a latency histogram: successes/failures, `prover_active_proofs`, `prover_artifacts_ok`, `prover_last_proof_latency_ms`, and `prover_request_latency_seconds` buckets. Scrape it with your Prometheus sidecar or use `curl` for quick debugging.
- `/debug/pprof/*` ships with Go’s built-in profiling handlers so you can capture CPU/heap profiles in staging before tuning concurrency.
- The Groth16 engine logs command output/errors when witness or proving fail, making rapidsnark issues easy to audit.
- `/healthz` includes `ready`, `backend`, and `artifacts_ok` fields so orchestrators can alert when the prover downgrades or artifacts go missing.
- Response payloads carry a `warnings` array (e.g., if calldata export fails) with enough context for downstream teams to debug.

## Operational Tips

- **Key management / artifacts** – The source of truth is the `prover/artifacts` submodule. Use `prover/circuits/export_artifacts.sh` to generate/export `prover/circuits/build/*` (including `settlement_deploy.json`) plus `contracts/*/cache/settlement-vk.json` (derived from `settlement_deploy.json`), and `prover/circuits/import_from_artifacts.sh` (or `./run_local.sh`/`./run_prod.sh`) to sync vetted files into `prover/circuits/build` and the contract caches. CI can pull a tar/zip of `prover/circuits/build` via `prover/scripts/download_artifacts.sh` (driven by `PROVER_ARTIFACTS_URL` + optional `PROVER_ARTIFACTS_SHA256`); package it with `tar czf prover-artifacts.tgz -C prover/circuits/build .`. Refresh keys before releasing new circuits and rerun `check_artifacts.sh`/`go run ./cmd/verify-artifacts` to validate integrity.
- **Concurrency tuning** – Start with the default `PROVER_MAX_CONCURRENCY=runtime.NumCPU()` and raise it incrementally only after measuring CPU saturation and memory usage (rapidsnark typically peaks around 250–350 MB per job for this circuit). Set `PROVER_TEMP_DIR` to tmpfs for lower I/O latency if available.
- **Artifact hygiene** – Store `settlement_final.zkey` and the WASM/witness assets in a secret-managed bucket (S3 with bucket policies, GCS with CMEK) and mount them read-only into the container so proofs can’t be spoofed by tampering with files on disk.
- **Graceful restarts** – Because each job spawns a fresh rapidsnark process, `SIGTERM` simply waits for the current subprocesses to exit. Consider draining the worker (pause proof requests) before restarting for zero dropped jobs.
- **Alerting** – Monitor `prover.request.failed` logs and add Prometheus alerts for rising 5xx counts, long proof latencies, or repeated rapidsnark exits to detect artifact corruption early.
- **TLS / exposure** – If exposing the prover externally, front it with a reverse proxy (e.g., Caddy or Nginx) that terminates TLS and rate-limits the proof endpoint. The service only supports shared-secret auth; set `PROVER_SHARED_SECRET` and require `X-Prover-Secret`, or keep `/api/v1/proofs/settlement` on internal networks. Only `/healthz` and `/metrics` should be internet-reachable in most deployments.
- **Deployment steps** – Generate/mount artifacts, set env (`PROVER_LISTEN_ADDR`, `PROVER_CIRCUIT_DIR`, `PROVER_RAPIDSNARK_BINARY`, `PROVER_NODE_BINARY`, timeout/concurrency, `PROVER_TEMP_DIR`), run `./run_tests.sh` (fails if artifacts missing), then start the service. Post-deploy smoke: hit `/healthz` and submit a small proof payload; alert on `artifacts_ok=0` or repeated `prover.request.failed`.

## Docker Notes

- `docker-compose.yml` mounts `./prover/circuits` into the container so locally generated artifacts are available.
- The Dockerfile installs Node 20 + rapidsnark v0.0.7 (GitHub release); override `PROVER_RAPIDSNARK_BINARY` if you need a different version.
- Running `./run_local.sh` rebuilds the prover image, so re-run after regenerating circuits.

## Step-by-Step: Artifacts Submodule (Source of Truth)

1. Update the artifacts submodule:

   ```bash
   git submodule update --init --recursive prover/artifacts
   ```

2. If the circuit changed, regenerate + export artifacts (otherwise skip to step 4):

   ```bash
   cd prover/circuits
   bash export_artifacts.sh
   ```

3. Commit/push the artifacts repo, then update the submodule pointer in the main repo.
4. Sync vetted artifacts into the runtime build/caches:

   ```bash
   cd prover/circuits
   bash import_from_artifacts.sh
   ```

   `./run_local.sh` and `./run_prod.sh` also sync `contracts/*/cache/settlement-vk.json` from `settlement_deploy.json`.

5. Validate alignment:

   ```bash
   jq -r '.circuitHash' prover/circuits/build/settlement_hashes.json
   cast call <verifier> "circuitHash()(bytes32)" --rpc-url <RPC_URL>
   ```

6. If the circuit hash changed, redeploy the verifier and update `RM_VERIFIER_ADDRESS`.
7. Start the stack with `./run_local.sh` or `./run_prod.sh`.
