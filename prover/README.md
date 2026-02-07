# Prover

Go-based Groth16 prover service used for settlement proofs.

**Entrypoint**
- `prover/main.go`

**Key behavior**
- Validates circuits/artifacts at startup.
- Exposes `/healthz`, `/metrics`, and `/debug/pprof/*`.

**Run**
- `make prover`

**Tests**
- `cd prover && go test ./...`
