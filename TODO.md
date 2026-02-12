# Repository TODO

**MVP Critical**
`backend`
- Validate `RM_INTERNAL_API_SECRET` is set for API and caller services.
- Confirm database schema matches expected `backend/shared/models.py`.
`contracts`
- Validate deployment scripts against current chain IDs.
- Confirm ownership transfers and admin keys are secured.
`contracts/zen`
- Validate `BATCH_SIZE=256` and `MERKLE_DEPTH=8` are consistent with prover.
- Confirm `Verifier` uses the correct circuit hash.
`frontend`
- Ensure `NEXT_PUBLIC_API_BASE_URL` and `NEXT_PUBLIC_PRICE_STREAMER_URL` are set in prod.
- Verify event cards load quickly with cache-friendly API queries.
`hedger`
- Confirm hedger admin routes are protected in prod.
`infra`
- Validate cross-service internal network paths in docker compose and Caddy.
`prover`
- Ensure circuit artifacts in `prover/circuits/build` match the deployed contracts (hashes + version).
`repo`
- Confirm production env secrets for API/worker/relayer/prover and deploy with `RM_INTERNAL_API_SECRET`.
- Verify prover artifacts and circuit hash are aligned across contracts, prover, and API.
`streamer`
- Confirm Redis history trimming is enforced for long-running streams.

**MVP High**
`api/streamer`
- Load-test API + streamer for 100 concurrent users and adjust cache limits.
`contracts`
- Verify on-chain config (factory, verifier, escrow) and full settlement flow in staging.
- Ensure settlement and verification flow matches prover circuit hash.
`frontend`
- Validate pagination limits and load-more behavior across all event lists.
`streamer`
- Validate rate-limit/connection guard defaults under expected load.

**MVP Medium**
`observability`
- Add dashboards for API latency, worker sync durations, and streamer staleness.
`ops`
- Add a deploy smoke test that calls public endpoints and internal health checks.
`streamer`
- Add tests for control endpoints and subgraph proxy error handling.

**MVP Low**
`docs`
- Improve structured docs for ops runbooks (rollbacks, incident response).

**MVP Nice to have**
`frontend`
- Add prefetch for event detail on hover.
`prover`
- Add structured logging to include proof input sizes and queue wait times.
`streamer`
- Add backpressure when active connections exceed capacity.
`tracing`
- Add sampled tracing across API/worker/relayer.

**Production Critical**
`backend`
- Formalize migration plan and schema versioning controls.
`db`
- Enable database backups and retention policy.
`frontend`
- Ensure CSP and security headers allow only required domains.
`hedger`
- Ensure secrets are managed via a vault or secret manager.
`infra`
- Tighten firewall and private network rules so internal endpoints are not reachable publicly.
`prover`
- Store proving keys in a secure store (KMS + sealed artifact distribution).
- Implement key rotation procedure with rollback safeguards.
`redis`
- Ensure redis persistence and memory limits are configured.
`relayer`
- Ensure key management and signing isolation for relayer private key.
`streamer`
- Ensure WS/SSE reconnect policies are tuned for prod traffic.

**Production High**
`backend`
- Add load-shedding strategy for DB outages and Redis failures.
`ci/cd`
- Automate database migrations and schema checks in CI/CD.
`hedger`
- Add multi-signer safety controls.
`prover`
- Run continuous proof generation health checks.
- Add autoscaling based on active proof concurrency and queue depth.
- Add a shared artifact cache for multi-instance deployments.

**Production Medium**
`api`
- Add multi-region read replicas for API or edge caching for heavy list endpoints.
`backend`
- Add structured alerts for API background task failures.
`hedger`
- Add staging simulation runbook.
`prover`
- Add canary proofs on deploys; block traffic if canary fails.

**Production Low**
`backend`
- Add auditing for quote issuance and consumption.
`contracts/zen`
- Add on-chain analytics for commitment counts.
`relayer/prover`
- Add replay and audit tools for relayer and proof queues.

**Production Nice to have**
`backend`
- Add read replica support and query routing.
`deploy`
- Add a canary deployment pipeline and rollout dashboards.
