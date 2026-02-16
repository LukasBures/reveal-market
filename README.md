# Reveal Market

Reveal Market is a multi-service stack for event-based prediction markets with on-chain settlement and off-chain ingestion, pricing, and UI.

**Services**
- `backend/api` FastAPI API for pricing, markets, trades, and internal ingestion hooks.
- `backend/worker` Async worker that syncs Polymarket/Gamma, hydrates caches, and drives settlement/proof queues.
- `streamer` FastAPI SSE/WS service for CLOB/RTDS data + FX prices with Redis-backed history.
- `relayer` FastAPI service that submits on-chain commit/claim/lock txs and optionally runs a queue.
- `hedger` FastAPI service for exposure/risk tracking and treasury snapshots.
- `frontend` Next.js 15 marketing/docs/market UI.
- `contracts` Foundry workspaces for on-chain contracts.
- `prover` Go-based Groth16 prover service.

**Public vs internal endpoints**
- Internal API hooks live under `/internal/*` and require `X-Internal-Secret`.
- The Caddy edge blocks `/internal/*` by default.
- Services should talk to each other on the Docker network using internal hostnames, not the public edge.

**Quick start (local)**
- `./run_local.sh` builds and launches the stack with cached BuildKit.
- `./run_prod.sh` performs cached builds and runs detached compose for prod-like runs.

**Tests**
- `make format`
- `make test`
- `./run_tests.sh` runs the full repo test sequence.

**Key env vars (high signal)**
- `RM_DATABASE_URL`, `RM_REDIS_URL` for API/worker.
- `RM_RPC_URL`, `RM_SETTLEMENT_SIGNER_PRIVATE_KEY` for on-chain operations.
- `RM_PRICING_SIGNER_PRIVATE_KEY` for quotes.
- `RM_INTERNAL_API_SECRET` for internal hooks.
- `RM_HEDGER_BASE_URL`, `RM_HEDGER_INTERNAL_SECRET` for post-commit hedging.
- `RM_HEDGER_QUEUE_ENABLED`, `RM_HEDGER_QUEUE_KEY` for hedger retry queue.
- `RELAYER_BEARER_TOKEN` or `RELAYER_ALLOW_INSECURE_AUTH=true` for relayer writes.
- `STREAMER_ACCESS_TOKEN` for streamer private access if enabled.
- `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_PRICE_STREAMER_URL` for frontend.

**Post-commit hedging (v1)**
- Commit tx is mined by the relayer (`status=1`) and then pushed to `POST /internal/commitments/sync`.
- The API records the commitment, then dispatches a hedger call to `POST /admin/commits`.
- Hedge failures never reject on-chain ingest; they are logged, alerted, and queued for retry.
- Hedger retries are processed by the API background loop `hedger_queue_loop`.

**Repo layout**
- `backend/` API + worker + shared models.
- `streamer/` price/data streamer.
- `relayer/` on-chain submitter.
- `hedger/` hedger service.
- `frontend/` Next.js site.
- `contracts/` Foundry workspaces.
- `prover/` Groth16 prover service.
