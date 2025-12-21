# MVP TODO
- Require auth by default (fail startup unless `RELAYER_BEARER_TOKEN` is set or an explicit dev override is enabled) and enforce it across `/commit`, `/claim`, `/status`, and `/admin/*`.
- Add abuse protection for write endpoints (rate limiting and optional IP allowlist) to prevent gas griefing.
- Add payload validation and preflight checks to avoid sending bad txs (bytes32/hex length validation, amount > 0, expiry > now, optional `eth_call`/`estimate_gas` guardrails).
- Surface queue health in `/healthz` (depth, deadletter count, oldest pending age) and add metrics for deadletter depth.
- Ship a relayer `.env.example` and document Docker/compose wiring, including `RELAYER_API_*` ingest settings.
- Add tests for preflight validation, fee-bump retries, and deadletter replay on SQLite + Postgres.
