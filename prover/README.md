# Prover

Go-based Groth16 prover service that generates settlement proofs. It validates circuit artifacts at startup, exposes health/metrics endpoints, and can stream proof responses over SSE.

**Entrypoint**
- `prover/main.go`

**Endpoints**
- `POST /api/v1/proofs/settlement` – Generate a settlement proof (supports `stream=1` or `Accept: text/event-stream`).
- `GET /healthz` – Health + artifact status (cached for a short TTL).
- `GET /heartbeat` – Liveness signal.
- `GET /metrics` – Prometheus metrics.
- `GET /metrics/expvar` – Expvar metrics (only when `PROVER_ENABLE_DEBUG=true`).
- `GET /debug/pprof/*` – pprof endpoints (only when `PROVER_ENABLE_DEBUG=true`).

**Auth**
- If `PROVER_SHARED_SECRET` is set, requests must include `X-Prover-Secret`.

**Operational behavior**
- Requires artifacts under `prover/circuits/build` (or `PROVER_CIRCUIT_DIR`). Startup fails if required artifacts are missing or hash mismatches are detected.
- Proof generation is capped by `PROVER_MAX_CONCURRENCY`. When at capacity, requests return HTTP `429`.
- Optional strict validation (`PROVER_STRICT_VALIDATION=true`) enforces internal consistency between totals and rake.

**Key configuration**
- `PROVER_LISTEN_ADDR` (default `0.0.0.0:8085`)
- `PROVER_SHARED_SECRET` (optional)
- `PROVER_ENABLE_DEBUG` (default `false`)
- `PROVER_MAX_CONCURRENCY`
- `PROVER_PROOF_TIMEOUT_SECONDS`
- `PROVER_REQUEST_TIMEOUT_SECONDS`
- `PROVER_MAX_REQUEST_BYTES`
- `PROVER_STRICT_VALIDATION` (default `false`)
- `PROVER_HEALTH_CACHE_SECONDS` (default `5`)
- HTTP timeouts:
  - `PROVER_READ_HEADER_TIMEOUT_SECONDS` (default `5`)
  - `PROVER_READ_TIMEOUT_SECONDS` (default `15`)
  - `PROVER_WRITE_TIMEOUT_SECONDS` (default `180`)
  - `PROVER_IDLE_TIMEOUT_SECONDS` (default `60`)
  - `PROVER_MAX_HEADER_BYTES` (default `1048576`)

**Run**
- `make prover`

**Tests**
- `cd prover && go test ./...`
