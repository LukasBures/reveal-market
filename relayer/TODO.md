# MVP TODO
- Ship a relayer `.env.example` and document Docker/compose wiring, including `RELAYER_API_*` ingest settings.
- Add tests for fee-bump retries and deadletter replay on SQLite + Postgres.
- Add tests for `/lock-batches` payload validation, Poseidon batch-root computation, and ingest metadata requirements.
