# Worker TODO

Focused follow-ups for the ingestion/priming/proof worker.

## MVP-critical
- **Monitoring & alerts**: Add explicit alerts for stalled Gamma sync, missing heartbeats, and proof/settlement queue gaps so markets cannot silently skip proof generation.
- **Factory mirroring**: Stream factory events (Goldsky or RPC) for rake/signer/oracle/cap changes instead of relying solely on backfill, and record deltas in the ledger.

## Operational
- **Retention policy**: Decide whether to keep retention as metrics-only or enable deletes/archival; if enabling deletes, ensure cache tags and batch stats stay consistent.
- **Proof queue visibility**: Expose queue depth + oldest job age in `/metrics` and health to catch prover outages quickly.
