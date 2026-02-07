# Repository TODO

**MVP - Critical**
- Confirm production env secrets for API/worker/relayer/prover and deploy with `RM_INTERNAL_API_SECRET`.
- Verify prover artifacts and circuit hash are aligned across contracts, prover, and API.
- Validate cross-service internal network paths in docker compose and Caddy.

**MVP - High**
- Verify on-chain config (factory, verifier, escrow) and full settlement flow in staging.
- Load-test API + streamer for 100 concurrent users and adjust cache limits.

**MVP - Medium**
- Add dashboards for API latency, worker sync durations, and streamer staleness.
- Add a deploy smoke test that calls public endpoints and internal health checks.

**MVP - Low**
- Improve structured docs for ops runbooks (rollbacks, incident response).

**MVP - Nice to have**
- Add sampled tracing across API/worker/relayer.

**Production - Critical**
- Tighten firewall and private network rules so internal endpoints are not reachable publicly.
- Enable database backups and retention policy.
- Ensure redis persistence and memory limits are configured.

**Production - High**
- Automate database migrations and schema checks in CI/CD.
- Run continuous proof generation health checks.

**Production - Medium**
- Add multi-region read replicas for API or edge caching for heavy list endpoints.

**Production - Low**
- Add replay and audit tools for relayer and proof queues.

**Production - Nice to have**
- Add a canary deployment pipeline and rollout dashboards.
