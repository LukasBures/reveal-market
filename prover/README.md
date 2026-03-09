# Prover

Go-based Groth16 prover service that generates settlement proofs. It validates circuit artifacts at startup, exposes health/metrics endpoints, and can stream proof responses over SSE.

## Entrypoint

`prover/main.go`

## Go source files

| File | Role |
| --- | --- |
| `main.go` | HTTP server, routing, request handling, proof dispatch |
| `groth16_prover.go` | Witness generation + rapidsnark invocation, calldata encoding |
| `worker.go` | File-queue worker mode (`PROVER_WORKER_MODE=worker`) |
| `warmup.go` | Loads `warmup_request.json` for the `/warmup` endpoint |
| `cache.go` | In-memory proof result cache (SHA-256 keyed, TTL + max-entries eviction) |
| `metrics.go` | Prometheus text-format exposition + expvar counters/histograms |
| `internal/shared/config.go` | `LoadConfig()` — all env var parsing and defaults |
| `internal/shared/artifacts.go` | Keccak-256 artifact hash verification against `settlement_hashes.json` |
| `internal/shared/env.go` | Low-level env helpers (`getenv`, `intEnv`, `floatEnv`) |

## Endpoints

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `POST` | `/api/v1/proofs/settlement` | `X-Prover-Secret` | Generate a Groth16 settlement proof. Add `?stream=1` or `Accept: text/event-stream` for SSE streaming. |
| `GET` | `/api/v1/proofs/preflight` | `X-Prover-Secret` | Returns `circuit_hash` + `ready` flag; used by the worker before submitting proofs. |
| `POST` | `/api/v1/proofs/warmup` | `X-Prover-Secret` | Runs a proof from `circuits/build/warmup_request.json` to pre-heat JIT/caches. |
| `GET` | `/healthz` | none | JSON health payload including artifact status, backend, and readiness. Response is cached for `PROVER_HEALTH_CACHE_SECONDS`. Returns 503 when not ready. |
| `GET` | `/heartbeat` | none | Liveness signal; returns `{"status":"ok","heartbeat_at":"..."}`. |
| `GET` | `/metrics` | none | Prometheus text metrics. |
| `GET` | `/metrics/expvar` | `X-Prover-Secret` | Expvar metrics — only registered when `PROVER_ENABLE_DEBUG=true`. |
| `GET` | `/debug/pprof/*` | `X-Prover-Secret` | pprof endpoints — only registered when `PROVER_ENABLE_DEBUG=true`. |

### Proof request body (`POST /api/v1/proofs/settlement`)

```json
{
  "marketId": "<decimal or hex>",
  "merkleRoot": "<0x hex>",
  "winningOutcomeId": "0",
  "totalEscrow": "<decimal>",
  "totalLiability": "<decimal>",
  "rakeBps": "<decimal, 0-10000>",
  "poolTotals": ["<yes decimal>", "<no decimal>"],
  "circuitHash": "<0x hex>",
  "batchIndex": "<decimal>",
  "commitmentsCount": "<decimal, 1-256>",
  "tickets": [ /* exactly 256 entries */ ]
}
```

Each ticket: `{ "ticketId", "outcomeId", "amount", "payout", "user", "salt" }` (all decimal or hex strings).

### Proof response

```json
{
  "proof": "<rapidsnark JSON string>",
  "public_signals": ["<10 field elements>"],
  "circuit_hash": "0x...",
  "generated_at": "2026-01-02T15:04:05.000Z",
  "prover_version": "...",
  "request_id": "req-1-...",
  "backend": "groth16-rapidsnark",
  "proof_calldata": [["<pi_a/pi_b/pi_c hex>"], ["<public signal hex>"]],
  "warnings": []
}
```

## Auth

All proof/preflight/warmup endpoints require `X-Prover-Secret: <value>` matching `RM_PROVER_SHARED_SECRET`. `/healthz`, `/heartbeat`, and `/metrics` are unauthenticated. Debug endpoints require the secret even when `PROVER_ENABLE_DEBUG=true`.

## Binary dependencies

| Binary | Purpose | Env override |
| --- | --- | --- |
| `rapidsnark` | Groth16 proof generation from witness | `PROVER_RAPIDSNARK_BINARY` |
| `node` | JS witness generator (default mode) | `PROVER_NODE_BINARY` |
| `settlement_cpp/settlement` | C++ witness generator (optional fast path) | `PROVER_WITNESS_BINARY` or `PROVER_WITNESS_MODE=cpp` |

When `PROVER_WITNESS_BINARY` is set (or `PROVER_WITNESS_MODE=cpp`), `node` is not required. The C++ binary is auto-resolved to `<PROVER_CIRCUIT_DIR>/settlement_cpp/settlement`.

## Artifact verification

On startup `VerifyArtifacts` (Keccak-256) checks every file in `settlement_hashes.json`. The prover exits 1 if any artifact is missing, empty, or has a hash mismatch. The `BATCH_SIZE` declared in `settlement_hashes.json` must equal 256. Artifacts are re-verified in the background every 60 seconds and reflected in `/healthz`.

Required files (resolved relative to `PROVER_CIRCUIT_DIR`, default `circuits/build`):

- `settlement_final.zkey`
- `settlement_vk.json`
- `settlement_hashes.json`
- `settlement_js/generate_witness.js`
- `settlement_js/settlement.wasm`
- `settlement_cpp/settlement` (only when using C++ witness mode)

## Environment variables

### Core

| Variable | Default | Description |
| --- | --- | --- |
| `RM_PROVER_SHARED_SECRET` | _(required)_ | Shared secret for `X-Prover-Secret` header auth |
| `PROVER_LISTEN_ADDR` | `0.0.0.0:8085` | HTTP listen address |
| `PROVER_VERSION` | `dev` | Version string reported in health/proof responses |
| `PROVER_CIRCUIT_HASH` | _(empty)_ | Override circuit hash; must match `settlement_hashes.json` if set |
| `PROVER_HEARTBEAT_SECONDS` | `60` | Interval between heartbeat log lines |
| `PROVER_BACKEND` | `groth16` | Backend mode: `groth16` or `auto` (mock is disabled) |
| `PROVER_WORKER_MODE` | `inline` | Set to `worker` to run file-queue worker mode instead of HTTP server |
| `PROVER_ENABLE_DEBUG` | `false` | Enable `/metrics/expvar` and `/debug/pprof/*` endpoints |
| `PROVER_LOG_LEVEL` | `INFO` | Log level: `DEBUG`, `INFO`, `WARN`, `ERROR` |

### Artifact paths

| Variable | Default | Description |
| --- | --- | --- |
| `PROVER_CIRCUIT_DIR` | `circuits/build` | Base directory for all artifact paths |
| `PROVER_ZKEY_PATH` | `<CIRCUIT_DIR>/settlement_final.zkey` | Groth16 proving key |
| `PROVER_VK_PATH` | `<CIRCUIT_DIR>/settlement_vk.json` | Verification key |
| `PROVER_HASHES_PATH` | `<CIRCUIT_DIR>/settlement_hashes.json` | Artifact hash manifest |
| `PROVER_WASM_PATH` | `<CIRCUIT_DIR>/settlement_js/settlement.wasm` | WASM witness artifact |
| `PROVER_WITNESS_SCRIPT` | `<CIRCUIT_DIR>/settlement_js/generate_witness.js` | JS witness generator script |
| `PROVER_WITNESS_BINARY` | _(empty)_ | Explicit path to C++ witness binary (overrides JS mode) |
| `PROVER_WITNESS_MODE` | _(empty)_ | Set to `cpp` to auto-resolve C++ binary from `<CIRCUIT_DIR>/settlement_cpp/settlement` |
| `PROVER_RAPIDSNARK_BINARY` | `rapidsnark` | Path/name of rapidsnark binary |
| `PROVER_NODE_BINARY` | `node` | Path/name of Node.js binary |
| `PROVER_TEMP_DIR` | _(system temp)_ | Directory for per-proof temporary working directories |

### Proof generation

| Variable | Default | Description |
| --- | --- | --- |
| `PROVER_MAX_CONCURRENCY` | `<num_cpus>` | Maximum simultaneous proof generations |
| `PROVER_PROOF_TIMEOUT_SECONDS` | `120` | Per-proof subprocess timeout |
| `PROVER_REQUEST_TIMEOUT_SECONDS` | `<PROOF_TIMEOUT>` | Total request context timeout |
| `PROVER_MAX_REQUEST_BYTES` | `1048576` | Maximum request body size in bytes |
| `PROVER_STRICT_VALIDATION` | `true` | Enforce internal consistency (pool totals, rake) |

### Queue and cache

| Variable | Default | Description |
| --- | --- | --- |
| `PROVER_ASYNC_QUEUE_ENABLED` | `true` | Enable in-memory proof queue to smooth bursts |
| `PROVER_QUEUE_MAX_DEPTH` | `32` | Maximum pending queue slots; requests block when full |
| `PROVER_QUEUE_ACQUIRE_TIMEOUT_SECONDS` | `2` | How long to wait for a queue slot before returning 429 |
| `PROVER_CACHE_TTL_SECONDS` | `300` | Proof result cache TTL (0 to disable) |
| `PROVER_CACHE_MAX_ENTRIES` | `500` | Maximum cached proof results (oldest evicted when full) |

### HTTP server timeouts

| Variable | Default | Description |
| --- | --- | --- |
| `PROVER_READ_HEADER_TIMEOUT_SECONDS` | `5` | `http.Server.ReadHeaderTimeout` |
| `PROVER_READ_TIMEOUT_SECONDS` | `15` | `http.Server.ReadTimeout` |
| `PROVER_WRITE_TIMEOUT_SECONDS` | `180` | `http.Server.WriteTimeout` |
| `PROVER_IDLE_TIMEOUT_SECONDS` | `60` | `http.Server.IdleTimeout` |
| `PROVER_MAX_HEADER_BYTES` | `1048576` | `http.Server.MaxHeaderBytes` |

### Health

| Variable | Default | Description |
| --- | --- | --- |
| `PROVER_HEALTH_CACHE_SECONDS` | `5` | TTL for cached `/healthz` response |

## Worker mode

When `PROVER_WORKER_MODE=worker` the service skips the HTTP server and instead processes proof jobs from a JSONL file queue (`proof_queue.jsonl`) in the working directory. It polls every 2 seconds, retries failed jobs up to 3 times, and routes permanently failed jobs to `proof_queue.deadletter.jsonl`. Interrupted `.processing.*` files are recovered on startup.

## Prometheus metrics

| Metric | Type | Description |
| --- | --- | --- |
| `prover_proofs_success_total` | counter | Total successful proofs |
| `prover_proofs_failure_total` | counter | Total failed proofs |
| `prover_proof_cache_hits_total` | counter | Proof cache hits |
| `prover_last_proof_latency_ms` | gauge | Most recent proof duration in milliseconds |
| `prover_active_proofs` | gauge | Currently running proof generations |
| `prover_artifacts_ok` | gauge | 1 when all artifacts pass hash verification, 0 otherwise |
| `prover_last_input_bytes` | gauge | Request body size of the most recent proof |
| `prover_last_ticket_count` | gauge | Ticket count in the most recent proof |
| `prover_request_latency_seconds` | histogram | Proof generation latency histogram |
| `prover_up` | gauge | Always 1 while the process is running |

## Run

```bash
make prover
```

## Tests

```bash
cd prover && go test ./...
```

## Alerting

Prometheus alert rules live in `prover/alerts.yml`.
