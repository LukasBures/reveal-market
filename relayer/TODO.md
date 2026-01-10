# Relayer TODO

## MVP
- Provide a relayer `.env.example` and doc snippet for compose/K8s, including ingest settings (`RELAYER_API_*`) and auth/rate-limit defaults.
- Expand tests to cover fee-bump retries and deadletter replay on both SQLite and Postgres queue backends.
- Add tests for `/lock-batches` validation (batch root computation, contiguous tickets) and ingest metadata requirements.

## Hardening
- Enforce bearer/IP/rate limits in production by default (config presets) and add coverage for auth failures.
- Expose queue depth/oldest job age in `/metrics` to alert on backlog growth.
